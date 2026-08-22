"""LiveDSPyCoordinator: streams a REAL engine run as AG-UI SSE.

Flow (plan phase 7):

    RUN_STARTED → STATE_SNAPSHOT → understanding delta
    while the engine runs: drain RunEventBus → TOOL_CALL_* + STATE_DELTA
    on result: synthesis deltas + TEXT_MESSAGE_* → final STATE_DELTA → RUN_FINISHED
    on engine exception: failed delta → RUN_ERROR (safe code, never a stack trace)
    on client disconnect: stop quietly (ReActV2 thread may finish in background)

Invariants match the mock coordinator: terminal event exactly once, Accept
header drives encoding, internal errors never leak implementation details.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder
from litellm.exceptions import RateLimitError

from app.agent.engine import AgentEngine, AgentRunContext, AgentRunResult
from app.agui.event_bus import DONE, RunEventBus
from app.agui.event_mapper import map_domain_event
from app.agui.trace_reducer import TraceReducer
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactStarted,
    SourceDiscovered,
)
from app.contracts.error_codes import public_error
from app.services.metrics import MetricsRegistry
from app.services.run_input import last_user_text
from app.services.run_persistence import RunPersistence

logger = logging.getLogger(__name__)

_TERMINAL_EVENTS = {EventType.RUN_FINISHED, EventType.RUN_ERROR}


class EngineBuilder(Protocol):
    def __call__(self, bus: RunEventBus, *, thread_id: str) -> AgentEngine: ...


class LiveDSPyCoordinator:
    async def stream(
        self,
        *,
        input_data: RunAgentInput,
        engine_builder: EngineBuilder,
        accept: str | None,
        is_disconnected: Callable[[], Awaitable[bool]],
        persistence: RunPersistence | None = None,
        run_timeout_s: float = 300.0,
        metrics: MetricsRegistry | None = None,
    ) -> AsyncIterator[str]:
        encoder = EventEncoder(accept=accept or "")
        thread_id = input_data.thread_id
        run_id = input_data.run_id
        loop = asyncio.get_running_loop()
        bus = RunEventBus(loop)
        prior_state = (
            await persistence.get_latest_state(thread_id) if persistence else None
        )
        reducer = TraceReducer(
            thread_id=thread_id, run_id=run_id, prior_state=prior_state
        )
        tools_message_id = f"msg-tools-{run_id}"
        started_monotonic = asyncio.get_running_loop().time()
        if metrics:
            metrics.incr("agent_runs_total")

        def emit(event: BaseEvent) -> str:
            return encoder.encode(event)

        async def mark_run_cancelled() -> None:
            """Client is gone: settle the run record + panel snapshot as
            cancelled. Late engine events are discarded by the bus close, and
            the loop's awaited result below is never consumed."""
            reducer.state["run"]["status"] = "cancelled"
            reducer.state["run"]["errorCode"] = "run_cancelled"
            if persistence:
                await persistence.run_cancelled(
                    thread_id=thread_id, run_id=run_id, state_json=reducer.state
                )
            logger.info("run %s cancelled (thread %s)", run_id, thread_id)

        try:
            if await is_disconnected():
                return
            yield emit(RunStartedEvent(thread_id=thread_id, run_id=run_id))
            yield emit(StateSnapshotEvent(snapshot=reducer.state))
            logger.info("run %s started (thread %s)", run_id, thread_id)

            user_message = _last_user_message_json(input_data)
            continuation_history = (
                await persistence.get_continuation_history(thread_id)
                if persistence
                else None
            )
            if persistence and user_message:
                await persistence.run_started(
                    thread_id=thread_id, run_id=run_id, user_message=user_message
                )

            yield emit(StateDeltaEvent(delta=reducer.begin()))

            context = AgentRunContext(thread_id=thread_id, run_id=run_id)
            engine = engine_builder(bus, thread_id=thread_id)
            engine_task = asyncio.create_task(
                engine.run(
                    user_request=last_user_text(input_data),
                    # continuation history arrives with persistence (PR 7)
                    history=continuation_history,
                    context=context,
                )
            )
            engine_task.add_done_callback(lambda _t: bus.close_from_loop())

            try:
                # The timeout bounds the ENTIRE run: drain + final result wait.
                async with asyncio.timeout(run_timeout_s):
                    while True:
                        if await is_disconnected():
                            bus.cancel_token.cancel()
                            engine_task.cancel()
                            await mark_run_cancelled()
                            return
                        event = await bus.next()
                        if event is DONE:
                            break
                        agui_events = map_domain_event(
                            event,  # type: ignore[arg-type]
                            tools_message_id=tools_message_id,
                            reducer=reducer,
                        )
                        if persistence and isinstance(
                            event,
                            (
                                SourceDiscovered,
                                ArtifactStarted,
                                ArtifactReady,
                                ArtifactFailed,
                            ),
                        ):
                            await persistence.record_domain_event(
                                event, thread_id=thread_id, run_id=run_id
                            )
                        if metrics:
                            from app.contracts.domain import ToolCompleted, ToolFailed

                            if isinstance(event, ToolCompleted):
                                metrics.incr("agent_tool_calls_total")
                                metrics.observe(
                                    "agent_tool_duration_ms", event.duration_ms
                                )
                            elif isinstance(event, ToolFailed):
                                metrics.incr("agent_tool_calls_total")
                                metrics.incr("agent_tool_errors_total")
                                metrics.observe(
                                    "agent_tool_duration_ms", event.duration_ms
                                )
                        for agui_event in agui_events:
                            yield emit(agui_event)

                    result = await engine_task  # exceptions land here, after draining
            except TimeoutError:
                bus.cancel_token.cancel()
                engine_task.cancel()
                result = AgentRunResult(
                    status="failed",
                    answer=None,
                    process_summary="The agent run timed out.",
                    termination_reason="timeout",
                    error_code="agent_timeout",
                )

            if result.status == "completed":
                yield emit(StateDeltaEvent(delta=reducer.complete_run(result)))
                message_id = f"msg-{run_id}"
                yield emit(
                    TextMessageStartEvent(message_id=message_id, role="assistant")
                )
                yield emit(
                    TextMessageContentEvent(
                        message_id=message_id, delta=result.answer or ""
                    )
                )
                yield emit(TextMessageEndEvent(message_id=message_id))
                if persistence:
                    await persistence.run_completed(
                        thread_id=thread_id,
                        run_id=run_id,
                        result=result,
                        state_json=reducer.state,
                        assistant_message_id=message_id,
                    )
                yield emit(RunFinishedEvent(thread_id=thread_id, run_id=run_id))
                logger.info("run %s completed (thread %s)", run_id, thread_id)
                if metrics:
                    metrics.observe(
                        "agent_run_duration_ms",
                        (asyncio.get_running_loop().time() - started_monotonic) * 1000,
                    )
            else:
                yield emit(StateDeltaEvent(delta=reducer.complete_run(result)))
                if persistence:
                    await persistence.run_failed(
                        thread_id=thread_id,
                        run_id=run_id,
                        result=result,
                        state_json=reducer.state,
                    )
                code, message = public_error(result.error_code, "agent_no_output")
                logger.warning(
                    "run %s failed [%s] (thread %s)", run_id, code, thread_id
                )
                if metrics:
                    metrics.incr("agent_run_errors_total")
                yield emit(RunErrorEvent(message=message, code=code))

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code, message = _code_for_exception(exc)
            logger.exception("live run failed (thread %s, run %s)", thread_id, run_id)
            yield emit(
                StateDeltaEvent(
                    delta=reducer.complete_run(
                        AgentRunResult(
                            status="failed",
                            answer=None,
                            process_summary=(
                                "The agent run failed before producing a response."
                            ),
                            termination_reason="failed",
                            error_code=code,
                        )
                    )
                )
            )
            yield emit(RunErrorEvent(message=message, code=code))
            if metrics:
                metrics.incr("agent_run_errors_total")


def _code_for_exception(exc: Exception) -> tuple[str, str]:
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, RateLimitError) or "rate limit" in text or "429" in text:
        return public_error("rate_limited")
    return public_error("internal_error")


def _last_user_message_json(input_data: RunAgentInput) -> dict[str, Any] | None:
    for message in reversed(input_data.messages):
        if message.role == "user":
            return message.model_dump(by_alias=True, mode="json", exclude_none=True)
    return None
