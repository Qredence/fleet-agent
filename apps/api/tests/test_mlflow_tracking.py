"""MLflow tracking helpers: local SQLite store, params, metrics, artifacts.

Every test pins the tracking store to a tmp SQLite URI *and* pins the artifact
root to a tmp directory, so nothing touches the operator's real
``.artifacts/mlflow.db``, the repo's ``apps/api/mlruns/`` tree, or any server.
The leak these tests guard against is real: MLflow resolves a relative
``mlruns/`` directory for an experiment created without an explicit artifact
location, and that path is derived from the process's working directory —
which is how 56 run directories ended up inside the repository.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import mlflow_observability
from app.services.mlflow_observability import (
    ARTIFACT_ROOT_ENV,
    TRACING_EXPERIMENT,
    configure_mlflow,
    default_artifact_root,
    resolve_artifact_root,
    resolve_tracking_uri,
)
from evals.mlflow_tracking import (
    OPTIMIZATION_EXPERIMENT,
    ROUTING_EVAL_EXPERIMENT,
    log_optimization_run,
    log_routing_score,
)

_SECRET = "sk-abcdefghijklmnopqrstuvwx"


@pytest.fixture(autouse=True)
def _restore_mlflow_env() -> Iterator[None]:
    """Restore the MLFLOW_* environment block after every test.

    ``mlflow.set_tracking_uri`` and ``mlflow.set_experiment`` write
    ``MLFLOW_TRACKING_URI`` and ``MLFLOW_EXPERIMENT_ID`` into the environment
    "so that subprocess can inherit it" (verified in mlflow 3.15.2). The shared
    conftest purges ``FLEET_AGENT_*`` and ``MODAL_*`` but not ``MLFLOW_*``, and
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


# The repository tree the tests must not write into. ``apps/api/mlruns`` is the
# directory the CWD-derived artifact location used to create.
_REPO_ROOT = Path(mlflow_observability.__file__).resolve().parents[4]
_REPO_MLRUNS = _REPO_ROOT / "apps" / "api" / "mlruns"


def _local_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    # SQLite backend: MLflow 3.x put the filesystem store in maintenance mode.
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setenv("FLEET_AGENT_MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(tmp_path / "artifacts"))
    return uri


def _client() -> object:
    from mlflow.tracking import MlflowClient

    return MlflowClient()


def _repo_mlruns_entries() -> set[str]:
    if not _REPO_MLRUNS.exists():
        return set()
    return {str(path.relative_to(_REPO_MLRUNS)) for path in _REPO_MLRUNS.rglob("*")}


def _under(location: str, root: Path) -> bool:
    return Path(location).resolve().is_relative_to(root.resolve())


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


class TestArtifactRoot:
    """Artifact locations must come from the store, never from the CWD."""

    def test_local_store_puts_artifacts_beside_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv(ARTIFACT_ROOT_ENV, raising=False)

        root = resolve_artifact_root(f"sqlite:///{tmp_path}/mlflow.db")

        assert root == tmp_path.resolve() / "mlruns"

    def test_env_override_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(tmp_path / "elsewhere"))

        assert (
            resolve_artifact_root(f"sqlite:///{tmp_path}/mlflow.db")
            == (tmp_path / "elsewhere").resolve()
        )

    def test_remote_store_keeps_the_server_in_charge(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv(ARTIFACT_ROOT_ENV, raising=False)

        assert resolve_artifact_root("http://mlflow.example:5000") == (
            default_artifact_root()
        )


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
        assert run.data.metrics["baseline_failures"] == pytest.approx(0.0)
        assert run.data.metrics["candidate_failures"] == pytest.approx(0.0)
        assert run.data.metrics["gates_passed"] == pytest.approx(1.0)
        assert run.data.tags["fleet.outcome"] == "artifact-written"
        assert run.data.tags["fleet.kind"] == "router-optimization"
        assert run.data.tags["fleet.suite"] == "routing"
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

        run_id = log_routing_score(
            mean=0.8, misses=misses, total=45, min_accuracy=0.9, failures=2
        )

        client = _client()
        experiment = client.get_experiment_by_name(ROUTING_EVAL_EXPERIMENT)
        assert experiment is not None
        (run,) = client.search_runs([experiment.experiment_id])
        assert run.info.run_id == run_id
        assert run.data.metrics["mean_score"] == pytest.approx(0.8)
        assert run.data.metrics["misses"] == pytest.approx(3)
        assert run.data.metrics["under_selected"] == pytest.approx(1)
        assert run.data.metrics["over_selected"] == pytest.approx(2)
        # Raised examples are scored 0 by dspy.Evaluate, so the count is what
        # separates a provider error from a routing miss in the history.
        assert run.data.metrics["failures"] == pytest.approx(2)
        assert run.data.metrics["gate_passed"] == pytest.approx(0.0)
        artifacts = [a.path for a in client.list_artifacts(run.info.run_id)]
        assert "misses.json" in artifacts

    def test_tags_the_scored_dataset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """A score has to name the eval set it measured (name, version, digest)."""
        _local_store(monkeypatch, tmp_path)

        log_routing_score(
            mean=1.0,
            misses=[],
            total=45,
            min_accuracy=0.9,
            dataset_name="fleet-agent-routing-eval-v1",
            dataset_version=1,
            dataset_digest="b1df33e0fc32a8da",
        )

        client = _client()
        experiment = client.get_experiment_by_name(ROUTING_EVAL_EXPERIMENT)
        assert experiment is not None
        (run,) = client.search_runs([experiment.experiment_id])
        assert run.data.tags["fleet.kind"] == "routing-eval"
        assert run.data.tags["fleet.gate_passed"] == "True"
        assert run.data.tags["fleet.dataset.name"] == "fleet-agent-routing-eval-v1"
        assert run.data.tags["fleet.dataset.version"] == "1"
        assert run.data.tags["fleet.dataset.digest"] == "b1df33e0fc32a8da"


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

    def test_experiment_artifacts_land_under_the_pinned_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """The tracing experiment must name its artifact directory explicitly."""
        _local_store(monkeypatch, tmp_path)
        monkeypatch.setattr("mlflow.dspy.autolog", lambda **kwargs: None)

        assert configure_mlflow(self._settings(True)) is True  # type: ignore[arg-type]

        experiment = _client().get_experiment_by_name(TRACING_EXPERIMENT)
        assert experiment is not None
        assert _under(experiment.artifact_location, tmp_path / "artifacts")
        assert not _under(experiment.artifact_location, _REPO_ROOT)

    def test_unusable_store_degrades_with_a_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """A bad tracking URI must not stop the app from booting."""
        monkeypatch.setenv(
            "FLEET_AGENT_MLFLOW_TRACKING_URI", "sqlite:////dev/null/nope/mlflow.db"
        )

        with caplog.at_level("WARNING"):
            enabled = configure_mlflow(self._settings(True))  # type: ignore[arg-type]

        assert enabled is False
        assert "could not be enabled" in caplog.text

    def test_missing_mlflow_degrades_with_a_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        import sys

        _local_store(monkeypatch, tmp_path)
        monkeypatch.setitem(sys.modules, "mlflow", None)

        with caplog.at_level("WARNING"):
            enabled = configure_mlflow(self._settings(True))  # type: ignore[arg-type]

        assert enabled is False
        assert "could not be enabled" in caplog.text


@pytest.fixture()
def tracing_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[str]:
    """Tracing enabled into a temp store, with the redacting span processor.

    Tracing is global (autolog mutates ``dspy.settings.callbacks`` and
    ``mlflow.tracing.configure`` mutates process-wide tracing config), so the
    teardown restores both.
    """
    import dspy
    import mlflow

    uri = _local_store(monkeypatch, tmp_path)
    dspy.settings.configure(callbacks=[])
    assert (
        configure_mlflow(  # type: ignore[arg-type]
            SimpleNamespace(mlflow_tracing_enabled=True, mlflow_tracking_uri=None)
        )
        is True
    )
    yield uri
    mlflow.dspy.autolog(disable=True)
    mlflow.tracing.configure(span_processors=[])
    dspy.settings.configure(callbacks=[])


def _last_trace_blob() -> str:
    """Every span of the newest trace in the active experiment, as JSON."""
    import mlflow

    mlflow.flush_trace_async_logging()
    experiment = mlflow.get_experiment_by_name(TRACING_EXPERIMENT)
    assert experiment is not None
    traces = mlflow.search_traces(locations=[experiment.experiment_id])
    assert len(traces) >= 1
    trace = traces.iloc[0] if hasattr(traces, "iloc") else traces[0]
    if hasattr(trace, "__getitem__") and "spans" in trace:
        spans = trace["spans"]
    else:
        spans = trace.data.spans
    return json.dumps([str(span) for span in spans], default=str)


class TestTracingRedaction:
    def test_secrets_are_scrubbed_before_the_span_is_stored(
        self, tracing_store: str
    ) -> None:
        """A key in a prompt must reach the store masked, like the browser text."""
        import dspy

        class _Answer(dspy.Signature):
            """Answer the request."""

            user_request: str = dspy.InputField()
            answer: str = dspy.OutputField()

        with dspy.context(lm=dspy.utils.DummyLM([{"answer": f"using {_SECRET}"}])):
            dspy.Predict(_Answer)(user_request=f"my api_key = {_SECRET} for you")

        blob = _last_trace_blob()

        assert _SECRET not in blob
        assert "[redacted]" in blob

    def test_a_run_writes_nothing_into_the_repo_mlruns_tree(
        self, tracing_store: str
    ) -> None:
        """The store and the artifact root are both pinned to the temp dir."""
        import dspy

        before = _repo_mlruns_entries()

        class _Answer(dspy.Signature):
            """Answer the request."""

            user_request: str = dspy.InputField()
            answer: str = dspy.OutputField()

        with dspy.context(lm=dspy.utils.DummyLM([{"answer": "ok"}])):
            dspy.Predict(_Answer)(user_request="write nothing into the repo")
        _last_trace_blob()

        assert _repo_mlruns_entries() == before
