"""AG-UI SSE coordinators: fixture replay and the live DSPy run.

Both coordinators own the same protocol invariants — the Accept header drives the
encoder, exactly one terminal event is emitted, a client disconnect stops the
stream quietly, and internal failures surface as a safe RUN_ERROR (never a stack
trace). ``RunCoordinator`` replays scripted fixture streams; ``LiveDSPyCoordinator``
runs the real engine, reduces domain events into public state, and settles the
run durably.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
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
from dspy import LMAuthError, LMInvalidRequestError, LMRateLimitError

from app.agent.approval import approved_tool_names
from app.agent.engine import (
    AgentRunContext,
    AgentRunResult,
    AgentStreamUpdate,
    EngineBuilder,
)
from app.agent.event_bus import DONE, RunEventBus
from app.agent.provider import ProviderOverride
from app.agui.state import TraceReducer
from app.agui.wire import chunk_text, map_domain_event
from app.contracts.constants import public_error
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactStarted,
    DomainEvent,
    FinalFieldsReady,
    SourceDiscovered,
    SynthesisTokenDelta,
    ToolCompleted,
    ToolFailed,
)
from app.kernel.run_input import history_from_agui_messages, last_user_text
from app.persistence.models import Run
from app.persistence.run_persistence import RunPersistence
from app.services.metrics import MetricsRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimedEvent:
    """One fixture line: emit ``event`` ``at_ms`` after the stream starts."""

    at_ms: int
    event: BaseEvent


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
        run_timeout_s: float | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> AsyncIterator[str]:
        # Upstream types the optional parameter as `str`; "" is the no-value form.
        encoder = EventEncoder(accept=accept or "")
        terminal_sent = False
        loop = asyncio.get_running_loop()
        started = loop.time()
        metrics_recorded = False
        if metrics:
            metrics.incr("agent_runs_total")

        def record_terminal_metrics(*, error: bool) -> None:
            nonlocal metrics_recorded
            if metrics is None or metrics_recorded:
                return
            metrics_recorded = True
            metrics.observe(
                "agent_run_duration_ms",
                (loop.time() - started) * 1000,
            )
            if error:
                metrics.incr("agent_run_errors_total")

        try:
            async with asyncio.timeout(run_timeout_s):
                for timed in events:
                    if terminal_sent:
                        return
                    if await is_disconnected():
                        record_terminal_metrics(error=True)
                        return
                    await self._wait_until(timed.at_ms, started)
                    event = _bind_run_ids(timed.event, input_data)
                    encoded = encoder.encode(event)
                    if event.type in _TERMINAL_EVENTS:
                        terminal_sent = True
                        record_terminal_metrics(error=event.type == EventType.RUN_ERROR)
                    yield encoded
            if not terminal_sent:
                encoded = encoder.encode(
                    RunFinishedEvent(
                        thread_id=input_data.thread_id, run_id=input_data.run_id
                    )
                )
                terminal_sent = True
                record_terminal_metrics(error=False)
                yield encoded
        except TimeoutError:
            if terminal_sent:
                return
            code, message = public_error("agent_timeout")
            terminal_sent = True
            record_terminal_metrics(error=True)
            yield encoder.encode(RunErrorEvent(message=message, code=code))
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            if terminal_sent:
                return
            logger.exception(
                "mock run failed", extra={"thread_id": input_data.thread_id}
            )
            terminal_sent = True
            record_terminal_metrics(error=True)
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

    # Fixtures intentionally use stable IDs so they are easy to inspect. The
    # browser-owned message repository, however, requires message IDs to be
    # unique within a thread. Scope every fixture message identity to this
    # run while keeping tool-call IDs stable for the fixture trace.
    for field_name in ("message_id", "parent_message_id"):
        value = getattr(event, field_name, None)
        if isinstance(value, str) and value:
            updates[field_name] = f"{value}-{input_data.run_id}"

    if isinstance(event, StateSnapshotEvent):
        snapshot = dict(event.snapshot)
        snapshot["threadId"] = input_data.thread_id
        snapshot_run = dict(snapshot.get("run", {}))
        snapshot_run["id"] = input_data.run_id
        snapshot["run"] = snapshot_run
        updates["snapshot"] = snapshot

    if isinstance(event, CustomEvent) and isinstance(event.value, dict):
        custom_value = dict(event.value)
        changed = False
        if "runId" in custom_value:
            custom_value["runId"] = input_data.run_id
            changed = True
        msg_id = custom_value.get("messageId")
        if isinstance(msg_id, str) and msg_id:
            custom_value["messageId"] = f"{msg_id}-{input_data.run_id}"
            changed = True
        if changed:
            updates["value"] = custom_value

    return event.model_copy(update=updates) if updates else event


_CANCEL_SETTLEMENT_TIMEOUT_S = 2.0


def _consume_task_exception(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except Exception:
        return
    if exc is not None:
        logger.debug(
            "background task finished with %s after cancellation",
            type(exc).__name__,
        )


async def _cancel_task_bounded(
    task: asyncio.Task[Any] | None,
    *,
    label: str,
    thread_id: str,
    run_id: str,
    timeout_s: float | None = None,
) -> None:
    if task is None:
        return
    bound_s = _CANCEL_SETTLEMENT_TIMEOUT_S if timeout_s is None else timeout_s
    if not task.done():
        task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=bound_s)
    except TimeoutError:
        task.add_done_callback(_consume_task_exception)
        logger.error(
            "%s cleanup timed out (thread %s, run %s)",
            label,
            thread_id,
            run_id,
        )
    except asyncio.CancelledError:
        if not task.cancelled():
            task.add_done_callback(_consume_task_exception)
            raise
    except Exception as exc:
        logger.error(
            "%s cleanup failed (exception_type=%s)",
            label,
            type(exc).__name__,
        )


async def _pump_stream(
    stream_factory: Callable[..., Any],
    *,
    bus: RunEventBus,
    user_request: str,
    history: Any | None,
    context: AgentRunContext,
) -> AgentRunResult:
    """Consume streaming engine updates and publish final answer fields.

    Raises:
        RuntimeError: If the stream ends without a final result.
    """
    result: AgentRunResult | None = None
    summary_parts: list[str] = []
    async for update in stream_factory(
        user_request=user_request, history=history, context=context
    ):
        assert isinstance(update, AgentStreamUpdate)
        if update.kind == "final_fields":
            bus.publish_from_loop(
                FinalFieldsReady(
                    answer=update.answer,
                    process_summary=update.process_summary,
                )
            )
        elif update.kind == "token":
            # Streamed synthesis fields (already scrubbed by the
            # engine) become incremental message/state updates.
            if update.delta and update.stream_field == "answer":
                bus.publish_from_loop(
                    SynthesisTokenDelta(
                        field="answer",
                        delta=update.delta,
                        summary_so_far="".join(summary_parts),
                    )
                )
            elif update.delta and update.stream_field == "process_summary":
                summary_parts.append(update.delta)
                bus.publish_from_loop(
                    SynthesisTokenDelta(
                        field="process_summary",
                        delta=update.delta,
                        summary_so_far="".join(summary_parts),
                    )
                )
        else:
            result = update.result
    if result is None:
        raise RuntimeError("streaming engine ended without a final result")
    return result


@dataclass
class _LiveRunSession:
    """Mutable coordinator runtime state and lifecycle helpers for one live run."""

    thread_id: str
    run_id: str
    assistant_message_id: str
    reducer: TraceReducer
    encoder: EventEncoder
    bus: RunEventBus
    persistence: RunPersistence | None
    metrics: MetricsRegistry | None
    started_monotonic: float
    settlement_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    terminal_settled: bool = False
    terminal_emitted: bool = False
    text_message_started: bool = False
    text_message_ended: bool = False
    metrics_recorded: bool = False
    answer_streamed: bool = False
    answer_tokens_streamed: bool = False
    terminal_save_task: asyncio.Task[bool] | None = None
    engine_task: asyncio.Task[AgentRunResult] | None = None
    failed_artifacts: set[str] = field(default_factory=set)

    def emit(self, event: BaseEvent) -> str:
        encoded = self.encoder.encode(event)
        if isinstance(event, TextMessageStartEvent):
            self.text_message_started = True
        elif isinstance(event, TextMessageEndEvent):
            self.text_message_ended = True
        elif isinstance(event, (RunFinishedEvent, RunErrorEvent)):
            self.terminal_emitted = True
        return encoded

    def record_terminal_metrics(self, *, error: bool) -> None:
        if self.metrics is None or self.metrics_recorded:
            return
        self.metrics_recorded = True
        elapsed_ms = (asyncio.get_running_loop().time() - self.started_monotonic) * 1000
        self.metrics.observe("agent_run_duration_ms", elapsed_ms)
        if error:
            self.metrics.incr("agent_run_errors_total")

    def log_terminal(
        self,
        message: str,
        *,
        level: int,
        termination_reason: str | None,
    ) -> None:
        """Log bounded run diagnostics without history or provider data."""
        logger.log(
            level,
            message,
            self.run_id,
            self.thread_id,
            extra={
                "tool_call_count": self.reducer.tool_call_count,
                "termination_reason": termination_reason,
                "forced_submit": termination_reason == "forced_submit",
            },
        )

    def complete_public_state(
        self, result: AgentRunResult, *, cancelled: bool = False
    ) -> list[dict[str, object]]:
        """Finish the public reducer even if a mapper/reducer hook fails."""
        try:
            if cancelled:
                return self.reducer.cancel_run(result)
            return self.reducer.complete_run(result)
        except Exception:
            logger.exception(
                "public state reducer failed (thread %s, run %s)",
                self.thread_id,
                self.run_id,
            )
            self.reducer.record_terminal_fallback(result)
            return []

    def save_outcome(self, settled: bool) -> list[dict[str, Any]]:
        status = "saved" if settled and self.persistence else "failed"
        return self.reducer.set_save_status(status)

    def record_tool_metrics(self, event: DomainEvent) -> None:
        if not self.metrics:
            return
        if isinstance(event, ToolCompleted):
            self.metrics.incr("agent_tool_calls_total")
            self.metrics.observe("agent_tool_duration_ms", event.duration_ms)
        elif isinstance(event, ToolFailed):
            self.metrics.incr("agent_tool_calls_total")
            self.metrics.incr("agent_tool_errors_total")
            self.metrics.observe("agent_tool_duration_ms", event.duration_ms)

    async def persist_domain_event(self, event: DomainEvent) -> DomainEvent:
        if (
            isinstance(event, ArtifactReady)
            and event.artifact.id in self.failed_artifacts
        ):
            return ArtifactFailed(
                artifact_id=event.artifact.id,
                name=event.artifact.name,
                media_type=event.artifact.media_type,
            )
        if self.persistence and isinstance(
            event,
            (SourceDiscovered, ArtifactStarted, ArtifactReady, ArtifactFailed),
        ):
            try:
                await self.persistence.record_domain_event(
                    event, thread_id=self.thread_id, run_id=self.run_id
                )
            except Exception as exc:
                logger.error(
                    "resource persistence failed (exception_type=%s)",
                    type(exc).__name__,
                )
                if isinstance(event, (ArtifactStarted, ArtifactReady)):
                    self.failed_artifacts.add(event.artifact.id)
                    failed_event = ArtifactFailed(
                        artifact_id=event.artifact.id,
                        name=event.artifact.name,
                        media_type=event.artifact.media_type,
                    )
                    if isinstance(event, ArtifactReady):
                        # Mark an already-created Artifact row as failed rather
                        # than leaving it stuck in pending/started status.
                        try:
                            await self.persistence.record_domain_event(
                                failed_event,
                                thread_id=self.thread_id,
                                run_id=self.run_id,
                            )
                        except Exception as mark_exc:
                            logger.error(
                                "artifact failure marking failed (exception_type=%s)",
                                type(mark_exc).__name__,
                            )
                    return failed_event
        return event

    def start_engine(
        self,
        *,
        engine_builder: EngineBuilder,
        input_data: RunAgentInput,
        continuation_history: Any | None,
        provider_override: ProviderOverride | None,
        approved: frozenset[str] | None,
    ) -> asyncio.Task[AgentRunResult]:
        context = AgentRunContext(
            thread_id=self.thread_id,
            run_id=self.run_id,
            assistant_message_id=self.assistant_message_id,
        )
        engine = engine_builder(
            self.bus,
            thread_id=self.thread_id,
            provider_override=provider_override,
            approved=approved,
        )
        stream_factory = getattr(engine, "stream", None)
        user_request = last_user_text(input_data)
        if callable(stream_factory):
            task = asyncio.create_task(
                _pump_stream(
                    stream_factory,
                    bus=self.bus,
                    user_request=user_request,
                    history=continuation_history,
                    context=context,
                )
            )
        else:
            task = asyncio.create_task(
                engine.run(
                    user_request=user_request,
                    history=continuation_history,
                    context=context,
                )
            )
        task.add_done_callback(lambda _task: self.bus.close_from_loop())
        self.engine_task = task
        return task

    def start_terminal_save(self, result: AgentRunResult) -> None:
        if not self.persistence:
            return
        persistence = self.persistence
        snapshot = self.reducer.snapshot_for_persistence(save_status="saved")

        def _persist_terminal() -> Awaitable[bool | None]:
            if result.status == "completed":
                return persistence.run_completed(
                    thread_id=self.thread_id,
                    run_id=self.run_id,
                    result=result,
                    state_json=snapshot,
                    assistant_message_id=self.assistant_message_id,
                )
            return persistence.run_failed(
                thread_id=self.thread_id,
                run_id=self.run_id,
                result=result,
                state_json=snapshot,
            )

        self.terminal_save_task = asyncio.create_task(
            _settle_with_retry(_persist_terminal)
        )

    async def await_terminal_save(self) -> bool:
        if self.terminal_save_task is None:
            return False
        return await _finish_terminal(self.terminal_save_task)

    async def cancel_engine_task(self) -> None:
        self.bus.cancel_token.cancel()
        await _cancel_task_bounded(
            self.engine_task,
            label="engine",
            thread_id=self.thread_id,
            run_id=self.run_id,
        )

    async def settle_cancelled(self) -> bool:
        """Settle a cancelled agent run and record its terminal state."""
        async with self.settlement_lock:
            if self.terminal_settled:
                return False
            cancel_result = AgentRunResult(
                status="failed",
                answer=None,
                process_summary="The agent run was cancelled.",
                termination_reason="cancelled",
                error_code="run_cancelled",
            )
            self.complete_public_state(cancel_result, cancelled=True)
            settled = (
                await _settle_with_retry(
                    lambda: self.persistence.run_cancelled(  # type: ignore[union-attr]
                        thread_id=self.thread_id,
                        run_id=self.run_id,
                        state_json=self.reducer.snapshot_for_persistence(
                            save_status="saved"
                        ),
                    )
                )
                if self.persistence
                else True
            )
            self.save_outcome(settled)
            # A failed second retry is logged by _settle_with_retry, but this
            # generator must still stop rather than racing another terminal
            # event into the same run.
            self.terminal_settled = True
            self.record_terminal_metrics(error=True)
            self.log_terminal(
                "run %s cancelled (thread %s)",
                level=logging.INFO,
                termination_reason=cancel_result.termination_reason,
            )
            return settled

    async def settle_cancelled_bounded(self) -> bool:
        """Settles cancellation within a bounded interval."""
        task = asyncio.create_task(self.settle_cancelled())
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
                self.thread_id,
                self.run_id,
            )
            return False

    async def cleanup_on_abort(self) -> None:
        self.bus.cancel_token.cancel()
        if self.terminal_save_task is not None and not self.terminal_save_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self.terminal_save_task), timeout=5
                )
            except TimeoutError:
                self.terminal_save_task.cancel()
                await asyncio.gather(self.terminal_save_task, return_exceptions=True)
        await self.cancel_engine_task()
        if not self.terminal_emitted:
            try:
                await self.settle_cancelled_bounded()
            except Exception:
                logger.exception(
                    "could not persist cancellation (thread %s, run %s)",
                    self.thread_id,
                    self.run_id,
                )

    async def record_unexpected_failure(
        self, exc: Exception
    ) -> tuple[str, str, list[dict[str, Any]] | None]:
        code, message = _code_for_exception(exc)
        if code == "provider_request_rejected":
            message = f"{message} Run ID: {self.run_id}."
        if self.terminal_settled:
            if (
                self.terminal_save_task is not None
                and not self.terminal_save_task.done()
            ):
                self.terminal_save_task.add_done_callback(_consume_task_exception)
            self.record_terminal_metrics(error=True)
            return code, message, None

        failure = AgentRunResult(
            status="failed",
            answer=None,
            process_summary="The agent run failed before producing a response.",
            termination_reason="failed",
            error_code=code,
        )
        logger.error(
            "live run failed (thread %s, run %s, exception_type=%s)",
            self.thread_id,
            self.run_id,
            type(exc).__name__,
        )
        delta = self.complete_public_state(failure)
        settled = True
        if self.persistence:
            try:
                persistence = self.persistence
                settled = await _settle_terminal(
                    lambda: persistence.run_failed(
                        thread_id=self.thread_id,
                        run_id=self.run_id,
                        result=failure,
                        state_json=self.reducer.snapshot_for_persistence(
                            save_status="saved"
                        ),
                    )
                )
            except Exception as persist_exc:
                # Keep the fallback terminal event safe even if a custom
                # persistence implementation escapes the retry wrapper.
                logger.error(
                    "could not persist unexpected failure "
                    "(thread %s, run %s, exception_type=%s)",
                    self.thread_id,
                    self.run_id,
                    type(persist_exc).__name__,
                )
                settled = False
        delta.extend(self.save_outcome(settled))
        if not settled:
            logger.error(
                "unexpected terminal failure could not be persisted "
                "(thread %s, run %s)",
                self.thread_id,
                self.run_id,
            )
        self.terminal_settled = True
        self.record_terminal_metrics(error=True)
        self.log_terminal(
            "run %s ended with an unexpected failure (thread %s)",
            level=logging.ERROR,
            termination_reason=failure.termination_reason,
        )
        return code, message, delta


class LiveDSPyCoordinator:
    async def stream(
        self,
        *,
        input_data: RunAgentInput,
        engine_builder: EngineBuilder,
        accept: str | None,
        is_disconnected: Callable[[], Awaitable[bool]],
        provider_override: ProviderOverride | None = None,
        persistence: RunPersistence | None = None,
        reserved_run: Run | None = None,
        run_timeout_s: float = 300.0,
        metrics: MetricsRegistry | None = None,
    ) -> AsyncIterator[str]:
        """Stream an agent run as encoded AG-UI events."""
        encoder = EventEncoder(accept=accept or "")
        # Approval is decided before the run starts: gated tools are withheld
        # unless this request authorized them (see app/agent/approval.py).
        approved = approved_tool_names(input_data.forwarded_props)
        thread_id = input_data.thread_id
        run_id = input_data.run_id
        loop = asyncio.get_running_loop()
        bus = RunEventBus(loop)

        run = reserved_run
        if run is None and persistence is not None:
            run = await persistence.get_run(run_id)
            if run is None:
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
        if metrics:
            metrics.incr("agent_runs_total")

        session = _LiveRunSession(
            thread_id=thread_id,
            run_id=run_id,
            assistant_message_id=f"msg-{run_id}",
            reducer=reducer,
            encoder=encoder,
            bus=bus,
            persistence=persistence,
            metrics=metrics,
            started_monotonic=loop.time(),
        )

        try:
            if persistence:
                await persistence.mark_running(run_id=run_id, state_json=reducer.state)
            if await is_disconnected():
                await session.settle_cancelled_bounded()
                return

            yield session.emit(RunStartedEvent(thread_id=thread_id, run_id=run_id))
            yield session.emit(
                TextMessageStartEvent(
                    message_id=session.assistant_message_id,
                    role="assistant",
                )
            )
            yield session.emit(StateSnapshotEvent(snapshot=reducer.state))
            logger.info("run %s started (thread %s)", run_id, thread_id)

            continuation_history = (
                await persistence.get_continuation_history(thread_id, continuation_head)
                if persistence
                else None
            )
            if continuation_history is None and len(input_data.messages) > 1:
                continuation_history = history_from_agui_messages(
                    input_data.messages[:-1]
                )
            yield session.emit(StateDeltaEvent(delta=reducer.begin()))

            engine_task = session.start_engine(
                engine_builder=engine_builder,
                input_data=input_data,
                continuation_history=continuation_history,
                provider_override=provider_override,
                approved=approved,
            )

            try:
                # This timeout covers event draining and the final engine wait.
                async with asyncio.timeout(run_timeout_s):
                    while True:
                        if await is_disconnected():
                            await session.cancel_engine_task()
                            await session.settle_cancelled_bounded()
                            return
                        event = await bus.next()
                        if event is DONE:
                            break
                        if (
                            isinstance(event, SynthesisTokenDelta)
                            and event.field == "answer"
                        ):
                            # Tokens streamed the answer text incrementally;
                            # final fields must not duplicate it as chunks.
                            session.answer_streamed = True
                            session.answer_tokens_streamed = True
                        if isinstance(event, FinalFieldsReady) and event.answer:
                            session.answer_streamed = True
                        event = await session.persist_domain_event(event)  # type: ignore[arg-type]
                        agui_events = map_domain_event(
                            event,  # type: ignore[arg-type]
                            assistant_message_id=session.assistant_message_id,
                            reducer=reducer,
                            emit_answer_text=not session.answer_tokens_streamed,
                        )
                        session.record_tool_metrics(event)
                        for agui_event in agui_events:
                            yield session.emit(agui_event)
                    result = await engine_task
            except TimeoutError:
                await session.cancel_engine_task()
                result = AgentRunResult(
                    status="failed",
                    answer=None,
                    process_summary="The agent run timed out.",
                    termination_reason="timeout",
                    error_code="agent_timeout",
                )

            delta = session.complete_public_state(result)
            session.start_terminal_save(result)
            session.terminal_settled = True

            yield session.emit(StateDeltaEvent(delta=delta))
            if result.status == "completed" and not session.answer_streamed:
                for chunk in chunk_text(result.answer or ""):
                    yield session.emit(
                        TextMessageContentEvent(
                            message_id=session.assistant_message_id, delta=chunk
                        )
                    )
            yield session.emit(
                TextMessageEndEvent(message_id=session.assistant_message_id)
            )
            settled = await session.await_terminal_save()
            yield session.emit(StateDeltaEvent(delta=session.save_outcome(settled)))
            if not settled and persistence:
                logger.error(
                    "%s run could not be persisted (thread %s, run %s)",
                    "completed" if result.status == "completed" else "failed",
                    thread_id,
                    run_id,
                )

            if result.status == "completed":
                session.record_terminal_metrics(error=False)
                session.log_terminal(
                    "run %s completed (thread %s)",
                    level=logging.INFO,
                    termination_reason=result.termination_reason,
                )
                yield session.emit(RunFinishedEvent(thread_id=thread_id, run_id=run_id))
            else:
                code, message = public_error(result.error_code, "agent_no_output")
                logger.warning(
                    "run %s failed [%s] (thread %s)",
                    run_id,
                    code,
                    thread_id,
                    extra={
                        "tool_call_count": reducer.tool_call_count,
                        "termination_reason": result.termination_reason,
                        "forced_submit": result.termination_reason == "forced_submit",
                    },
                )
                session.record_terminal_metrics(error=True)
                yield session.emit(RunErrorEvent(message=message, code=code))

        except (asyncio.CancelledError, GeneratorExit):
            await session.cleanup_on_abort()
            raise
        except Exception as exc:
            if session.terminal_emitted:
                raise
            code, message, fallback_delta = await session.record_unexpected_failure(exc)
            if fallback_delta is not None:
                yield session.emit(StateDeltaEvent(delta=fallback_delta))
            if session.text_message_started and not session.text_message_ended:
                yield session.emit(
                    TextMessageEndEvent(message_id=session.assistant_message_id)
                )
            yield session.emit(RunErrorEvent(message=message, code=code))


async def _settle_terminal(operation: Callable[[], Awaitable[bool | None]]) -> bool:
    """Finish accepted terminal persistence despite a disconnected client."""
    return await _finish_terminal(asyncio.create_task(_settle_with_retry(operation)))


async def _finish_terminal(task: asyncio.Task[bool]) -> bool:
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        raise


async def _settle_with_retry(
    operation: Callable[[], Awaitable[bool | None]],
) -> bool:
    """Retry one lifecycle write with a fresh session after rollback."""

    for attempt in range(2):
        try:
            result = await operation()
            return result is not False
        except Exception as exc:
            if attempt == 0:
                logger.warning(
                    "terminal persistence failed; retrying with a fresh session "
                    "(exception_type=%s)",
                    type(exc).__name__,
                )
            else:
                logger.error(
                    "terminal persistence failed after retry (exception_type=%s)",
                    type(exc).__name__,
                )
    return False


def _flatten_exception_group(
    group: BaseExceptionGroup[BaseException],
) -> list[BaseException]:
    """Flatten nested exception groups into their leaf exceptions.

    ``dspy.streamify`` runs a program inside an anyio task group, so a failure
    from a provider can reach this boundary wrapped rather than bare.
    """
    flat: list[BaseException] = []
    for exc in group.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            flat.extend(_flatten_exception_group(exc))
        else:
            flat.append(exc)
    return flat


def _code_for_exception(exc: Exception) -> tuple[str, str]:
    leaves: list[BaseException]
    if isinstance(exc, BaseExceptionGroup):
        leaves = _flatten_exception_group(exc)
    else:
        leaves = [exc]
    text = " ".join(f"{type(item).__name__} {item}" for item in leaves).lower()
    if any(isinstance(item, LMAuthError) for item in leaves) or "lmautherror" in text:
        return public_error("provider_unauthorized")
    if (
        any(isinstance(item, LMRateLimitError) for item in leaves)
        or "rate limit" in text
        or "ratelimit" in text
        or "429" in text
    ):
        return public_error("rate_limited")
    if any(isinstance(item, LMInvalidRequestError) for item in leaves):
        return public_error("provider_request_rejected")
    return public_error("internal_error")
