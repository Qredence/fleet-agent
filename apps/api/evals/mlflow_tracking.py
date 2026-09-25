"""MLflow run history for offline evaluation and self-improvement.

Every optimization attempt — gates passed or failed — and every scored
routing-eval run is logged with params, metrics, artifacts, and ``fleet.*``
tags, so the router's evolution is filterable in one place: ``mlflow ui`` over
the default local store, or any MLflow server the operator points
``FLEET_AGENT_MLFLOW_TRACKING_URI`` at. The tags answer the questions the
metrics alone cannot: which suite and dataset version a score belongs to, which
kind of run it was, and whether the gate passed.

Like the rest of the offline harness, these helpers never talk to the
database, the live engine, or any remote system the operator has not
configured.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import dspy

from app.services.mlflow_observability import connect, ensure_experiment

logger = logging.getLogger(__name__)

OPTIMIZATION_EXPERIMENT = "fleet-agent/router-optimization"
ROUTING_EVAL_EXPERIMENT = "fleet-agent/routing-eval"

KIND_OPTIMIZATION = "router-optimization"
KIND_ROUTING_EVAL = "routing-eval"
SUITE_TAG = "fleet.suite"


def use_experiment(name: str) -> Any:
    """Connect to the resolved store and select ``name`` with an explicit root.

    ``mlflow.set_experiment(name)`` would create a missing experiment with an
    artifact location resolved from the current directory; ``ensure_experiment``
    creates it with an explicit one instead.
    """
    mlflow = connect()
    mlflow.set_experiment(experiment_id=ensure_experiment(name))
    return mlflow


def log_optimization_run(
    *,
    outcome: str,
    budget: str,
    seed: int,
    split_seed: int,
    train_examples: int,
    val_examples: int,
    min_accuracy: float,
    baseline_mean: float,
    candidate_mean: float,
    baseline_latency_s: float,
    candidate_latency_s: float,
    dspy_version: str,
    baseline_failures: int = 0,
    candidate_failures: int = 0,
    artifact_dir: Path | None = None,
) -> str | None:
    """Log one optimization attempt (pass or fail) to MLflow.

    ``baseline_failures`` / ``candidate_failures`` count held-out examples
    whose router call raised: ``dspy.Evaluate`` scores those with its
    ``failure_score`` (0.0 here) and continues, so a failing provider lowers a
    mean without appearing anywhere else in the run.

    Returns the run id, or ``None`` when MLflow could not be reached — the
    harness treats logging as best-effort and never fails an optimization
    because of it.
    """
    try:
        mlflow = use_experiment(OPTIMIZATION_EXPERIMENT)
        with mlflow.start_run(run_name=f"router-{budget}-{outcome}") as run:
            mlflow.set_tags(
                {
                    "fleet.kind": KIND_OPTIMIZATION,
                    SUITE_TAG: "routing",
                    "fleet.outcome": outcome,
                    "fleet.dspy_version": dspy_version,
                    "fleet.gates_passed": str(outcome == "artifact-written"),
                    "fleet.budget": budget,
                }
            )
            mlflow.log_params(
                {
                    "budget": budget,
                    "seed": seed,
                    "split_seed": split_seed,
                    "train_examples": train_examples,
                    "val_examples": val_examples,
                    "min_accuracy": min_accuracy,
                }
            )
            mlflow.log_metrics(
                {
                    "baseline_mean": baseline_mean,
                    "candidate_mean": candidate_mean,
                    "baseline_mean_latency_s": baseline_latency_s,
                    "candidate_mean_latency_s": candidate_latency_s,
                    "baseline_failures": float(baseline_failures),
                    "candidate_failures": float(candidate_failures),
                    "gates_passed": 1.0 if outcome == "artifact-written" else 0.0,
                }
            )
            if artifact_dir is not None and artifact_dir.is_dir():
                mlflow.log_artifacts(str(artifact_dir), artifact_path="candidate")
            run_id = run.info.run_id
    except Exception:  # noqa: BLE001 — observability must never break the run
        logger.warning("MLflow optimization logging failed; continuing", exc_info=True)
        return None
    logger.info("logged optimization attempt %s to MLflow (%s)", run_id, outcome)
    return run_id


def log_routing_score(
    *,
    mean: float,
    misses: list[tuple[str, str, str, float]],
    total: int,
    min_accuracy: float,
    failures: int = 0,
    dataset_name: str | None = None,
    dataset_version: int | None = None,
    dataset_digest: str | None = None,
) -> str | None:
    """Log one scored routing-eval run (misses land as a JSON artifact).

    ``failures`` counts examples whose router call raised: ``dspy.Evaluate``
    scores them with its ``failure_score`` (0.0) and continues, so without the
    count a provider error is indistinguishable from a routing miss.

    The three ``dataset_*`` arguments tag the run with the exact eval set it
    scored (``evals.datasets``); pass them so a score can be traced back to a
    dataset version and digest.
    """
    try:
        mlflow = use_experiment(ROUTING_EVAL_EXPERIMENT)
        gate_passed = mean >= min_accuracy
        tags = {
            "fleet.kind": KIND_ROUTING_EVAL,
            SUITE_TAG: "routing",
            "fleet.dspy_version": dspy.__version__,
            "fleet.gate_passed": str(gate_passed),
            "fleet.min_accuracy": str(min_accuracy),
        }
        if dataset_name:
            tags["fleet.dataset.name"] = dataset_name
        if dataset_version is not None:
            tags["fleet.dataset.version"] = str(dataset_version)
        if dataset_digest:
            tags["fleet.dataset.digest"] = dataset_digest
        under = sum(1 for miss in misses if miss[3] == 0.0)
        over = len(misses) - under
        with mlflow.start_run(run_name="routing-score") as run:
            mlflow.set_tags(tags)
            mlflow.log_params(
                {
                    "examples": total,
                    "min_accuracy": min_accuracy,
                }
            )
            mlflow.log_metrics(
                {
                    "mean_score": mean,
                    "misses": len(misses),
                    "under_selected": under,
                    "over_selected": over,
                    "failures": float(failures),
                    "gate_passed": float(gate_passed),
                }
            )
            if misses:
                # Requests come from the operator's own eval set; the store
                # is operator-side observability.
                mlflow.log_dict(
                    {
                        "misses": [
                            {
                                "request": request,
                                "expected": expected,
                                "actual": actual,
                                "score": score,
                            }
                            for request, expected, actual, score in misses
                        ]
                    },
                    "misses.json",
                )
            run_id = run.info.run_id
    except Exception:  # noqa: BLE001 — observability must never break the run
        logger.warning("MLflow routing-score logging failed; continuing", exc_info=True)
        return None
    logger.info("logged routing eval %s to MLflow", run_id)
    return run_id
