import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.factory import make_engine_builder
from app.api.agent import router as agent_router
from app.api.artifacts import router as artifacts_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.api.projects import router as projects_router
from app.api.threads import router as threads_router
from app.persistence.db import build_engine, build_sessionmaker
from app.persistence.repositories import RunsRepository
from app.services.artifact_storage import LocalArtifactStorage
from app.services.metrics import MetricsRegistry
from app.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Server-restart reconciliation: orphaned "running" runs are interrupted.
    orphaned = await RunsRepository(app.state.db_sessions).mark_orphaned_interrupted()
    if orphaned:
        logger.warning("marked %d orphaned running runs as interrupted", orphaned)
    if app.state.settings.api_key is None:
        logger.warning(
            "FLEET_AGENT_API_KEY is unset — the API runs in open local mode. "
            "Set it for any shared deployment."
        )
    yield
    engine = app.state.db_engine
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Fleet Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.artifact_storage = LocalArtifactStorage(Path(settings.artifacts_dir))
    app.state.engine_builder = make_engine_builder(
        settings, storage=app.state.artifact_storage
    )
    app.state.db_engine = build_engine(settings)
    app.state.db_sessions = build_sessionmaker(app.state.db_engine)
    app.state.run_semaphore = asyncio.Semaphore(settings.max_concurrent_runs)
    app.state.metrics = MetricsRegistry()

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Accept", "Content-Type", "Authorization", "X-API-Key"],
    )

    app.include_router(health_router)
    app.include_router(agent_router)
    app.include_router(projects_router)
    app.include_router(threads_router)
    app.include_router(artifacts_router)
    app.include_router(metrics_router)

    return app


app = create_app()
