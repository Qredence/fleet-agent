"""MLflow tracking helpers: local SQLite store, params, metrics, artifacts.

Every test pins the store to a tmp SQLite URI, so nothing touches the
operator's real ``.artifacts/mlflow.db`` or any server.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.mlflow_observability import (
    TRACING_EXPERIMENT,
    configure_mlflow,
    resolve_tracking_uri,
)
from evals.mlflow_tracking import (
    OPTIMIZATION_EXPERIMENT,
    ROUTING_EVAL_EXPERIMENT,
    log_optimization_run,
    log_routing_score,
)


def _local_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    # SQLite backend: MLflow 3.x put the filesystem store in maintenance mode.
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setenv("FLEET_AGENT_MLFLOW_TRACKING_URI", uri)
    return uri


def _client() -> object:
    from mlflow.tracking import MlflowClient

    return MlflowClient()


class TestResolveTrackingUri:
    def test_env_then_settings_then_local_default(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FLEET_AGENT_MLFLOW_TRACKING_URI", "sqlite:///custom.db")
        assert resolve_tracking_uri() == "sqlite:///custom.db"
        monkeypatch.delenv("FLEET_AGENT_MLFLOW_TRACKING_URI")

        monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.example:5000")
        assert resolve_tracking_uri() == "http://mlflow.example:5000"
        monkeypatch.delenv("MLFLOW_TRACKING_URI")

        assert resolve_tracking_uri("sqlite:///configured.db") == (
            "sqlite:///configured.db"
        )
        default = resolve_tracking_uri()
        assert default.startswith("sqlite:///") and default.endswith("mlflow.db")


class TestLogOptimizationRun:
    def _log_kwargs(self, **overrides: object) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "outcome": "artifact-written",
            "budget": "light",
            "seed": 0,
            "split_seed": 17,
            "train_examples": 32,
            "val_examples": 13,
            "min_accuracy": 0.9,
            "baseline_mean": 0.95,
            "candidate_mean": 1.0,
            "baseline_latency_s": 3.0,
            "candidate_latency_s": 3.1,
            "dspy_version": "3.3.1",
            "artifact_dir": None,
        }
        kwargs.update(overrides)
        return kwargs

    def test_writes_run_with_params_metrics_and_candidate_artifacts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _local_store(monkeypatch, tmp_path)
        artifact_dir = tmp_path / "candidate"
        artifact_dir.mkdir()
        (artifact_dir / "state.json").write_text(
            '{"module_src": "x"}', encoding="utf-8"
        )
        (artifact_dir / "report.md").write_text("# report", encoding="utf-8")

        run_id = log_optimization_run(
            **self._log_kwargs(artifact_dir=artifact_dir)  # type: ignore[arg-type]
        )

        client = _client()
        experiment = client.get_experiment_by_name(OPTIMIZATION_EXPERIMENT)
        assert experiment is not None
        (run,) = client.search_runs([experiment.experiment_id])
        assert run.info.run_id == run_id
        assert run.data.params["budget"] == "light"
        assert run.data.params["train_examples"] == "32"
        assert run.data.params["min_accuracy"] == "0.9"
        assert run.data.metrics["baseline_mean"] == pytest.approx(0.95)
        assert run.data.metrics["candidate_mean"] == pytest.approx(1.0)
        assert run.data.metrics["gates_passed"] == pytest.approx(1.0)
        assert run.data.tags["fleet.outcome"] == "artifact-written"
        nested = [a.path for a in client.list_artifacts(run.info.run_id, "candidate")]
        assert "candidate/state.json" in nested
        assert "candidate/report.md" in nested

    def test_gates_failed_run_logs_without_artifacts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _local_store(monkeypatch, tmp_path)

        run_id = log_optimization_run(
            **self._log_kwargs(  # type: ignore[arg-type]
                outcome="gates-failed",
                baseline_mean=1.0,
                candidate_mean=0.8,
            )
        )

        client = _client()
        experiment = client.get_experiment_by_name(OPTIMIZATION_EXPERIMENT)
        assert experiment is not None
        (run,) = client.search_runs([experiment.experiment_id])
        assert run.info.run_id == run_id
        assert run.data.metrics["gates_passed"] == pytest.approx(0.0)
        assert run.data.tags["fleet.outcome"] == "gates-failed"
        assert client.list_artifacts(run.info.run_id) == []


class TestLogRoutingScore:
    def test_logs_score_with_miss_buckets(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _local_store(monkeypatch, tmp_path)
        misses = [
            ("a-request", "workspace_write", "direct", 0.0),
            ("b-request", "workspace_read", "workspace_shell", 0.35),
            ("c-request", "workspace_read", "workspace_shell", 0.35),
        ]

        run_id = log_routing_score(mean=0.8, misses=misses, total=45, min_accuracy=0.9)

        client = _client()
        experiment = client.get_experiment_by_name(ROUTING_EVAL_EXPERIMENT)
        assert experiment is not None
        (run,) = client.search_runs([experiment.experiment_id])
        assert run.info.run_id == run_id
        assert run.data.metrics["mean_score"] == pytest.approx(0.8)
        assert run.data.metrics["misses"] == pytest.approx(3)
        assert run.data.metrics["under_selected"] == pytest.approx(1)
        assert run.data.metrics["over_selected"] == pytest.approx(2)
        assert run.data.metrics["gate_passed"] == pytest.approx(0.0)
        artifacts = [a.path for a in client.list_artifacts(run.info.run_id)]
        assert "misses.json" in artifacts


class TestConfigureMlflow:
    def _settings(self, enabled: bool) -> SimpleNamespace:
        return SimpleNamespace(mlflow_tracing_enabled=enabled, mlflow_tracking_uri=None)

    def test_disabled_is_a_noop(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "mlflow.dspy.autolog", lambda **kwargs: calls.append(kwargs)
        )

        enabled = configure_mlflow(self._settings(False))  # type: ignore[arg-type]

        assert enabled is False
        assert calls == []

    def test_enabled_sets_store_and_traces(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        uri = _local_store(monkeypatch, tmp_path)
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "mlflow.dspy.autolog", lambda **kwargs: calls.append(kwargs)
        )

        enabled = configure_mlflow(self._settings(True))  # type: ignore[arg-type]

        assert enabled is True
        assert calls and calls[0]["log_traces"] is True
        import mlflow

        assert mlflow.get_tracking_uri() == uri
        experiment = _client().get_experiment_by_name(TRACING_EXPERIMENT)
        assert experiment is not None
