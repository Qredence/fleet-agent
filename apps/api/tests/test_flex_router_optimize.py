"""Self-improvement loop tests: Flex router state, gates, artifacts.

Harness tests (gates, artifact layout, promotion pointer) never touch Deno:
the Flex sandbox is only spawned at ``forward``. Tests that actually run
evolved or baseline source through the interpreter are gated on a local
Deno runtime, which CI does not install.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import dspy
import pytest

import evals.optimize as optimize
from app.agent.factory import _promoted_router_src, build_tool_profiles
from app.agent.flex_router import (
    ROUTER_STATE_FORMAT,
    FlexToolRouter,
    load_flex_router,
    load_flex_router_from_file,
)
from app.agent.program import FleetAgent
from app.agent.routing import ROUTES, ToolRoutingSignature, coerce_route
from app.agent.tool_registry import ToolMetadata, ToolRegistry
from evals.agent_tool_routing import ROUTING_EXAMPLES
from tests.helpers.scripted_lm import ScriptedLM, router_call

requires_deno = pytest.mark.skipif(
    shutil.which("deno") is None, reason="Flex sandbox needs a Deno runtime"
)

_FAKE_MODULE_SRC = (
    "class Evolved(dspy.Module):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "        self.predict = dspy.Predict('user_request -> route')\n"
    "\n"
    "    def forward(self, **inputs):\n"
    "        return self.predict(**inputs)\n"
)


def _probe_registry() -> ToolRegistry:
    def probe(query: str) -> str:
        """Return one deterministic value."""
        return "probe"

    return ToolRegistry([(probe, ToolMetadata(name="probe", capability="retrieval"))])


class _StubRouter(dspy.Module):  # type: ignore[misc]
    """Deterministic router stand-in; no sandbox, no LM."""

    def forward(self, *, user_request: str) -> dspy.Prediction:
        del user_request
        return dspy.Prediction(route="research")


def _wire_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    baseline_mean: float,
    candidate_mean: float,
    candidate_src: str = _FAKE_MODULE_SRC,
) -> None:
    """Point the optimizer at tmp_path with canned scores and no provider."""
    monkeypatch.setattr(optimize, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(
        optimize, "ACTIVE_POINTER", tmp_path / "flex_router_active.json"
    )
    monkeypatch.setattr(
        optimize, "_resolve_lm", lambda: ScriptedLM([router_call("research")])
    )
    monkeypatch.setattr("shutil.which", lambda name: f"/fake/{name}")
    # Harness tests assert file/gate behavior; the MLflow history logging is
    # spied separately where it matters and never writes a real store here.
    monkeypatch.setattr(optimize, "log_optimization_run", lambda **kwargs: None)

    scores = iter([(baseline_mean, [], 0.01), (candidate_mean, [], 0.02)])

    def fake_score(router: Any, lm: Any, examples: Any) -> Any:
        del router, lm, examples
        return next(scores)

    monkeypatch.setattr(optimize, "_score_router", fake_score)

    def fake_compile(program: Any, **kwargs: Any) -> Any:
        del program, kwargs
        return SimpleNamespace(flex=SimpleNamespace(module_src=candidate_src))

    monkeypatch.setattr(optimize, "compile_gepa_candidate", fake_compile)


class TestStratifiedSplit:
    def test_split_is_deterministic_and_route_balanced(self):
        train_a, val_a = optimize.stratified_split(ROUTING_EXAMPLES)
        train_b, val_b = optimize.stratified_split(ROUTING_EXAMPLES)

        assert train_a == train_b and val_a == val_b
        assert len(train_a) + len(val_a) == len(ROUTING_EXAMPLES)
        # Every route stays in both halves: the candidate must keep learning
        # every route and the held-out score must see every route.
        assert {e.expected_route for e in train_a} == set(ROUTES)
        assert {e.expected_route for e in val_a} == set(ROUTES)
        train_requests = {str(e.user_request) for e in train_a}
        val_requests = {str(e.user_request) for e in val_a}
        assert not train_requests & val_requests


class TestFlexRouterState:
    def test_binds_baseline_source_at_construction(self):
        router = FlexToolRouter()

        src = router.module_src()

        assert "dspy.Predict" in src
        assert "forward" in src
        # The rendered signature keeps the least-privilege vocabulary, so the
        # sandbox baseline cannot invent capabilities outside the routes.
        for route in ROUTES:
            assert route in src

    def test_load_flex_router_round_trips_module_src(self):
        state = {"module_src": _FAKE_MODULE_SRC, "lm": None}

        loaded = load_flex_router(state)

        assert loaded.module_src() == _FAKE_MODULE_SRC

    def test_load_flex_router_rejects_state_without_source(self):
        with pytest.raises(ValueError, match="module_src"):
            load_flex_router({"lm": None})
        with pytest.raises(ValueError, match="module_src"):
            load_flex_router({"module_src": "   "})

    def test_load_from_file_rejects_missing_and_malformed(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="FLEET_AGENT_ROUTER_STATE"):
            load_flex_router_from_file(tmp_path / "absent.json")

        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_flex_router_from_file(bad_json)

        bad_shape = tmp_path / "shape.json"
        bad_shape.write_text(json.dumps(["nope"]), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON object"):
            load_flex_router_from_file(bad_shape)

        no_src = tmp_path / "no_src.json"
        no_src.write_text(json.dumps({"format": ROUTER_STATE_FORMAT}), encoding="utf-8")
        with pytest.raises(ValueError, match="module_src"):
            load_flex_router_from_file(no_src)

    @requires_deno
    def test_promoted_state_file_loads_and_routes(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "format": ROUTER_STATE_FORMAT,
                    "module_src": _FAKE_MODULE_SRC,
                    "lm": None,
                }
            ),
            encoding="utf-8",
        )

        router = load_flex_router_from_file(state_file)

        assert router.module_src() == _FAKE_MODULE_SRC


class TestOptimizerGates:
    def test_refuses_regression_and_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _wire_harness(
            monkeypatch,
            tmp_path,
            baseline_mean=1.0,
            candidate_mean=0.5,
        )

        exit_code = optimize.main(["--auto", "light"])

        assert exit_code == 2
        assert list(tmp_path.iterdir()) == []

    def test_refuses_floor_miss_and_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _wire_harness(
            monkeypatch,
            tmp_path,
            baseline_mean=0.6,
            candidate_mean=0.75,  # beats baseline, below --min-accuracy 0.9
        )

        assert optimize.main(["--auto", "light", "--min-accuracy", "0.9"]) == 2
        assert list(tmp_path.iterdir()) == []

    def test_writes_versioned_artifact_when_gates_pass(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        _wire_harness(
            monkeypatch,
            tmp_path,
            baseline_mean=0.8,
            candidate_mean=1.0,
        )

        exit_code = optimize.main(["--auto", "light", "--seed", "3"])

        assert exit_code == 0
        (artifact_dir,) = [p for p in tmp_path.iterdir() if p.is_dir()]
        assert artifact_dir.name.startswith("flex_router_gepa_")

        state = json.loads((artifact_dir / "state.json").read_text(encoding="utf-8"))
        assert state == {
            "format": ROUTER_STATE_FORMAT,
            "module_src": _FAKE_MODULE_SRC,
            "lm": None,
        }

        manifest = json.loads(
            (artifact_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["budget"] == "light"
        assert manifest["seed"] == 3
        assert manifest["baseline_mean"] == 0.8
        assert manifest["candidate_mean"] == 1.0
        assert manifest["dspy_version"] == dspy.__version__

        report = (artifact_dir / "report.md").read_text(encoding="utf-8")
        assert "PASSED" in report
        assert _FAKE_MODULE_SRC in report
        assert (artifact_dir / "module_src.py").read_text(
            encoding="utf-8"
        ).strip() == _FAKE_MODULE_SRC.strip()

        # The state is loadable and the promote instructions name the artifact.
        assert load_flex_router(state).module_src() == _FAKE_MODULE_SRC
        assert str(artifact_dir) in capsys.readouterr().out

    def test_promote_copies_pointer_without_optimizing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        _wire_harness(monkeypatch, tmp_path, baseline_mean=0.0, candidate_mean=0.0)
        artifact = tmp_path / "flex_router_gepa_test"
        artifact.mkdir()
        (artifact / "state.json").write_text(
            json.dumps(
                {
                    "format": ROUTER_STATE_FORMAT,
                    "module_src": _FAKE_MODULE_SRC,
                    "lm": None,
                }
            ),
            encoding="utf-8",
        )

        exit_code = optimize.main(["--promote", "--artifact", str(artifact)])

        assert exit_code == 0
        pointer = tmp_path / "flex_router_active.json"
        assert (
            json.loads(pointer.read_text(encoding="utf-8"))["module_src"]
            == _FAKE_MODULE_SRC
        )
        assert "FLEET_AGENT_ROUTER_STATE" in capsys.readouterr().out

    def test_promote_without_artifacts_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _wire_harness(monkeypatch, tmp_path, baseline_mean=0.0, candidate_mean=0.0)

        assert optimize.main(["--promote"]) == 1

    def test_logs_mlflow_attempt_outcome_on_pass_and_fail(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        outcomes: list[str] = []

        def spy_log(**kwargs: Any) -> str:
            outcomes.append(str(kwargs["outcome"]))
            assert kwargs["budget"] == "light"
            return "mlflow-run-id"

        _wire_harness(monkeypatch, tmp_path, baseline_mean=0.5, candidate_mean=1.0)
        monkeypatch.setattr(optimize, "log_optimization_run", spy_log)

        assert optimize.main(["--auto", "light"]) == 0
        assert outcomes == ["artifact-written"]

        # A rejected candidate is logged too: the attempt history matters.
        _wire_harness(monkeypatch, tmp_path, baseline_mean=1.0, candidate_mean=0.5)
        monkeypatch.setattr(optimize, "log_optimization_run", spy_log)

        assert optimize.main(["--auto", "light"]) == 2
        assert outcomes == ["artifact-written", "gates-failed"]


class TestRuntimeWiring:
    def test_fleet_agent_accepts_injected_router_and_defaults_to_predict(self):
        profiles = build_tool_profiles(_probe_registry())

        injected = FleetAgent(tool_profiles=profiles, max_iters=2, router=_StubRouter())
        default = FleetAgent(tool_profiles=profiles, max_iters=2)

        assert isinstance(injected.router, _StubRouter)
        assert isinstance(default.router, dspy.Predict)
        assert default.router.signature == ToolRoutingSignature

    def test_router_output_still_coerces_to_least_privilege(self):
        # Degenerate router output must degrade to direct, never grant tools.
        assert coerce_route("workspace_shell") == "workspace_shell"
        assert coerce_route("sudo everything") == "direct"
        assert coerce_route(None) == "direct"

    def test_promoted_router_src_none_when_unset(self):
        settings = SimpleNamespace(router_state_path=None)

        assert _promoted_router_src(settings) is None  # type: ignore[arg-type]

    def test_promoted_router_src_fails_fast_on_missing_file(self, tmp_path: Path):
        settings = SimpleNamespace(router_state_path=str(tmp_path / "absent.json"))

        with pytest.raises(FileNotFoundError, match="FLEET_AGENT_ROUTER_STATE"):
            _promoted_router_src(settings)  # type: ignore[arg-type]

    @requires_deno
    def test_promoted_router_src_returns_bound_source(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "format": ROUTER_STATE_FORMAT,
                    "module_src": _FAKE_MODULE_SRC,
                    "lm": None,
                }
            ),
            encoding="utf-8",
        )

        src = _promoted_router_src(SimpleNamespace(router_state_path=str(state_file)))  # type: ignore[arg-type]

        assert src == _FAKE_MODULE_SRC


class TestSandboxForward:
    """Real interpreter runs; local-only because CI lacks Deno."""

    @requires_deno
    def test_baseline_router_forwards_through_the_sandbox(self):
        router = FlexToolRouter()
        adapter = dspy.JSONAdapter(use_native_function_calling=True)

        with dspy.context(lm=ScriptedLM([router_call("research")]), adapter=adapter):
            prediction = router(user_request="Search the docs for AG-UI state sync.")

        assert prediction.route == "research"
        assert coerce_route(getattr(prediction, "route", None)) == "research"

    @requires_deno
    def test_loaded_state_forwards_through_the_sandbox(self):
        # A state rebuilt from dump/load behaves like the original program.
        original = FlexToolRouter()
        state: Mapping[str, Any] = {"module_src": original.module_src(), "lm": None}
        rebuilt = load_flex_router(state)
        adapter = dspy.JSONAdapter(use_native_function_calling=True)

        with dspy.context(
            lm=ScriptedLM([router_call("workspace_read")]), adapter=adapter
        ):
            prediction = rebuilt(user_request="Find where FleetAgent is defined.")

        assert prediction.route == "workspace_read"


class TestExtractModuleSrc:
    def test_extracts_evolved_source_from_candidate(self):
        candidate = SimpleNamespace(flex=SimpleNamespace(module_src=_FAKE_MODULE_SRC))

        assert optimize._extract_module_src(candidate) == _FAKE_MODULE_SRC

    def test_rejects_candidate_without_source(self):
        with pytest.raises(RuntimeError, match="module_src"):
            optimize._extract_module_src(SimpleNamespace(flex=SimpleNamespace()))
