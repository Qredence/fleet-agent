"""Versioned MLflow dataset for the least-privilege routing eval set.

mlflow 3.15.2 keeps evaluation datasets as records on a tracking store, but its
dataset *versioning* is Databricks-only: against a local store
``EvaluationDataset.version`` stays None and ``list_versions()`` /
``get_dataset(version=...)`` raise NotImplementedError (verified 2026-09-17).
The version therefore lives in the dataset *name*
(``fleet-agent-routing-eval-v1``) plus ``fleet.dataset.*`` tags carrying the
version and a content digest, so ``load_dataset(version)`` is a versioned
lookup and a stale copy is detectable. The examples themselves are never
duplicated here: they come from ``evals.agent_tool_routing.ROUTING_EXAMPLES``,
the same set the runner, the optimizer, and the GEPA metric score.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.mlflow_observability import connect, ensure_experiment
from evals.agent_tool_routing import ROUTING_EXAMPLES
from evals.mlflow_tracking import ROUTING_EVAL_EXPERIMENT

logger = logging.getLogger(__name__)

ROUTING_DATASET_NAME = "fleet-agent-routing-eval"
DATASET_VERSIONS: tuple[int, ...] = (1,)
DEFAULT_DATASET_VERSION = 1
SUITE_TAG = "fleet.suite"
VERSION_TAG = "fleet.dataset.version"
DIGEST_TAG = "fleet.dataset.digest"


def dataset_name(version: int = DEFAULT_DATASET_VERSION) -> str:
    """Versioned dataset name: the version is part of the lookup key."""
    if version not in DATASET_VERSIONS:
        raise ValueError(
            f"unknown routing dataset version {version!r}; known: {DATASET_VERSIONS}"
        )
    return f"{ROUTING_DATASET_NAME}-v{version}"


def routing_records(version: int = DEFAULT_DATASET_VERSION) -> list[dict[str, Any]]:
    """The routing examples as MLflow dataset records.

    ``inputs`` and ``expectations`` are the columns ``mlflow.genai.evaluate``
    feeds a scorer; ``expected_route`` keeps the field name the dspy examples
    and the GEPA metric already use.
    """
    dataset_name(version)  # reject an unknown version before any store call
    return [
        {
            "inputs": {"user_request": str(example.user_request)},
            "expectations": {"expected_route": str(example.expected_route)},
        }
        for example in ROUTING_EXAMPLES
    ]


def dataset_digest(records: Sequence[Mapping[str, Any]]) -> str:
    """Stable content fingerprint, so a changed dataset is detectable."""
    canonical = json.dumps(list(records), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def load_dataset(version: int = DEFAULT_DATASET_VERSION) -> Any | None:
    """The stored dataset for ``version``, or None when it was never built."""
    from mlflow.exceptions import MlflowException
    from mlflow.genai import datasets as mlflow_datasets

    connect()
    try:
        return mlflow_datasets.get_dataset(name=dataset_name(version))
    except MlflowException:
        return None


def build_dataset(
    version: int = DEFAULT_DATASET_VERSION, *, experiment_id: str | None = None
) -> Any:
    """Create or reuse the stored dataset for ``version`` and return it.

    Idempotent by digest: ``merge_records`` APPENDS, so a rebuild that did not
    check the stored digest would silently duplicate every example. A stored
    dataset with a matching digest and record count is returned untouched; any
    mismatch replaces it.

    ``mlflow.genai.datasets`` is imported lazily so the validate-only CLI path
    never loads the genai stack.
    """
    from mlflow.genai import datasets as mlflow_datasets

    connect()
    records = routing_records(version)
    digest = dataset_digest(records)
    name = dataset_name(version)
    stored = load_dataset(version)
    if stored is not None:
        if _is_current(stored, digest, len(records)):
            return stored
        mlflow_datasets.delete_dataset(dataset_id=stored.dataset_id)
    created = mlflow_datasets.create_dataset(
        name=name,
        experiment_id=experiment_id or ensure_experiment(ROUTING_EVAL_EXPERIMENT),
        tags={SUITE_TAG: "routing", VERSION_TAG: str(version), DIGEST_TAG: digest},
    )
    created.merge_records(records)
    logger.info("built MLflow dataset %s (%s records)", name, len(records))
    return created


def _is_current(stored: Any, digest: str, record_count: int) -> bool:
    """True when the stored dataset already holds exactly this content."""
    return stored.tags.get(DIGEST_TAG) == digest and len(stored.to_df()) == record_count


def dataset_reference(dataset: Any) -> dict[str, Any]:
    """The ``fleet.dataset.*`` run tags that identify ``dataset``."""
    tags = getattr(dataset, "tags", {}) or {}
    raw_version = tags.get(VERSION_TAG)
    return {
        "dataset_name": getattr(dataset, "name", None),
        "dataset_version": int(raw_version) if raw_version else None,
        "dataset_digest": tags.get(DIGEST_TAG),
    }
