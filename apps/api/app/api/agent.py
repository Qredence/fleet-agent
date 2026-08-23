"""POST /api/agent — AG-UI over SSE.

Two modes (FLEET_AGENT_AGENT_MODE):
- "fixtures" (dev/CI default): replays the canonical NDJSON mock streams,
- "engine" (production): LiveDSPyCoordinator runs the real DSPy ReActV2
  bridge with instrumented tools, persisting runs/messages/state/history.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import cast

from ag_ui.core import RunAgentInput
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agui.live_coordinator import EngineBuilder, LiveDSPyCoordinator
from app.agui.run_coordinator import RunCoordinator
from app.contracts.error_codes import ERROR_MESSAGES
from app.persistence.repositories import RunsRepository, ThreadsRepository
from app.services.metrics import MetricsRegistry
from app.services.mock_run import load_fixture, select_fixture_name
from app.services.run_persistence import (
    ReservationErrorCode,
    RunPersistence,
    RunReservationError,
)
from app.settings import Settings

router = APIRouter(prefix="/api", tags=["agent"])
logger = logging.getLogger(__name__)

_RESERVATION_RESPONSES: dict[ReservationErrorCode, tuple[int, str]] = {
    ReservationErrorCode.THREAD_NOT_FOUND: (404, "Thread not found."),
    ReservationErrorCode.RUN_ALREADY_EXISTS: (
        409,
        "A run with this ID already exists.",
    ),
    ReservationErrorCode.INPUT_MESSAGE_INVALID: (
        409,
        "The input message must be a user message.",
    ),
    ReservationErrorCode.MESSAGE_PARENT_INVALID: (
        409,
        "The message branch is invalid.",
    ),
    ReservationErrorCode.MESSAGE_NOT_FOUND: (409, "The message branch is invalid."),
    ReservationErrorCode.MESSAGE_WRONG_THREAD: (409, "The message branch is invalid."),
    ReservationErrorCode.RESERVATION_CONFLICT: (
        409,
        "Run reservation could not be created.",
    ),
}


def _reservation_http_error(exc: RunReservationError) -> HTTPException:
    status, detail = _RESERVATION_RESPONSES.get(
        exc.code,
        _RESERVATION_RESPONSES[ReservationErrorCode.RESERVATION_CONFLICT],
    )
    return HTTPException(status_code=status, detail=detail)


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable reverse-proxy buffering for SSE
}


def get_engine_builder(request: Request) -> EngineBuilder:
    return cast(EngineBuilder, request.app.state.engine_builder)


def get_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.db_sessions)


@router.post("/agent")
async def run_agent(input_data: RunAgentInput, request: Request) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    accept = request.headers.get("accept")

    if settings.agent_mode == "engine":
        sessions = get_sessions(request)
        # Runs must belong to a persisted thread (FK integrity + no
        # cross-thread writes). Fixtures mode stays thread-agnostic on purpose.
        try:
            thread = await ThreadsRepository(sessions).get(input_data.thread_id)
            if thread is None:
                raise HTTPException(status_code=404, detail="Thread not found.")
            # Idempotency: an existing runId must not start again.
            existing_run = await RunsRepository(sessions).get(input_data.run_id)
            if existing_run is not None:
                raise HTTPException(
                    status_code=409, detail="A run with this ID already exists."
                )
        except HTTPException:
            raise
        except Exception:
            logger.exception(
                "reservation preflight failed (thread %s, run %s)",
                input_data.thread_id,
                input_data.run_id,
            )
            raise HTTPException(
                status_code=503,
                detail="Run reservation could not be created.",
            ) from None

        # Global concurrency cap: graceful 429 when saturated.
        semaphore: asyncio.Semaphore = request.app.state.run_semaphore
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
        except TimeoutError:
            raise HTTPException(
                status_code=429, detail=ERROR_MESSAGES["rate_limited"]
            ) from None

        persistence = RunPersistence(sessions)
        try:
            await persistence.reserve_run(input_data=input_data)
        except RunReservationError as exc:
            semaphore.release()
            raise _reservation_http_error(exc) from None
        except Exception:
            # Reservation is the only pre-stream operation that owns the
            # permit. Never strand capacity when a database/serialization
            # error occurs before a StreamingResponse is returned.  Driver
            # details stay in server logs; clients receive a fixed response.
            semaphore.release()
            logger.exception(
                "run reservation failed (thread %s, run %s)",
                input_data.thread_id,
                input_data.run_id,
            )
            raise HTTPException(
                status_code=503,
                detail="Run reservation could not be created.",
            ) from None

        stream = LiveDSPyCoordinator().stream(
            input_data=input_data,
            engine_builder=get_engine_builder(request),
            accept=accept,
            is_disconnected=request.is_disconnected,
            persistence=persistence,
            run_timeout_s=settings.run_timeout_seconds,
            metrics=request.app.state.metrics,
        )

        async def gated() -> AsyncIterator[str]:
            metrics: MetricsRegistry = request.app.state.metrics
            metrics.gauge_delta("active_sse_connections", 1)
            try:
                async for chunk in stream:
                    yield chunk
            finally:
                metrics.gauge_delta("active_sse_connections", -1)
                semaphore.release()

        return StreamingResponse(
            gated(), media_type="text/event-stream", headers=_SSE_HEADERS
        )

    coordinator = RunCoordinator()
    events = load_fixture(select_fixture_name(input_data))
    stream = coordinator.stream(
        input_data=input_data,
        events=events,
        accept=accept,
        is_disconnected=request.is_disconnected,
    )
    return StreamingResponse(
        stream, media_type="text/event-stream", headers=_SSE_HEADERS
    )
