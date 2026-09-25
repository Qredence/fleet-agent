"""The code capability: plan, change-and-verify, report honestly.

The loop is the product: these tests drive it with a scripted LM while keeping
everything else real (real workspace tools on a temp copy, real pytest for the
happy path, stubbed verdicts where determinism matters).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import dspy
import pytest

from app.agent.code import (
    VerifyResult,
    build_code_agent,
    code_spec,
)
from app.agent.tools.workspace import WorkspacePolicy, WorkspaceTools
from evals.code import FIXTURE_DIR, TASK, run_pytest, validate_code_fixture
from tests.helpers.scripted_lm import ScriptedLM, evidence_end

FIXED_CALC = "def add(a: int, b: int) -> int:\n    return a + b\n"


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "code"
    shutil.copytree(FIXTURE_DIR, workspace)
    return workspace


def _tools(workspace: Path) -> list:
    return WorkspaceTools(
        WorkspacePolicy(root=workspace, allow_write=True, allow_bash=True)
    ).dspy_tools()


def _understand_step(plan: str = "Fix the operator in calc.py") -> dict:
    return {
        "calls": [],
        "content": json.dumps({"plan": plan, "files_to_touch": ["calc.py"]}),
    }


def _answer_step(answer: str = "Fixed.") -> dict:
    return {
        "calls": [],
        "content": json.dumps(
            {
                "answer": answer,
                "process_summary": "Changed, verified.",
                "key_decisions": ["minimal fix"],
                "caveats": [],
            }
        ),
    }


class RecordingLM(ScriptedLM):
    """ScriptedLM that also records every rendered prompt."""

    def __init__(self, steps: list) -> None:
        super().__init__(steps)
        self.prompts: list[str] = []

    def forward(self, prompt=None, messages=None, **kwargs):  # noqa: ANN001, ANN201
        for message in messages or []:
            content = message.get("content")
            if isinstance(content, str):
                self.prompts.append(content)
        if isinstance(prompt, str):
            self.prompts.append(prompt)
        return super().forward(prompt=prompt, messages=messages, **kwargs)


def _run(agent, lm) -> dspy.Prediction:
    adapter = dspy.JSONAdapter(use_native_function_calling=True)
    with dspy.context(lm=lm, adapter=adapter):
        return agent(user_request=TASK)


def test_code_spec_loads_and_builds_all_three_nodes(tmp_path: Path) -> None:
    spec = code_spec()
    assert spec.agent == "code"
    assert set(spec.modules) == {"understand", "change", "answer"}

    agent = build_code_agent(
        _tools(_workspace(tmp_path)),
        test_command=lambda: VerifyResult(passed=True, summary="ok"),
    )
    names = [name for name, _ in agent.named_predictors()]
    # The react loop exposes its inner predictor by path, exactly like the
    # routed program's evidence loops - every step stays optimizable.
    assert {"understand", "change.react", "answer"} <= set(names)


def test_happy_path_verifies_with_real_tools_and_real_pytest(tmp_path: Path) -> None:
    """Everything real except the LM: tools execute, pytest decides."""
    workspace = _workspace(tmp_path)
    agent = build_code_agent(
        _tools(workspace),
        test_command=lambda: run_pytest(workspace),
    )
    lm = ScriptedLM(
        [
            _understand_step(),
            [{"name": "read", "args": {"path": "calc.py"}}],
            [{"name": "write", "args": {"path": "calc.py", "content": FIXED_CALC}}],
            evidence_end(),
            _answer_step("Fixed calc.add; suite green."),
        ]
    )
    result = _run(agent, lm)

    assert result.termination_reason == "verified"
    assert "green" in str(result.answer)
    assert (workspace / "calc.py").read_text() == FIXED_CALC


def test_retry_feeds_the_failure_into_the_next_attempt(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    calls = {"n": 0}

    def flaky() -> VerifyResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return VerifyResult(passed=False, summary="1 failed: assert -1 == 5")
        return VerifyResult(passed=True, summary="2 passed")

    agent = build_code_agent(_tools(workspace), test_command=flaky)
    seen: list[tuple[int, str]] = []

    # Match the rendered VALUE marker, not the bare field name: the signature
    # schema repeats every field name on every turn, while the value section
    # carries what this attempt actually received.
    marker = "[[ ## previous_failure ## ]]"

    class AttemptAwareLM(RecordingLM):
        def forward(self, prompt=None, messages=None, **kwargs):  # noqa: ANN001, ANN201
            for message in messages or []:
                content = message.get("content")
                if isinstance(content, str) and marker in content:
                    seen.append((calls["n"], content))
            return super().forward(prompt=prompt, messages=messages, **kwargs)

    agent = build_code_agent(_tools(workspace), test_command=flaky)
    lm = AttemptAwareLM(
        [
            _understand_step(),
            [{"name": "read", "args": {"path": "calc.py"}}],
            evidence_end(),
            [{"name": "read", "args": {"path": "calc.py"}}],
            evidence_end(),
            _answer_step("Fixed on the second attempt."),
        ]
    )
    result = _run(agent, lm)

    assert calls["n"] == 2
    assert result.termination_reason == "verified"

    # Change prompts rendered before any test ran carry no failure; prompts
    # rendered after the first failure carry its summary.
    # The marker also appears in a template echo that carries the literal
    # ``{previous_failure}`` placeholder on every turn. Only value renders -
    # lines without the placeholder - prove what an attempt actually received.
    def values(pairs):
        return [
            text
            for _, text in pairs
            if "[[ ## previous_failure ## ]]" in text
            and "{previous_failure}" not in text
        ]

    assert seen, "the change loop must render its inputs"
    before = values([p for p in seen if p[0] == 0])
    assert before and all("assert -1 == 5" not in text for text in before)
    after = values([p for p in seen if p[0] == 1])
    assert after and all("assert -1 == 5" in text for text in after)


def test_budget_exhausted_reports_failure_honestly(tmp_path: Path) -> None:
    """The answer step receives the failure state; the run must not claim success."""
    workspace = _workspace(tmp_path)
    calls = {"n": 0}

    def always_fails() -> VerifyResult:
        calls["n"] += 1
        return VerifyResult(passed=False, summary="still red")

    agent = build_code_agent(
        _tools(workspace), test_command=always_fails, max_attempts=2
    )
    seen_inputs: list[dict] = []

    lm = RecordingLM(
        [
            _understand_step(),
            evidence_end(),
            evidence_end(),
            _answer_step("Could not fix it."),
        ]
    )
    original_forward = RecordingLM.forward

    def spy_forward(self, prompt=None, messages=None, **kwargs):
        for message in messages or []:
            content = message.get("content")
            if isinstance(content, str) and "test_result" in content:
                seen_inputs.append(content)
        return original_forward(self, prompt, messages, **kwargs)

    RecordingLM.forward = spy_forward  # type: ignore[method-assign]
    try:
        result = _run(agent, lm)
    finally:
        RecordingLM.forward = original_forward  # type: ignore[method-assign]

    assert calls["n"] == 2
    assert result.termination_reason == "unverified"
    assert seen_inputs, "the answer step must receive the test outcome"
    assert "FAILED" in seen_inputs[-1]


def test_empty_request_rejected(tmp_path: Path) -> None:
    agent = build_code_agent(
        _tools(_workspace(tmp_path)),
        test_command=lambda: VerifyResult(passed=True, summary="ok"),
    )
    with pytest.raises(ValueError, match="must not be empty"):
        with dspy.context(lm=ScriptedLM([])):
            agent(user_request="   ")


def test_metric_fails_pre_fix_and_passes_post_fix(tmp_path: Path) -> None:
    """The eval machinery itself, with no LM involved."""
    workspace = _workspace(tmp_path)
    assert validate_code_fixture() == []

    before = run_pytest(workspace)
    assert not before.passed

    (workspace / "calc.py").write_text(FIXED_CALC)
    after = run_pytest(workspace)
    assert after.passed
