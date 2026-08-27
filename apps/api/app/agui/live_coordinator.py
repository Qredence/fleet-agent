"""Live DSPy coordinator with durable, exactly-once terminal settlement."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol

from ag_ui.core import (
    BaseEvent,
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

from app.agent.engine import (
    AgentEngine,
    AgentRunContext,
    AgentRunResult,
    AgentStreamUpdate,
)
from app.agui.event_bus import DONE, RunEventBus
from app.agui.event_mapper import chunk_text, map_domain_event
from app.agui.trace_reducer import TraceReducer
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactStarted,
    FinalFieldsReady,
    SourceDiscovered,
    ToolCompleted,
    ToolFailed,
)
from app.contracts.error_codes import public_error
from app.services.metrics import MetricsRegistry
from app.services.run_input import last_user_text
from app.services.run_persistence import RunPersistence

logger = logging.getLogger(__name__)
_CANCEL_SETTLEMENT_TIMEOUT_S = 2.0


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
        """
        Stream an agent run as encoded AG-UI events.
        
        Parameters:
        	input_data (RunAgentInput): Input data identifying the thread, run, and user request.
        	engine_builder (EngineBuilder): Factory that creates the agent engine and connects it to the event bus.
        	accept (str | None): Requested event encoding or media type.
        	is_disconnected (Callable[[], Awaitable[bool]]): Callback that reports whether the client disconnected.
        	persistence (RunPersistence | None): Optional lifecycle and state persistence service.
        	run_timeout_s (float): Maximum duration allowed for event processing and engine completion.
        	metrics (MetricsRegistry | None): Optional metrics registry for run and tool metrics.
        
        Yields:
        	str: Encoded lifecycle, state, message, and terminal events for the agent run.
        """
        encoder = EventEncoder(accept=accept or "")
        thread_id = input_data.thread_id
        run_id = input_data.run_id
        loop = asyncio.get_running_loop()
        bus = RunEventBus(loop)
        run = await persistence.get_run(run_id) if persistence else None
        if persistence and run is None:
            run = await persistence.reserve_run(input_data=input_data)
        continuation_head = run.continuation_message_id if run else None
        prior_state = (
            await persistence.get_latest_state(thread_id, continuation_head)
            if persistence
            else None
        )
        reducer = TraceReducer(
            thread_id=thread_id,
            run_id=run_id,
            prior_state=prior_state,
            run_scoped_decisions=persistence is not None,
        )
        tools_message_id = f"msg-tools-{run_id}"
        answer_message_id = f"msg-{run_id}"
        started_monotonic = loop.time()
        if metrics:
            metrics.incr("agent_runs_total")

        def emit(event: BaseEvent) -> str:
            return encoder.encode(event)

        terminal_settled = False
        terminal_emitted = False
        settlement_lock = asyncio.Lock()
        metrics_recorded = False
        engine_task: asyncio.Task[AgentRunResult] | None = None

        def record_terminal_metrics(*, error: bool) -> None:
            nonlocal metrics_recorded
            if metrics is None or metrics_recorded:
                return
            metrics_recorded = True
            metrics.observe(
                "agent_run_duration_ms",
                (loop.time() - started_monotonic) * 1000,
            )
            if error:
                metrics.incr("agent_run_errors_total")

        def complete_public_state(result: AgentRunResult) -> list[dict[str, object]]:
            """Finish the public reducer even if a mapper/reducer hook fails."""

            try:
                return reducer.complete_run(result)
            except Exception:
                logger.exception(
                    "public state reducer failed (thread %s, run %s)",
                    thread_id,
                    run_id,
                )
                run_state = reducer.state.setdefault("run", {})
                run_state["status"] = (
                    "cancelled" if result.error_code == "run_cancelled" else "failed"
                )
                run_state["finishedAt"] = _utc_now()
                if result.termination_reason:
                    run_state["terminationReason"] = result.termination_reason
                if result.error_code:
                    run_state["errorCode"] = result.error_code
                return []

        async def settle_cancelled() -> bool:
            nonlocal terminal_settled
            async with settlement_lock:
                if terminal_settled:
                    return False
                cancel_result = AgentRunResult(
                    status="failed",
                    answer=None,
                    process_summary="The agent run was cancelled.",
                    termination_reason="cancelled",
                    error_code="run_cancelled",
                )
                complete_public_state(cancel_result)
                reducer.state["run"]["status"] = "cancelled"
                reducer.state["run"]["errorCode"] = "run_cancelled"
                settled = (
                    await _settle_with_retry(
                        lambda: persistence.run_cancelled(
                            thread_id=thread_id,
                            run_id=run_id,
                            state_json=reducer.state,
                        )
                    )
                    if persistence
                    else True
                )
                # A failed second retry is logged by _settle_with_retry, but
                # this generator must still stop rather than racing another
                # terminal event into the same run.
                terminal_settled = True
                record_terminal_metrics(error=True)
                logger.info("run %s cancelled (thread %s)", run_id, thread_id)
                return settled

        async def settle_cancelled_bounded() -> bool:
            """
            Complete cancellation settlement within a bounded, shielded interval.
            
            Returns:
                bool: `True` if cancellation settlement completes successfully, `False` if it times out or fails.
            """

            task = asyncio.create_task(settle_cancelled())
            try:
                return await asyncio.wait_for(
                    asyncio.shield(task), timeout=_CANCEL_SETTLEMENT_TIMEOUT_S
                )
            except TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
                logger.error(
                    "cancellation settlement timed out (thread %s, run %s)",
                    thread_id,
                    run_id,
                )
                return False

        def pump_stream(
            stream_factory: Callable[..., Any],
            *,
            user_request: str,
            history: Any | None,
            context: AgentRunContext,
        ) -> Coroutine[Any, Any, AgentRunResult]:
            """Consume a streaming engine and publish final answer fields as soon as they become available.
            
            Parameters:
                stream_factory: Callable that produces agent stream updates.
                user_request: The user's request.
                history: Prior conversation history, if available.
                context: Context for the agent run.
            
            Returns:
                The authoritative agent run result.
            
            Raises:
                RuntimeError: If the stream ends without a final result.
            """

            async def run_pump() -> AgentRunResult:
                """
                Consume the streaming engine updates and provide the completed agent run result.
                
                Raises:
                    RuntimeError: If the stream ends without a final result.
                
                Returns:
                    AgentRunResult: The completed agent run result.
                """
                result: AgentRunResult | None = None
                async for update in stream_factory(
                    user_request=user_request,
                    history=history,
                    context=context,
                ):
                    assert isinstance(update, AgentStreamUpdate)
                    if update.kind == "final_fields":
                        bus.publish_from_loop(
                            FinalFieldsReady(
                                answer=update.answer,
                                process_summary=update.process_summary,
                            )
                        )
                    else:
                        result = update.result
                if result is None:
                    raise RuntimeError("streaming engine ended without a final result")
                return result

            return run_pump()

        answer_streamed = False
        try:
            if persistence:
                await persistence.mark_running(run_id=run_id, state_json=reducer.state)
            if await is_disconnected():
                await settle_cancelled_bounded()
                return

            yield emit(RunStartedEvent(thread_id=thread_id, run_id=run_id))
            yield emit(StateSnapshotEvent(snapshot=reducer.state))
            logger.info("run %s started (thread %s)", run_id, thread_id)

            continuation_history = (
                await persistence.get_continuation_history(thread_id, continuation_head)
                if persistence
                else None
            )
            yield emit(StateDeltaEvent(delta=reducer.begin()))

            context = AgentRunContext(thread_id=thread_id, run_id=run_id)
            engine = engine_builder(bus, thread_id=thread_id)
            stream_factory = getattr(engine, "stream", None)
            if callable(stream_factory):
                engine_task = asyncio.create_task(
                    pump_stream(
                        stream_factory,
                        user_request=last_user_text(input_data),
                        history=continuation_history,
                        context=context,
                    )
                )
            else:
                engine_task = asyncio.create_task(
                    engine.run(
                        user_request=last_user_text(input_data),
                        history=continuation_history,
                        context=context,
                    )
                )
            engine_task.add_done_callback(lambda _task: bus.close_from_loop())

            try:
                # This timeout covers event draining and the final engine wait.
                async with asyncio.timeout(run_timeout_s):
                    while True:
                        if await is_disconnected():
                            bus.cancel_token.cancel()
                            engine_task.cancel()
                            await settle_cancelled_bounded()
                            return
                        event = await bus.next()
                        if event is DONE:
                            break
                        if isinstance(event, FinalFieldsReady) and event.answer:
                            answer_streamed = True
                        agui_events = map_domain_event(
                            event,  # type: ignore[arg-type]
                            tools_message_id=tools_message_id,
                            reducer=reducer,
                            answer_message_id=answer_message_id,
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
                    result = await engine_task
            except TimeoutError:
                bus.cancel_token.cancel()
                engine_task.cancel()
                try:
                    await engine_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("engine cleanup failed after timeout")
                result = AgentRunResult(
                    status="failed",
                    answer=None,
                    process_summary="The agent run timed out.",
                    termination_reason="timeout",
                    error_code="agent_timeout",
                )

            delta = complete_public_state(result)
            if result.status == "completed":
                yield emit(StateDeltaEvent(delta=delta))
                if not answer_streamed:
                    yield emit(
                        TextMessageStartEvent(
                            message_id=answer_message_id, role="assistant"
                        )
                    )
                    for chunk in chunk_text(result.answer or ""):
                        yield emit(
                            TextMessageContentEvent(
                                message_id=answer_message_id, delta=chunk
                            )
                        )
                    yield emit(TextMessageEndEvent(message_id=answer_message_id))
                settled = (
                    await _settle_with_retry(
                        lambda: persistence.run_completed(
                            thread_id=thread_id,
                            run_id=run_id,
                            result=result,
                            state_json=reducer.state,
                            assistant_message_id=answer_message_id,
                        )
                    )
                    if persistence
                    else True
                )
                if not settled:
                    # The answer and completed public state are already on the
                    # wire.  Persistence is retried above, but a database
                    # outage must not turn this accepted stream into an
                    # unterminated response or leak a driver exception.
                    logger.error(
                        "completed run could not be persisted (thread %s, run %s)",
                        thread_id,
                        run_id,
                    )
                terminal_settled = True
                record_terminal_metrics(error=False)
                terminal_emitted = True
                yield emit(RunFinishedEvent(thread_id=thread_id, run_id=run_id))
                logger.info("run %s completed (thread %s)", run_id, thread_id)
            else:
                yield emit(StateDeltaEvent(delta=delta))
                settled = (
                    await _settle_with_retry(
                        lambda: persistence.run_failed(
                            thread_id=thread_id,
                            run_id=run_id,
                            result=result,
                            state_json=reducer.state,
                        )
                    )
                    if persistence
                    else True
                )
                if not settled:
                    logger.error(
                        "failed run could not be persisted (thread %s, run %s)",
                        thread_id,
                        run_id,
                    )
                terminal_settled = True
                code, message = public_error(result.error_code, "agent_no_output")
                logger.warning(
                    "run %s failed [%s] (thread %s)", run_id, code, thread_id
                )
                record_terminal_metrics(error=True)
                terminal_emitted = True
                yield emit(RunErrorEvent(message=message, code=code))

        except asyncio.CancelledError:
            if not terminal_emitted:
                if engine_task is not None and not engine_task.done():
                    engine_task.cancel()
                try:
                    await settle_cancelled_bounded()
                except Exception:
                    logger.exception(
                        "could not persist cancellation (thread %s, run %s)",
                        thread_id,
                        run_id,
                    )
            raise
        except Exception as exc:
            if terminal_emitted or terminal_settled:
                raise
            code, message = _code_for_exception(exc)
            failure = AgentRunResult(
                status="failed",
                answer=None,
                process_summary="The agent run failed before producing a response.",
                termination_reason="failed",
                error_code=code,
            )
            logger.exception("live run failed (thread %s, run %s)", thread_id, run_id)
            delta = complete_public_state(failure)
            settled = True
            if persistence:
                try:
                    settled = await _settle_with_retry(
                        lambda: persistence.run_failed(
                            thread_id=thread_id,
                            run_id=run_id,
                            result=failure,
                            state_json=reducer.state,
                        )
                    )
                except Exception:
                    # Keep the fallback terminal event safe even if a custom
                    # persistence implementation escapes the retry wrapper.
                    logger.exception(
                        "could not persist unexpected failure (thread %s, run %s)",
                        thread_id,
                        run_id,
                    )
                    settled = False
            if not settled:
                logger.error(
                    "unexpected terminal failure could not be persisted "
                    "(thread %s, run %s)",
                    thread_id,
                    run_id,
                )
            # This fallback is deliberately unconditional: once the request
            # was accepted, clients must receive one safe terminal event even
            # when both persistence attempts fail.
            terminal_settled = True
            terminal_emitted = True
            record_terminal_metrics(error=True)
            yield emit(StateDeltaEvent(delta=delta))
            yield emit(RunErrorEvent(message=message, code=code))


async def _settle_with_retry(
    operation: Callable[[], Awaitable[bool | None]],
) -> bool:
    """Retry one lifecycle write with a fresh session after rollback."""

    for attempt in range(2):
        try:
            result = await operation()
            return result is not False
        except Exception:
            if attempt == 0:
                logger.warning(
                    "terminal persistence failed; retrying with a fresh session",
                    exc_info=True,
                )
            else:
                logger.exception("terminal persistence failed after retry")
    return False


def _code_for_exception(exc: Exception) -> tuple[str, str]:
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, RateLimitError) or "rate limit" in text or "429" in text:
        return public_error("rate_limited")
    return public_error("internal_error")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
