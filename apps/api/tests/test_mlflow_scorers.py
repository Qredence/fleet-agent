"""MLflow genai scorers: deterministic budgets first, the LLM judge opt-in.

Hermetic: the tests that talk to MLflow pin the tracking store and the artifact
root to ``tmp_path``. No test calls a provider — the judge is constructed, never
invoked, and the one real ``mlflow.genai.evaluate`` run uses a plain Python
``predict_fn``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.routing import ROUTES
from app.services.mlflow_observability import ARTIFACT_ROOT_ENV
from evals.agent_tool_routing import ROUTING_EXAMPLES, routing_metric
from evals.datasets import build_dataset, dataset_digest, routing_records
from evals.mlflow_tracking import ROUTING_EVAL_EXPERIMENT
from evals.run import main as eval_run_main
from evals.scorers import (
    DEFAULT_LATENCY_BUDGET_S,
    DEFAULT_TOOL_CALL_BUDGET,
    JUDGE_MODEL_ENV,
    answer_quality_judge,
    deterministic_scorers,
    latency_budget,
    route_least_privilege,
    tool_call_budget,
)
from evals.scoring import RoutingScore


@pytest.fixture(autouse=True)
def _restore_mlflow_env() -> Iterator[None]:
    """Restore the MLFLOW_* environment block after every test.

    ``mlflow.set_tracking_uri`` and ``mlflow.set_experiment`` write
    ``MLFLOW_TRACKING_URI`` and ``MLFLOW_EXPERIMENT_ID`` into the environment
    "so that subprocess can inherit it" (verified in mlflow 3.16.0). The shared
    conftest purges ``FLEET_AGENT_*`` and ``MLFLOW_*`` between tests, and
    ``resolve_tracking_uri`` reads the environment first — so a test that
    resolves a store would otherwise repoint every later test, including
    ``test_mlflow_tracing.py``, at a tmp store that no longer exists.
    """
    before = {
        key: value for key, value in os.environ.items() if key.startswith("MLFLOW")
    }
    yield
    for key in [k for k in os.environ if k.startswith("MLFLOW") and k not in before]:
        del os.environ[key]
    os.environ.update(before)


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Pin both the tracking store and the artifact root to ``tmp_path``."""
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setenv("FLEET_AGENT_MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(tmp_path / "artifacts"))
    return uri


def _row(route: str, expected: str) -> dict[str, Any]:
    return {
        "inputs": {"user_request": f"request for {expected}"},
        "outputs": {"route": route},
        "expectations": {"expected_route": expected},
    }


def _fake_trace(spans: list[str] | None = None, duration_ms: float | None = None):
    """A trace stand-in: the scorers only read ``data.spans`` and ``info``.

    ``spans=None`` models a row whose prediction was never traced, which is a
    different observation from a traced run that made no tool calls.
    """
    traced = None if spans is None else [SimpleNamespace(span_type=k) for k in spans]
    return SimpleNamespace(
        data=SimpleNamespace(spans=traced),
        info=SimpleNamespace(execution_duration=duration_ms),
    )


class TestLeastPrivilegeScorer:
    def test_exact_over_and_under_selection(self) -> None:
        assert route_least_privilege(**_row("workspace_read", "workspace_read")) == 1.0
        over = route_least_privilege(**_row("workspace_shell", "workspace_read"))

        assert over == 0.35
        assert route_least_privilege(**_row("direct", "workspace_write")) == 0.0

    def test_agrees_with_the_shared_metric(self) -> None:
        """One definition of least privilege, or the numbers drift apart."""
        import dspy

        gold = dspy.Example(expected_route="artifact")
        assert route_least_privilege(**_row("research", "artifact")) == float(
            routing_metric(gold, dspy.Prediction(route="research")).score
        )

    def test_an_invented_route_is_coerced_to_the_least_capability(self) -> None:
        assert route_least_privilege(**_row("web_search", "workspace_shell")) == 0.0


class TestToolCallBudget:
    def test_reported_calls_inside_the_budget_pass(self) -> None:
        outputs = {"tool_calls": 2}

        assert tool_call_budget(outputs=outputs, expectations={}) == 1.0
        assert (
            tool_call_budget(
                outputs={"tool_calls": DEFAULT_TOOL_CALL_BUDGET}, expectations={}
            )
            == 1.0
        )

    def test_overrun_is_penalised_in_proportion(self) -> None:
        budget = 4.0
        expectations = {"max_tool_calls": budget}

        half_over = tool_call_budget(
            outputs={"tool_calls": 6}, expectations=expectations
        )

        assert half_over == pytest.approx(0.5)
        assert tool_call_budget(
            outputs={"tool_calls": 4 * budget}, expectations=expectations
        ) == pytest.approx(0.0)

    def test_falls_back_to_the_traces_tool_spans(self) -> None:
        trace = _fake_trace(spans=["LLM", "TOOL", "CHAIN", "TOOL"])

        assert tool_call_budget(trace=trace, expectations={"max_tool_calls": 2}) == 1.0
        assert tool_call_budget(
            trace=trace, expectations={"max_tool_calls": 1}
        ) == pytest.approx(0.0)

    def test_a_row_with_nothing_to_measure_is_skipped(self) -> None:
        """An unobserved run must not look efficient."""
        assert tool_call_budget(outputs={}, expectations={}) is None
        assert tool_call_budget(trace=_fake_trace(), expectations={}) is None

    def test_a_traced_run_that_called_no_tool_scores_full_marks(self) -> None:
        """Zero observed calls is an observation, not a missing one."""
        observed_none = _fake_trace(spans=[])

        assert tool_call_budget(trace=observed_none, expectations={}) == 1.0


class TestLatencyBudget:
    def test_reported_seconds_inside_the_budget_pass(self) -> None:
        assert latency_budget(outputs={"latency_s": 1.5}, expectations={}) == 1.0

    def test_trace_milliseconds_are_converted_to_seconds(self) -> None:
        over = _fake_trace(duration_ms=DEFAULT_LATENCY_BUDGET_S * 1000 * 2)

        assert latency_budget(trace=over, expectations={}) == pytest.approx(0.0)
        inside = _fake_trace(duration_ms=DEFAULT_LATENCY_BUDGET_S * 1000)
        assert latency_budget(trace=inside, expectations={}) == 1.0

    def test_a_row_with_nothing_to_measure_is_skipped(self) -> None:
        assert latency_budget(outputs={}, expectations={}) is None
        assert latency_budget(trace=_fake_trace(), expectations={}) is None


class TestJudgeIsOptIn:
    def test_deterministic_scorers_never_include_a_judge(self) -> None:
        scorers = deterministic_scorers()

        assert [scorer.name for scorer in scorers] == [
            "fleet_route_least_privilege",
            "fleet_tool_call_budget",
            "fleet_latency_budget",
        ]

    def test_the_judge_refuses_to_default_to_a_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(JUDGE_MODEL_ENV, raising=False)

        with pytest.raises(ValueError, match="needs a model"):
            answer_quality_judge()

    def test_a_named_model_builds_a_scorer_without_calling_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Construction is offline (verified on mlflow 3.16.0); scoring is not."""
        from mlflow.genai.scorers import Scorer

        monkeypatch.setenv(JUDGE_MODEL_ENV, "openai:/gpt-4o-mini")

        judge = answer_quality_judge()

        assert isinstance(judge, Scorer)
        assert judge.name == "fleet_answer_quality"


class TestGenaiEvaluate:
    def _one_example_per_route(self) -> list[Any]:
        return [
            next(e for e in ROUTING_EXAMPLES if e.expected_route == route)
            for route in ROUTES
        ]

    def test_scores_the_versioned_dataset_with_the_deterministic_scorers(
        self, store: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real mlflow.genai.evaluate over the real dataset and scorers.

        The predict function answers every row with ``workspace_shell``, the
        most capable profile, so the metric has to return 1.0 for the one row
        that needs it and 0.35 (the over-selection penalty) for the other five.
        """
        import mlflow
        from mlflow.tracking import MlflowClient

        examples = self._one_example_per_route()
        monkeypatch.setattr("evals.datasets.ROUTING_EXAMPLES", examples)
        from evals.mlflow_tracking import use_experiment

        dataset = build_dataset()
        use_experiment(ROUTING_EVAL_EXPERIMENT)

        def predict(**inputs: Any) -> dict[str, Any]:
            return {"route": "workspace_shell", "tool_calls": 1, "latency_s": 0.5}

        result = mlflow.genai.evaluate(
            data=dataset, scorers=deterministic_scorers(), predict_fn=predict
        )

        expected_route_mean = (5 * 0.35 + 1.0) / len(examples)
        metrics = {name: float(value) for name, value in result.metrics.items()}
        assert metrics["fleet_route_least_privilege/mean"] == pytest.approx(
            expected_route_mean
        )
        assert metrics["fleet_tool_call_budget/mean"] == 1.0
        assert metrics["fleet_latency_budget/mean"] == 1.0

        client = MlflowClient()
        experiment = client.get_experiment_by_name(ROUTING_EVAL_EXPERIMENT)
        assert experiment is not None
        run = client.get_run(result.run_id)
        assert run.info.experiment_id == experiment.experiment_id
        # The genai run's artifacts stay in the pinned temp root, not the repo.
        assert (
            Path(experiment.artifact_location)
            .resolve()
            .is_relative_to((tmp_path / "artifacts").resolve())
        )


class TestCliMlflowEval:
    def test_the_cli_registers_the_dataset_and_runs_the_genai_scorers(
        self,
        store: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--mlflow-eval`` wires the real dataset and scorers into the CLI.

        The provider and the dspy scoring loop are stubbed: this test is about
        the MLflow wiring, not about spending LM steps on prompt formatting.
        """
        from evals.datasets import load_dataset

        tiny = [
            next(e for e in ROUTING_EXAMPLES if e.expected_route == route)
            for route in ROUTES
        ]
        monkeypatch.setattr("evals.run.ROUTING_EXAMPLES", tiny)
        monkeypatch.setattr("evals.datasets.ROUTING_EXAMPLES", tiny)
        monkeypatch.setattr("evals.run.validate_routing_dataset", lambda: [])
        monkeypatch.setattr("evals.run._resolve_lm", lambda: object())
        monkeypatch.setattr(
            "evals.run._score_routing",
            lambda lm: RoutingScore(mean=1.0, misses=[], mean_latency_s=0.1),
        )

        def predict(**inputs: Any) -> dict[str, Any]:
            return {"route": "workspace_shell", "tool_calls": 0, "latency_s": 0.1}

        monkeypatch.setattr("evals.run._mlflow_predict_fn", lambda lm: predict)

        exit_code = eval_run_main(["--suite", "routing", "--mlflow-eval"])

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "mlflow dataset: fleet-agent-routing-eval-v1" in out
        assert "mlflow genai metrics:" in out
        dataset = load_dataset()
        assert dataset is not None
        assert len(dataset.to_df()) == len(tiny)
        assert dataset.tags["fleet.dataset.digest"] == dataset_digest(routing_records())
