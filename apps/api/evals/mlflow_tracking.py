"""MLflow run history for offline evaluation and self-improvement.

Every optimization attempt — gates passed or failed — and every scored
routing-eval run is logged with params, metrics, and (on pass) the full
candidate artifact, so the router's evolution is reviewable in one place:
`mlflow ui` over the default local store, or any MLflow server the operator
points ``FLEET_AGENT_MLFLOW_TRACKING_URI`` at.

Like the rest of the offline harness, these helpers never talk to the
database, the live engine, or any remote system the operator has not
configured.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.mlflow_observability import resolve_tracking_uri

logger = logging.getLogger(__name__)

OPTIMIZATION_EXPERIMENT = "fleet-agent/router-optimization"
ROUTING_EVAL_EXPERIMENT = "fleet-agent/routing-eval"


def _mlflow() -> Any:
    """Connect MLflow to the resolved store and return the module."""
    import mlflow

    mlflow.set_tracking_uri(resolve_tracking_uri())
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
    artifact_dir: Path | None = None,
) -> str | None:
    """Log one optimization attempt (pass or fail) to MLflow.

    Returns the run id, or ``None`` when MLflow could not be reached — the
    harness treats logging as best-effort and never fails an optimization
    because of it.
    """
    try:
        mlflow = _mlflow()
        mlflow.set_experiment(OPTIMIZATION_EXPERIMENT)
        with mlflow.start_run(run_name=f"flex-router-{budget}-{outcome}") as run:
            mlflow.set_tags(
                {
                    "fleet.outcome": outcome,
                    "fleet.dspy_version": dspy_version,
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
) -> str | None:
    """Log one scored routing-eval run (misses land as a JSON artifact)."""
    try:
        mlflow = _mlflow()
        mlflow.set_experiment(ROUTING_EVAL_EXPERIMENT)
        under = sum(1 for miss in misses if miss[3] == 0.0)
        over = len(misses) - under
        with mlflow.start_run(run_name="routing-score") as run:
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
                    "gate_passed": float(mean >= min_accuracy),
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
