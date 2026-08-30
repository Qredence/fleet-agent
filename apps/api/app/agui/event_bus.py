"""Thread-safe domain event channel from the DSPy worker to the SSE loop.

ReActV2 executes tools inside `asyncio.to_thread`, so instrumented tools
publish via `loop.call_soon_threadsafe`; the SSE generator drains the queue.
One bus per run — events can never leak across concurrent runs.

All publishes (worker and loop side) append to the loop's callback queue at
publish time, so delivery order always matches publication order: a direct
`put_nowait` from the loop thread could otherwise overtake worker events that
were scheduled earlier but have not run yet.
"""

import asyncio

from app.agui.cancel_token import RunCancelToken
from app.contracts.domain import DomainEvent

# Sentinel delivered when the producer side is finished.
_EVENT_SOURCE_DONE = object()


class RunEventBus:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        """Initialize an event bus for the specified event loop.

        Parameters:
            loop (asyncio.AbstractEventLoop): Event loop used for publishing.
        """
        self._loop = loop
        self._queue: asyncio.Queue[DomainEvent | object] = asyncio.Queue()
        self.cancel_token = RunCancelToken()

    def publish_from_worker(self, event: DomainEvent) -> None:
        """Queue an event for delivery from a worker thread."""
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def publish_from_loop(self, event: DomainEvent) -> None:
        """Schedule an event published from the event loop thread.

        Parameters:
            event (DomainEvent): The event to publish.

        The event is scheduled through the loop's callback queue instead of
        being put directly, so it can never overtake worker events that were
        scheduled earlier (single FIFO order for both publish paths).
        """
        self._loop.call_soon(self._queue.put_nowait, event)

    def close_from_loop(self) -> None:
        """Schedule the sentinel; pending worker events drain first."""
        self._loop.call_soon(self._queue.put_nowait, _EVENT_SOURCE_DONE)

    async def next(self) -> DomainEvent | object:
        """Next domain event, or the sentinel when the source closed."""
        return await self._queue.get()


DONE = _EVENT_SOURCE_DONE
