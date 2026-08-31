"""Operator-side MLflow observability (opt-in).

Two independent surfaces share this module:

* ``evals/mlflow_tracking.py`` logs offline optimization and scoring runs.
* ``configure_mlflow`` enables dspy tracing for live agent runs — strictly
  opt-in, because MLflow traces capture LLM prompts and completions *by
  design*. Traces live in the operator's MLflow store; they never reach the
  browser, and the feature stays off unless the operator turns it on.

The default store is a local SQLite backend at ``.artifacts/mlflow.db``
(gitignored alongside artifact storage); MLflow 3.x put the old
filesystem store in maintenance mode, so SQLite is the modern zero-infra
default. Point ``FLEET_AGENT_MLFLOW_TRACKING_URI`` — or the standard
``MLFLOW_TRACKING_URI`` — at a server to centralize.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.settings import Settings

logger = logging.getLogger(__name__)

TRACING_EXPERIMENT = "fleet-agent/agent-runs"


def default_tracking_uri() -> str:
    """Local SQLite store URI under the (gitignored) artifact root."""
    db = (Path(".artifacts") / "mlflow.db").resolve()
    return f"sqlite:///{db}"


def resolve_tracking_uri(configured: str | None = None) -> str:
    """Env override > mlflow's own env var > configured value > local default."""
    for env_name in ("FLEET_AGENT_MLFLOW_TRACKING_URI", "MLFLOW_TRACKING_URI"):
        value = os.environ.get(env_name)
        if value:
            return value
    return configured or default_tracking_uri()


def configure_mlflow(settings: Settings) -> bool:
    """Enable dspy tracing into MLflow when the operator opts in.

    Returns ``True`` when tracing was enabled. Must run once at application
    startup, before any predictor call. With the setting off (the default)
    this imports nothing and touches nothing.

    Privacy boundary: enabling this makes LLM prompts and completions
    observable in the operator's own MLflow store. That is a deliberate
    operator decision — the app never sends provider data to the browser.
    """
    if not settings.mlflow_tracing_enabled:
        return False
    import mlflow

    uri = resolve_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(TRACING_EXPERIMENT)
    # Trace predictor, ReAct, and tool-call spans from live runs. Compile-
    # time and eval-time tracing stay off here: optimization is logged
    # explicitly (params, metrics, artifacts) by the offline harness.
    mlflow.dspy.autolog(
        log_traces=True,
        log_traces_from_compile=False,
        log_traces_from_eval=False,
    )
    logger.info("MLflow dspy tracing enabled (store: %s)", uri)
    return True
