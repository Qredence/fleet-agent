"""Streams a scripted AG-UI event sequence as SSE, with protocol invariants:

- the request's Accept header drives the EventEncoder,
- a terminal event (RUN_FINISHED / RUN_ERROR) is emitted exactly once,
- client disconnects stop the stream quietly,
- internal failures surface as a safe RUN_ERROR, never a stack trace.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Any

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    StateSnapshotEvent,
)
from ag_ui.encoder import EventEncoder

from app.services.mock_run import TimedEvent

logger = logging.getLogger(__name__)

_TERMINAL_EVENTS = {EventType.RUN_FINISHED, EventType.RUN_ERROR}


class RunCoordinator:
    """Replays timed events; owns timing, id binding, and stream invariants."""

    def __init__(self, *, time_scale: float = 1.0) -> None:
        self._time_scale = time_scale

    async def stream(
        self,
        *,
        input_data: RunAgentInput,
        events: Iterable[TimedEvent],
        accept: str | None,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[str]:
        # Upstream types the optional parameter as `str`; "" is the no-value form.
        encoder = EventEncoder(accept=accept or "")
        terminal_sent = False
        started = asyncio.get_running_loop().time()

        try:
            for timed in events:
                if await is_disconnected():
                    return
                await self._wait_until(timed.at_ms, started)
                event = _bind_run_ids(timed.event, input_data)
                terminal_sent = event.type in _TERMINAL_EVENTS
                yield encoder.encode(event)
            if not terminal_sent:
                yield encoder.encode(
                    RunFinishedEvent(
                        thread_id=input_data.thread_id, run_id=input_data.run_id
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "mock run failed", extra={"thread_id": input_data.thread_id}
            )
            yield encoder.encode(
                RunErrorEvent(
                    message="The agent run failed.",
                    code="internal_error",
                )
            )

    async def _wait_until(self, at_ms: int, started: float) -> None:
        if self._time_scale <= 0:
            return
        elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000
        delay_s = max(0.0, (at_ms - elapsed_ms) / 1000 * self._time_scale)
        await asyncio.sleep(delay_s)


def _bind_run_ids(event: BaseEvent, input_data: RunAgentInput) -> BaseEvent:
    """Carry the client's thread/run ids onto fixture events."""
    updates: dict[str, Any] = {}
    if hasattr(event, "thread_id"):
        updates["thread_id"] = input_data.thread_id
    if hasattr(event, "run_id"):
        updates["run_id"] = input_data.run_id

    if isinstance(event, StateSnapshotEvent):
        snapshot = dict(event.snapshot)
        snapshot["threadId"] = input_data.thread_id
        snapshot_run = dict(snapshot.get("run", {}))
        snapshot_run["id"] = input_data.run_id
        snapshot["run"] = snapshot_run
        updates["snapshot"] = snapshot

    return event.model_copy(update=updates) if updates else event
