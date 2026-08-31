import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.approval import APPROVAL_REGISTRY
from app.agent.factory import make_engine_builder
from app.api.agent import router as agent_router
from app.api.artifacts import router as artifacts_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.api.projects import router as projects_router
from app.api.threads import router as threads_router
from app.api.tools import router as tools_router
from app.persistence.db import build_engine, build_sessionmaker
from app.persistence.repositories import RunsRepository
from app.services.artifact_storage import LocalArtifactStorage
from app.services.durable_approvals import (
    resumable_run_ids,
    sweep_expired_checkpoints,
)
from app.services.metrics import MetricsRegistry
from app.services.mlflow_observability import configure_mlflow
from app.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Opt-in dspy tracing into MLflow: enabled once, before any predictor
    # call. Off by default; see app/services/mlflow_observability.py.
    configure_mlflow(app.state.settings)
    # Server-restart reconciliation: in-memory run state is gone, but runs
    # that parked a durable approval checkpoint stay interrupted and
    # resumable; everything else settles as failed.
    sessions = app.state.db_sessions
    APPROVAL_REGISTRY.clear()
    resumable = await resumable_run_ids(sessions)
    orphaned = await RunsRepository(sessions).mark_orphaned_interrupted(
        keep_run_ids=resumable
    )
    if orphaned:
        logger.warning("marked %d orphaned runs as failed", orphaned)
    if resumable:
        logger.info(
            "preserved %d interrupted runs with resumable approval checkpoints",
            len(resumable),
        )
    swept = await sweep_expired_checkpoints(sessions)
    if swept:
        logger.info("swept %d expired approval checkpoints", swept)
    if app.state.settings.api_key is None:
        logger.warning(
            "FLEET_AGENT_API_KEY is unset — the API runs in open local mode. "
            "Set it for any shared deployment."
        )
    yield
    engine = app.state.db_engine
    await engine.dispose()


def create_app() -> FastAPI:
    """
    Create and configure the Fleet Agent API application.

    Returns:
        FastAPI: The configured application instance.
    """
    settings = get_settings()

    app = FastAPI(
        title="Fleet Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.artifact_storage = LocalArtifactStorage(Path(settings.artifacts_dir))
    app.state.db_engine = build_engine(settings)
    app.state.db_sessions = build_sessionmaker(app.state.db_engine)
    app.state.engine_builder = make_engine_builder(
        settings,
        storage=app.state.artifact_storage,
        sessions=app.state.db_sessions,
    )
    app.state.run_semaphore = asyncio.Semaphore(settings.max_concurrent_runs)
    app.state.metrics = MetricsRegistry()

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-API-Key",
            "X-OpenRouter-Key",
            "X-OpenRouter-Model",
            # BYOK provider overrides parsed by app/api/provider.py and sent
            # by the web client on every browser-owned provider run.
            "X-LLM-Key",
            "X-LLM-Base-Url",
            "X-LLM-Model",
            "X-LLM-Response-Format",
            "X-LLM-Messages-Format",
        ],
    )

    app.include_router(health_router)
    app.include_router(agent_router)
    app.include_router(projects_router)
    app.include_router(threads_router)
    app.include_router(tools_router)
    app.include_router(artifacts_router)
    app.include_router(metrics_router)

    return app


app = create_app()
