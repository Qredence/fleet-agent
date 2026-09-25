"""The code capability: understand once, then loop change-verify.

The driver loop lives here because "did the tests pass?" is a computed
condition, not a field mapping - same boundary as FleetAgent's routing
conditional. The spec (``agents/code.yaml``) owns signatures, prompts, and
the module tree; this module owns sequencing and the stop condition.

``test_command`` is required, never defaulted: a code agent that silently
skips verification is the failure mode this capability exists to remove.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import dspy

from app.agent.signature import AGENTS_DIR
from app.agent.spec import AgentSpec, ToolRegistry, build_program, load_spec

SPEC_PATH = AGENTS_DIR / "code.yaml"


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of one verification run."""

    passed: bool
    summary: str


TestCommand = Callable[[], VerifyResult]
"""Runs the task's test suite. Must be bounded by the caller (timeout);
raised exceptions are recorded as failures, never propagated."""


@lru_cache(maxsize=1)
def code_spec() -> AgentSpec:
    """The declarative code definition, validated once per process."""
    return load_spec(SPEC_PATH)


def _node(
    name: str,
    *,
    tools: Sequence[dspy.Tool] | None = None,
    max_iters: int | None = None,
) -> dspy.Module:
    """Build one code node from the spec, optionally overriding wiring.

    Only ``tools`` and ``max_iters`` may be overridden: everything else about
    a node (its signature, its prompt, its type) comes from the YAML, so an
    override can never silently redefine what the node is.
    """
    spec = code_spec().model_copy(deep=True)
    update: dict[str, Any] = {}
    if tools is not None:
        update["tools"] = [str(tool.name) for tool in tools]
    if max_iters is not None:
        update["max_iters"] = max_iters
    spec.root = name
    spec.modules = {name: spec.modules[name].model_copy(update=update)}
    registry = (
        ToolRegistry({str(tool.name): tool for tool in tools})
        if tools is not None
        else None
    )
    return build_program(spec, tools=registry)


def build_code_agent(
    tools: Sequence[dspy.Tool],
    *,
    test_command: TestCommand,
    max_attempts: int = 3,
    max_iters: int = 6,
) -> CodeAgent:
    """Assemble the code agent from spec-built nodes and a test command."""
    return CodeAgent(
        understand=_node("understand"),
        change=_node("change", tools=tools, max_iters=max_iters),
        answer=_node("answer"),
        test_command=test_command,
        max_attempts=max_attempts,
    )


class CodeAgent(dspy.Module):  # type: ignore[misc]  # DSPy is untyped
    """Understand once, then change-and-verify until green or spent.

    The submodules are spec-built nodes (see ``build_code_agent``), so their
    prompts and contracts stay declarative. The loop itself is plain Python:
    only it can observe the test outcome and decide whether another attempt
    is warranted.
    """

    def __init__(
        self,
        *,
        understand: dspy.Module,
        change: dspy.Module,
        answer: dspy.Module,
        test_command: TestCommand,
        max_attempts: int = 3,
    ) -> None:
        super().__init__()
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.understand = understand
        self.change = change
        self.answer = answer
        self._test_command = test_command
        self._max_attempts = max_attempts

    def forward(
        self,
        *,
        user_request: str,
        history: Any | None = None,
    ) -> dspy.Prediction:
        """Plan, change-and-verify, then report honestly."""
        if not user_request.strip():
            raise ValueError("user_request must not be empty")
        understood = self.understand(user_request=user_request)
        plan = getattr(understood, "plan", "")
        failure = ""
        result = VerifyResult(passed=False, summary="not run")
        attempts = 0
        for _ in range(self._max_attempts):
            attempts += 1
            self.change(
                user_request=user_request,
                plan=plan,
                previous_failure=failure,
                history=history,
            )
            try:
                result = self._test_command()
            except Exception as exc:
                result = VerifyResult(
                    passed=False, summary=f"test command failed: {exc}"
                )
            if result.passed:
                break
            failure = result.summary
        if result.passed:
            test_result = f"passed after {attempts} attempt(s): {result.summary}"
            termination_reason = "verified"
        else:
            test_result = f"FAILED after {attempts} attempt(s): {result.summary}"
            termination_reason = "unverified"
        final = self.answer(user_request=user_request, test_result=test_result)
        out = dspy.Prediction(
            answer=getattr(final, "answer", None),
            process_summary=getattr(final, "process_summary", None),
            key_decisions=list(getattr(final, "key_decisions", None) or []),
            caveats=list(getattr(final, "caveats", None) or []),
            termination_reason=termination_reason,
        )
        return out
