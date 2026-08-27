"""Thread-safe domain event channel from the DSPy worker to the SSE loop.

ReActV2 executes tools inside `asyncio.to_thread`, so instrumented tools
publish via `loop.call_soon_threadsafe`; the SSE generator drains the queue.
One bus per run — events can never leak across concurrent runs.
"""

import asyncio

from app.agui.cancel_token import RunCancelToken
from app.contracts.domain import DomainEvent

# Sentinel delivered when the producer side is finished.
_EVENT_SOURCE_DONE = object()


class RunEventBus:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[DomainEvent | object] = asyncio.Queue()
        self.cancel_token = RunCancelToken()

    def publish_from_worker(self, event: DomainEvent) -> None:
        """Queue an event for delivery from a worker thread."""
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def publish_from_loop(self, event: DomainEvent) -> None:
        """Publishes an event directly from the event loop.

        Parameters:
            event (DomainEvent): The event to publish.
        """
        self._queue.put_nowait(event)

    def close_from_loop(self) -> None:
        """Signal that no more domain events will arrive."""
        self._queue.put_nowait(_EVENT_SOURCE_DONE)

    async def next(self) -> DomainEvent | object:
        """Next domain event, or the sentinel when the source closed."""
        return await self._queue.get()


DONE = _EVENT_SOURCE_DONE
