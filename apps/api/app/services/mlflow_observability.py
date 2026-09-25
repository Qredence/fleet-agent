"""Operator-side MLflow observability (opt-in).

Three independent surfaces share this module:

* ``evals/mlflow_tracking.py`` logs offline optimization and scoring runs.
* ``evals/datasets.py`` stores the versioned routing eval set.
* ``configure_mlflow`` enables dspy tracing for live agent runs — strictly
  opt-in, because MLflow traces capture LLM prompts and completions *by
  design*. Traces live in the operator's MLflow store; they never reach the
  browser, and the feature stays off unless the operator turns it on.

The default store is a local SQLite backend at ``.artifacts/mlflow.db``
(gitignored alongside artifact storage); MLflow 3.x put the old filesystem
store in maintenance mode, so SQLite is the modern zero-infra default. Point
``FLEET_AGENT_MLFLOW_TRACKING_URI`` — or the standard ``MLFLOW_TRACKING_URI``
— at a server to centralize.

Artifact locations are never CWD-derived. MLflow resolves a *relative*
``mlruns/`` directory when an experiment is created without an explicit
``artifact_location``, which is how artifact directories used to leak into
``apps/api/mlruns/`` (56 run directories from experiments created in the repo
root). Every experiment this module creates names its artifact directory
explicitly — ``<store dir>/mlruns/<experiment>`` beside the SQLite store — so
a throwaway store in a temp dir keeps its artifacts in that temp dir too.
``FLEET_AGENT_MLFLOW_ARTIFACT_ROOT`` overrides the root.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from app.services.content_safety import scrub_public_text
from app.settings import Settings

logger = logging.getLogger(__name__)

TRACING_EXPERIMENT = "fleet-agent/agent-runs"
ARTIFACT_ROOT_ENV = "FLEET_AGENT_MLFLOW_ARTIFACT_ROOT"

# Tracking URI schemes this process can write files for. An empty scheme means
# a bare path (MLflow's own default store is the relative directory "mlruns").
_LOCAL_SCHEMES = frozenset({"", "file", "sqlite"})


def default_tracking_uri() -> str:
    """Local SQLite store URI under the (gitignored) artifact root."""
    db = (_repo_root() / ".artifacts" / "mlflow.db").resolve()
    return f"sqlite:///{db}"


def resolve_tracking_uri(configured: str | None = None) -> str:
    """Env override > mlflow's own env var > configured value > local default."""
    for env_name in ("FLEET_AGENT_MLFLOW_TRACKING_URI", "MLFLOW_TRACKING_URI"):
        value = os.environ.get(env_name)
        if value:
            return value
    return configured or default_tracking_uri()


def is_local_store(tracking_uri: str) -> bool:
    """True when ``tracking_uri`` addresses a store this process owns."""
    scheme = tracking_uri.split("://", 1)[0].lower() if "://" in tracking_uri else ""
    return scheme in _LOCAL_SCHEMES


def _local_store_path(tracking_uri: str) -> Path | None:
    """Absolute filesystem path behind a local tracking URI, if there is one.

    MLflow's SQLite form is ``sqlite:///`` plus an absolute path, so the real
    path keeps a leading ``//`` once the scheme is stripped; resolving it is
    what turns that back into a single-rooted absolute path.
    """
    if not is_local_store(tracking_uri):
        return None
    rest = tracking_uri
    if "://" in rest:
        rest = rest.split("://", 1)[1]
    elif rest.startswith(("sqlite:", "file:")):
        rest = rest.split(":", 1)[1]
    if not rest or rest.startswith(":memory:"):
        return None
    return Path(unquote(rest)).expanduser().resolve()


def _repo_root() -> Path:
    """Nearest ancestor of this file holding the repository's ``.git`` entry."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return Path.cwd()


def default_artifact_root() -> Path:
    """Fallback root when the store's own directory cannot host artifacts."""
    return _repo_root() / ".artifacts" / "mlruns"


def resolve_artifact_root(
    tracking_uri: str | None = None, configured: str | None = None
) -> Path:
    """Artifact root: env override > configured value > beside the local store."""
    value = os.environ.get(ARTIFACT_ROOT_ENV) or configured
    if value:
        return Path(value).expanduser().resolve()
    local_store = _local_store_path(tracking_uri) if tracking_uri else None
    if local_store is not None:
        return local_store.parent / "mlruns"
    return default_artifact_root()


def _local_artifact_path(location: str) -> bool:
    """True when an artifact location is a plain local path, not a remote URI."""
    return "://" not in location or location.startswith("file://")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _warn_legacy_artifact_location(
    name: str, location: str | None, tracking_uri: str
) -> None:
    """Warn when an existing experiment keeps a CWD-derived artifact location.

    mlflow 3.15.2 has no API to relocate an existing experiment (its client
    exposes no ``update_experiment``), so a store written before this module
    set explicit roots keeps those directories. Only new experiments are
    correct; the operator decides whether the old ones are worth migrating.
    """
    root = resolve_artifact_root(tracking_uri)
    if not location or not _local_artifact_path(location):
        return
    parsed_path = (
        unquote(urlsplit(location).path)
        if location.startswith("file://")
        else unquote(location)
    )
    if _is_within(Path(parsed_path), root):
        return
    logger.warning(
        "MLflow experiment %r keeps its existing artifact location %s, outside %s. "
        "MLflow cannot relocate an existing experiment; delete or rename it if "
        "writes there must stop.",
        name,
        location,
        root,
    )


def ensure_experiment(name: str, artifact_root: str | None = None) -> str:
    """Return ``name``'s experiment id, creating it with an explicit root.

    The caller must have set the tracking URI already (``connect`` and
    ``configure_mlflow`` both do). This project never calls
    ``mlflow.set_experiment`` with a bare name: that path creates the
    experiment with an artifact location resolved from the current directory.
    """
    import mlflow

    tracking_uri = str(mlflow.get_tracking_uri())
    existing = mlflow.get_experiment_by_name(name)
    if existing is not None:
        if getattr(existing, "lifecycle_stage", None) == "deleted":
            mlflow.MlflowClient().restore_experiment(existing.experiment_id)
        _warn_legacy_artifact_location(name, existing.artifact_location, tracking_uri)
        return str(existing.experiment_id)
    location = None
    if is_local_store(tracking_uri):
        root = resolve_artifact_root(tracking_uri, artifact_root)
        location = str(root / name.replace("/", "-"))
    try:
        return str(mlflow.create_experiment(name, artifact_location=location))
    except Exception:  # noqa: BLE001 — treat a lost creation race as success
        raced = mlflow.get_experiment_by_name(name)
        if raced is None:
            raise
        return str(raced.experiment_id)


def connect(configured: str | None = None) -> Any:
    """Point MLflow at the resolved store and return the module.

    Every tracking call in this project goes through here, so a caller cannot
    log into a store it did not resolve.
    """
    import mlflow

    mlflow.set_tracking_uri(resolve_tracking_uri(configured))
    return mlflow


_SENSITIVE_KEY_RE = re.compile(
    r"\b(?:api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token|password|passwd|pwd)\b",
    re.IGNORECASE,
)


def _scrub_json(value: Any) -> Any:
    """Mask secrets in a JSON-shaped span payload, keeping its structure intact."""
    if isinstance(value, str):
        return scrub_public_text(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            if (
                isinstance(k, str)
                and _SENSITIVE_KEY_RE.search(k)
                and isinstance(v, str)
            ):
                result[k] = "[redacted]" if len(v) >= 16 else scrub_public_text(v)
            else:
                result[k] = _scrub_json(v)
        return result
    if isinstance(value, (list, tuple)):
        return [_scrub_json(item) for item in value]
    return value


def redact_span_secrets(span: Any) -> None:
    """Span processor: mask secret-shaped text before the span is exported.

    MLflow traces capture prompts and completions by design, so enabling
    tracing is a deliberate operator decision. The app's own scrubbing contract
    still applies: ``content_safety.scrub_public_text`` runs over span inputs,
    outputs, and string attributes, so a key pasted into a prompt is masked in
    the store exactly as it is in the browser.

    Takes exactly one positional argument and returns nothing — mlflow 3.15.2's
    ``mlflow.tracing.configure`` validates both.
    """
    if span.inputs is not None:
        span.set_inputs(_scrub_json(span.inputs))
    if span.outputs is not None:
        span.set_outputs(_scrub_json(span.outputs))
    for key, value in list(span.attributes.items()):
        if isinstance(value, str) and (masked := scrub_public_text(value)) != value:
            span.set_attribute(key, masked)


def configure_mlflow(settings: Settings) -> bool:
    """Enable dspy tracing into MLflow when the operator opts in.

    Returns ``True`` when tracing was enabled and ``False`` when it was off or
    unusable. Never raises: this runs during application startup, so a bad
    tracking URI, an unwritable store, or a missing mlflow degrades to "no
    traces" with a warning instead of stopping the API from booting.

    Privacy boundary: enabling this makes LLM prompts and completions
    observable in the operator's own MLflow store, scrubbed by the same
    secret patterns the browser edition uses (``redact_span_secrets``).
    """
    if not settings.mlflow_tracing_enabled:
        return False
    try:
        import mlflow

        uri = resolve_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_tracking_uri(uri)
        experiment_id = ensure_experiment(TRACING_EXPERIMENT)
        mlflow.set_experiment(experiment_id=experiment_id)
        mlflow.tracing.configure(span_processors=[redact_span_secrets])
        # Trace predictor, ReAct, and tool-call spans from live runs. Compile-
        # time and eval-time tracing stay off here: optimization is logged
        # explicitly (params, metrics, artifacts) by the offline harness.
        mlflow.dspy.autolog(
            log_traces=True,
            log_traces_from_compile=False,
            log_traces_from_eval=False,
        )
    except Exception:  # noqa: BLE001 — observability must never break boot
        logger.warning(
            "MLflow dspy tracing could not be enabled; continuing without it",
            exc_info=True,
        )
        return False
    # Operator-facing startup fact: warn so it survives a default logging
    # setup, where the app's own INFO records are dropped. Enabling tracing
    # changes what the operator's store receives, so it must be confirmable.
    logger.warning("MLflow dspy tracing enabled (store: %s)", uri)
    return True
