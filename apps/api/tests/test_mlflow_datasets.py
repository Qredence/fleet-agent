"""The routing eval set as a versioned MLflow dataset.

Hermetic: the tracking store is a tmp SQLite file and the artifact root is a tmp
directory, so a build can neither touch the operator's store nor write into the
repository tree.

These tests also pin the mlflow 3.16.0 limitation the design works around —
dataset *versions* are Databricks-only, so on a local store ``version`` stays
None and ``list_versions()`` raises. If a future mlflow implements versions
locally, ``test_mlflow_has_no_local_dataset_versions`` fails and the name-plus-
digest scheme here can be simplified back to the native one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.services import mlflow_observability
from app.services.mlflow_observability import ARTIFACT_ROOT_ENV
from evals.agent_tool_routing import ROUTING_EXAMPLES
from evals.datasets import (
    DATASET_VERSIONS,
    DIGEST_TAG,
    ROUTING_DATASET_NAME,
    VERSION_TAG,
    build_dataset,
    dataset_digest,
    dataset_name,
    dataset_reference,
    load_dataset,
    routing_records,
)
from evals.mlflow_tracking import ROUTING_EVAL_EXPERIMENT

_REPO_MLRUNS = (
    Path(mlflow_observability.__file__).resolve().parents[4] / "apps" / "api" / "mlruns"
)


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


def _repo_mlruns() -> set[str]:
    if not _REPO_MLRUNS.exists():
        return set()
    return {str(path.relative_to(_REPO_MLRUNS)) for path in _REPO_MLRUNS.rglob("*")}


def test_records_mirror_the_eval_set_without_copying_it(store: str) -> None:
    """One record per example, taken from the single source of truth."""
    records = routing_records()

    assert len(records) == len(ROUTING_EXAMPLES)
    assert [record["inputs"]["user_request"] for record in records] == [
        str(example.user_request) for example in ROUTING_EXAMPLES
    ]
    assert [record["expectations"]["expected_route"] for record in records] == [
        str(example.expected_route) for example in ROUTING_EXAMPLES
    ]


def test_digest_follows_the_content() -> None:
    records = routing_records()

    assert dataset_digest(records) == dataset_digest(routing_records())
    changed = [dict(record) for record in records]
    changed[0] = {
        "inputs": {"user_request": "a different request"},
        "expectations": {"expected_route": "direct"},
    }
    assert dataset_digest(changed) != dataset_digest(records)


def test_build_registers_a_versioned_dataset_with_its_tags(
    store: str, tmp_path: Path
) -> None:
    dataset = build_dataset()

    assert dataset.name == f"{ROUTING_DATASET_NAME}-v1"
    assert dataset.tags[VERSION_TAG] == "1"
    assert dataset.tags[DIGEST_TAG] == dataset_digest(routing_records())
    assert len(dataset.to_df()) == len(ROUTING_EXAMPLES)
    assert load_dataset().dataset_id == dataset.dataset_id

    import mlflow

    experiment = mlflow.get_experiment_by_name(ROUTING_EVAL_EXPERIMENT)
    assert experiment is not None
    assert (
        Path(experiment.artifact_location)
        .resolve()
        .is_relative_to((tmp_path / "artifacts").resolve())
    )


def test_build_writes_nothing_into_the_repo_mlruns_tree(store: str) -> None:
    before = _repo_mlruns()

    build_dataset()

    assert _repo_mlruns() == before


def test_build_is_idempotent(store: str) -> None:
    """``merge_records`` appends, so a rebuild must not duplicate the eval set."""
    first = build_dataset()
    second = build_dataset()

    assert second.dataset_id == first.dataset_id
    assert len(second.to_df()) == len(ROUTING_EXAMPLES)


def test_build_replaces_a_dataset_whose_digest_moved(store: str) -> None:
    from mlflow.genai.datasets import set_dataset_tags

    dataset = build_dataset()
    set_dataset_tags(dataset_id=dataset.dataset_id, tags={DIGEST_TAG: "stale-digest"})

    rebuilt = build_dataset()

    assert rebuilt.tags[DIGEST_TAG] == dataset_digest(routing_records())
    assert len(rebuilt.to_df()) == len(ROUTING_EXAMPLES)


def test_loading_before_a_build_returns_none(store: str) -> None:
    assert load_dataset() is None


def test_versions_are_explicit() -> None:
    assert DATASET_VERSIONS == (1,)
    assert dataset_name(1) == f"{ROUTING_DATASET_NAME}-v1"
    with pytest.raises(ValueError, match="unknown routing dataset version"):
        dataset_name(2)


def test_dataset_reference_feeds_the_run_tags(store: str) -> None:
    reference = dataset_reference(build_dataset())

    assert set(reference) == {"dataset_name", "dataset_version", "dataset_digest"}
    assert reference["dataset_name"] == f"{ROUTING_DATASET_NAME}-v1"
    assert reference["dataset_version"] == 1
    assert reference["dataset_digest"] == dataset_digest(routing_records())
    # These keys are the keyword arguments log_routing_score tags the run with.
    from evals.mlflow_tracking import log_routing_score

    assert set(reference).issubset(log_routing_score.__code__.co_varnames)


def test_mlflow_has_no_local_dataset_versions(store: str) -> None:
    """Pin the limitation the name-plus-digest scheme exists to work around."""
    dataset = build_dataset()

    from mlflow.genai import datasets as mlflow_datasets

    assert dataset.version is None
    with pytest.raises(NotImplementedError):
        dataset.list_versions()
    # ``load_dataset`` therefore resolves by versioned *name* instead.
    with pytest.raises(NotImplementedError):
        mlflow_datasets.get_dataset(name=dataset.name, version=1)
