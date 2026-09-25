"""The router optimizer: split, gates, artifact, and live promotion.

The GEPA run itself is an operator command against a real provider. What these
tests cover is everything around it - the split, the gate, the artifact contract,
and the fact that a promoted artifact actually reaches the running program -
driven by a scripted LM so no provider is needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import dspy
import pytest
from dspy.utils.dummies import DummyLM

from app.agent.program import FleetAgent
from app.agent.routing import (
    ROUTER_STATE_FORMAT,
    ToolRoutingSignature,
    coerce_route,
    read_router_state,
    routing_signature,
)
from app.agent.tool_registry import TOOL_SPECS, ToolRegistry
from app.agent.tooling import create_dspy_tool
from app.agent.tools import search_docs
from evals.agent_tool_routing import ROUTING_EXAMPLES
from evals.optimize import RouterProgram, _report, main, split_examples
from tests.helpers.scripted_lm import _scripted_completion

# --- the split --------------------------------------------------------------


def test_split_is_disjoint_and_keeps_every_route_on_both_sides() -> None:
    train, held_out = split_examples(ROUTING_EXAMPLES, seed=17)

    train_ids = {id(example) for example in train}
    assert not (train_ids & {id(example) for example in held_out})
    assert len(train) + len(held_out) == len(ROUTING_EXAMPLES)

    train_routes = {coerce_route(getattr(e, "expected_route", None)) for e in train}
    held_routes = {coerce_route(getattr(e, "expected_route", None)) for e in held_out}
    assert train_routes == held_routes, "stratification must cover every profile"


def test_split_is_deterministic_for_a_seed() -> None:
    first = split_examples(ROUTING_EXAMPLES, seed=5)
    second = split_examples(ROUTING_EXAMPLES, seed=5)
    other = split_examples(ROUTING_EXAMPLES, seed=6)

    as_requests = lambda pair: [  # noqa: E731
        [e.user_request for e in pair[0]],
        [e.user_request for e in pair[1]],
    ]
    assert as_requests(first) == as_requests(second)
    assert as_requests(first) != as_requests(other)


# --- the artifact contract --------------------------------------------------


def _write_state(path: Path, **overrides: object) -> Path:
    payload = {
        "format": ROUTER_STATE_FORMAT,
        "router_instructions": "OPTIMIZED ROUTER RULES",
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_read_router_state_returns_the_promoted_instructions(tmp_path: Path) -> None:
    assert (
        read_router_state(_write_state(tmp_path / "s.json")) == "OPTIMIZED ROUTER RULES"
    )


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"format": "other/format@9"}, "is not"),
        ({"format": ROUTER_STATE_FORMAT}, "no router_instructions"),
        ({"format": ROUTER_STATE_FORMAT, "router_instructions": "   "}, "no router"),
    ],
)
def test_read_router_state_refuses_a_malformed_artifact(
    tmp_path: Path, payload: dict, match: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        read_router_state(path)


def test_read_router_state_refuses_a_missing_or_unreadable_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        read_router_state(tmp_path / "absent.json")

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not readable JSON"):
        read_router_state(broken)


# --- promotion reaches the running program ----------------------------------


def test_promoted_instructions_reach_the_router() -> None:
    baseline = dspy.Predict(ToolRoutingSignature)
    promoted = dspy.Predict(routing_signature("OPTIMIZED ROUTER RULES"))

    assert promoted.signature.instructions == "OPTIMIZED ROUTER RULES"
    assert baseline.signature.instructions != "OPTIMIZED ROUTER RULES"
    # The declared contract survives the override, Literal included.
    assert list(promoted.signature.output_fields) == ["route"]
    assert (
        promoted.signature.output_fields["route"].annotation
        == ToolRoutingSignature.output_fields["route"].annotation
    )


def _profiles():
    registry = ToolRegistry(
        [(create_dspy_tool(search_docs, name="search_docs"), TOOL_SPECS["search_docs"])]
    )
    return {"research": registry.dspy_tools(), "direct": []}


def test_fleet_agent_uses_promoted_instructions_when_given_them() -> None:
    agent = FleetAgent(
        tool_profiles=_profiles(), max_iters=2, router_instructions="PROMOTED"
    )
    baseline = FleetAgent(tool_profiles=_profiles(), max_iters=2)

    assert agent.router.signature.instructions == "PROMOTED"
    assert baseline.router.signature.instructions != "PROMOTED"
    # Overriding one program's router must not leak into the shared contract.
    assert ToolRoutingSignature.instructions != "PROMOTED"


# --- the gate, the artifact, and promotion ----------------------------------


class _PromptAwareLM(DummyLM):
    """Routes correctly only when the router carries the optimized rules.

    The router's instructions are part of the prompt, so a prompt that lacks the
    marker produces wrong routes and a low held-out mean - which is how the gate
    is exercised without a provider.
    """

    def __init__(self) -> None:
        super().__init__([{"route": "direct"}] * 400)

    def forward(self, prompt=None, messages=None, **kwargs):  # noqa: ANN001, ANN201
        del kwargs
        text = str(prompt or "") + str(messages or "")
        if "OPTIMIZED ROUTER RULES" in text:
            route = self._expected(text)
        else:
            # No promoted rules: answer with the least-privileged profile every
            # time, which is wrong for every example that needs more capability.
            route = "direct"
        return _scripted_completion([], json.dumps({"route": route}))

    @staticmethod
    def _expected(text: str) -> str:
        for example in ROUTING_EXAMPLES:
            if example.user_request in text:
                return coerce_route(example.expected_route)
        return "direct"


def _candidate_with(instructions: str) -> RouterProgram:
    program = RouterProgram()
    program.router.signature = ToolRoutingSignature.with_instructions(instructions)
    return program


def _run(tmp_path, monkeypatch, *, instructions: str, promote: bool, argv=None):
    lm = _PromptAwareLM()
    monkeypatch.setattr("evals.optimize._resolve_lm", lambda: lm)
    monkeypatch.setattr(
        "evals.optimize.compile_gepa_candidate",
        lambda program, **kwargs: _candidate_with(instructions),
    )
    monkeypatch.setattr("evals.optimize.ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(
        "evals.optimize.ACTIVE_POINTER", tmp_path / "artifacts" / "router_active.json"
    )
    monkeypatch.setattr("evals.optimize.log_optimization_run", lambda **kwargs: None)
    args = argv if argv is not None else (["--promote"] if promote else [])
    return main(args)


def test_a_better_candidate_passes_and_writes_an_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    code = _run(
        tmp_path, monkeypatch, instructions="OPTIMIZED ROUTER RULES", promote=False
    )

    assert code == 0
    dirs = list((tmp_path / "artifacts").glob("router_gepa_*"))
    assert len(dirs) == 1
    state = json.loads((dirs[0] / "router_state.json").read_text())
    assert state["format"] == ROUTER_STATE_FORMAT
    assert state["router_instructions"] == "OPTIMIZED ROUTER RULES"
    assert (dirs[0] / "manifest.json").is_file()
    assert (dirs[0] / "report.md").is_file()
    # an unpromoted run writes the artifact but no active pointer
    assert not (tmp_path / "artifacts" / "router_active.json").exists()


def test_promote_copies_the_state_to_the_active_pointer(
    tmp_path: Path, monkeypatch
) -> None:
    code = _run(
        tmp_path, monkeypatch, instructions="OPTIMIZED ROUTER RULES", promote=True
    )

    assert code == 0
    active = tmp_path / "artifacts" / "router_active.json"
    assert active.is_file()
    assert read_router_state(active) == "OPTIMIZED ROUTER RULES"


def test_no_improvement_is_rejected_and_writes_nothing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The gate is a gate: an identical candidate must not be promoted."""
    unchanged = ToolRoutingSignature.instructions
    code = _run(tmp_path, monkeypatch, instructions=unchanged, promote=True)

    assert code == 2
    captured = capsys.readouterr()
    assert "rejected" in captured.err
    assert not list((tmp_path / "artifacts").glob("router_gepa_*"))
    assert not (tmp_path / "artifacts" / "router_active.json").exists()


def test_validate_needs_no_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("evals.optimize._resolve_lm", lambda: None)
    assert main(["--validate"]) == 0


def test_a_run_without_a_provider_refuses_before_spending_anything(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr("evals.optimize._resolve_lm", lambda: None)
    assert main([]) == 2
    assert "no provider configured" in capsys.readouterr().err


def test_report_names_the_gate_and_both_means() -> None:
    from evals.scoring import RoutingScore

    text = _report(
        outcome="promoted",
        baseline=RoutingScore(mean=0.5, misses=[], mean_latency_s=1.0),
        candidate=RoutingScore(mean=0.9, misses=[], mean_latency_s=1.1),
        min_accuracy=0.8,
        budget="light",
        split=(32, 13),
        seed=0,
    )
    assert "promoted" in text
    assert "0.500" in text and "0.900" in text
    assert "candidate > baseline" in text


# --- the operator's pin reaches the engine ----------------------------------


def _built_program(tmp_path: Path, settings):
    import asyncio

    from app.agent.event_bus import RunEventBus
    from app.agent.factory import make_engine_builder
    from app.services.artifact_storage import LocalArtifactStorage

    builder = make_engine_builder(
        settings, storage=LocalArtifactStorage(tmp_path / "artifacts")
    )
    loop = asyncio.new_event_loop()
    try:
        engine = builder(RunEventBus(loop), thread_id="t-promoted")
        return engine._program_factory()  # type: ignore[attr-defined]
    finally:
        loop.close()


def test_factory_applies_a_pinned_router_artifact(tmp_path: Path) -> None:
    """An operator-pinned artifact must reach the program the engine builds."""
    from app.settings import Settings

    state = _write_state(tmp_path / "router.json")
    settings = Settings(router_state_path=str(state), llm_api_key=None)

    program = _built_program(tmp_path, settings)

    assert isinstance(program, FleetAgent)
    assert program.router.signature.instructions == "OPTIMIZED ROUTER RULES"


def test_factory_without_a_pin_keeps_the_baseline_router(tmp_path: Path) -> None:
    from app.settings import Settings

    settings = Settings(router_state_path=None, llm_api_key=None)
    program = _built_program(tmp_path, settings)

    assert program.router.signature.instructions == ToolRoutingSignature.instructions
    assert ToolRoutingSignature.instructions != "OPTIMIZED ROUTER RULES"


def test_a_malformed_pin_fails_at_build_time_rather_than_silently(
    tmp_path: Path,
) -> None:
    """A pinned artifact that cannot be read must not be ignored.

    An operator who sets the path expects it in effect; quietly falling back to
    the baseline would make a broken promotion look like a working one.
    """
    from app.settings import Settings

    broken = tmp_path / "router.json"
    broken.write_text("{not json", encoding="utf-8")
    settings = Settings(router_state_path=str(broken), llm_api_key=None)

    with pytest.raises(ValueError, match="not readable JSON"):
        _built_program(tmp_path, settings)


def test_identical_text_is_rejected_even_when_the_numbers_differ(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A depressed baseline must not promote a candidate that rewrote nothing.

    If two held-out calls raise on the baseline pass, its mean drops below the
    candidate's even when the candidate's instructions are byte-identical. The
    gate must reject on the text, not just the numbers.
    """
    from evals.scoring import RoutingScore

    monkeypatch.setattr("evals.optimize._resolve_lm", lambda: _PromptAwareLM())
    monkeypatch.setattr(
        "evals.optimize.compile_gepa_candidate",
        lambda program, **kwargs: _candidate_with(ToolRoutingSignature.instructions),
    )
    monkeypatch.setattr("evals.optimize.ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(
        "evals.optimize.ACTIVE_POINTER", tmp_path / "artifacts" / "router_active.json"
    )
    monkeypatch.setattr("evals.optimize.log_optimization_run", lambda **kwargs: None)

    calls = {"n": 0}

    def fake_score(router, lm, examples):
        calls["n"] += 1
        if calls["n"] == 1:
            return RoutingScore(mean=0.846, misses=[], mean_latency_s=1.0, failures=2)
        return RoutingScore(mean=1.0, misses=[], mean_latency_s=1.0, failures=0)

    monkeypatch.setattr("evals.optimize.score_router", fake_score)

    assert main([]) == 2
    assert "without rewriting" in capsys.readouterr().err
    assert not list((tmp_path / "artifacts").glob("router_gepa_*"))
    assert not (tmp_path / "artifacts" / "router_active.json").exists()


def test_provider_failure_exits_cleanly_and_is_logged(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A provider outage mid-run must not surface as a traceback."""
    logged: dict = {}
    monkeypatch.setattr("evals.optimize._resolve_lm", lambda: _PromptAwareLM())

    def boom(*args, **kwargs):
        raise RuntimeError("429 simulated outage")

    monkeypatch.setattr("evals.optimize.score_router", boom)
    monkeypatch.setattr("evals.optimize.ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(
        "evals.optimize.ACTIVE_POINTER", tmp_path / "artifacts" / "router_active.json"
    )
    monkeypatch.setattr(
        "evals.optimize.log_optimization_run", lambda **kwargs: logged.update(kwargs)
    )

    assert main([]) == 2
    assert "optimization failed" in capsys.readouterr().err
    assert logged.get("outcome") == "error"
    assert not (tmp_path / "artifacts").exists()
