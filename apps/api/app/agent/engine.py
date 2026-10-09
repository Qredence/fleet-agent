"""Provider-independent runtime boundary for a first-class DSPy program.

FastAPI routes depend on ``AgentEngine.run()`` and ``AgentRunResult``. They do
not know whether the program uses ReActV2, a compiled FleetAgent, or another
DSPy Module. Raw ``dspy.History`` stays server-side because it may contain
``next_thought`` and tool observations.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Literal, Protocol

import anyio
import dspy
from dspy.streaming import StreamListener
from dspy.streaming.messages import StreamResponse
from dspy.utils.callback import BaseCallback
from dspy.utils.exceptions import AdapterParseError, ContextWindowExceededError

from app.agent.event_bus import RunEventBus
from app.agent.provider import ProviderOverride
from app.kernel.content_safety import (
    StreamingScrubber,
    scrub_public_lines,
    scrub_public_text,
)

logger = logging.getLogger(__name__)


class SynthesisStreamListener(StreamListener):  # type: ignore[misc]
    """StreamListener pinned to ChatAdapter field boundaries.

    The synthesis call runs under a scoped ``dspy.context(adapter=ChatAdapter())``
    inside the program's worker thread (ChatAdapter's ``[[ ## field ## ]]``
    sections give exact, boilerplate-free boundaries). The stream consumer task
    that calls ``receive`` runs on the event loop and cannot see that
    thread-local scope, so the adapter is pinned here explicitly: otherwise the
    listener would parse ChatAdapter sections with the ambient JSONAdapter's
    identifiers and never detect a field boundary.
    """

    def receive(self, chunk: Any) -> Any:
        with dspy.context(adapter=dspy.ChatAdapter()):
            return super().receive(chunk)


def synthesis_stream_listeners(fields: Sequence[str]) -> list[SynthesisStreamListener]:
    """Build one pinned listener per synthesis output field."""
    return [SynthesisStreamListener(signature_field_name=field) for field in fields]


@dataclass(frozen=True)
class AgentRunContext:
    thread_id: str
    run_id: str
    assistant_message_id: str | None = None


@dataclass(frozen=True)
class AgentRunResult:
    status: Literal["completed", "failed"]
    answer: str | None
    process_summary: str | None
    key_decisions: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    termination_reason: str | None = None
    error_code: str | None = None
    evidence_status: Literal["complete", "partial", "insufficient"] | None = None
    evidence_reason: str | None = None
    output_intent: str = "none"
    # Server-side only. Never serialize this field to the browser.
    history: Any | None = None
    usage: dict[str, int] = field(default_factory=dict)


class AgentEngine(Protocol):
    async def run(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AgentRunResult: ...


class EngineBuilder(Protocol):
    """Build contract for one run-scoped engine.

    Declared here, beside the engine it produces, so the transport layer depends
    on the agent rather than the two importing each other.
    """

    def __call__(
        self,
        bus: RunEventBus,
        *,
        thread_id: str,
        provider_override: ProviderOverride | None = None,
        approved: frozenset[str] | None = None,
    ) -> AgentEngine: ...


class DspyProgram(Protocol):
    """Minimal callable contract implemented by FleetAgent and DSPy Modules."""

    def __call__(
        self,
        *,
        user_request: str,
        history: Any | None,
    ) -> dspy.Prediction: ...


ProgramFactory = Callable[[], DspyProgram]


def compose_callbacks(
    program: DspyProgram,
    engine_callbacks: list[BaseCallback],
) -> list[BaseCallback]:
    """Return DSPy's active callbacks extended with the engine's own.

    ``dspy.context(callbacks=...)`` REPLACES ``dspy.settings.callbacks`` instead of
    extending it (``dspy/utils/callback.py``). The opt-in metadata tracer installs its
    callback into that global list, so passing only the engine's callbacks silently
    disabled tracing on every live run while leaving offline runs traced. Compose
    instead of replace.
    """
    return [*list(dspy.settings.callbacks), *engine_callbacks]


@dataclass(frozen=True)
class AgentStreamUpdate:
    """Public incremental updates followed by the authoritative run result.

    ``token`` updates stream synthesis fields incrementally (DSPy-native via
    ``dspy.streamify`` listeners); ``final_fields`` carries the settled,
    scrubbed public fields; ``result`` is authoritative and always last.
    """

    kind: Literal["final_fields", "result", "token"]
    answer: str | None = None
    process_summary: str | None = None
    result: AgentRunResult | None = None
    stream_field: str | None = None
    delta: str | None = None


_REASON_TO_PUBLIC_CODE = {
    "max_iters": "agent_no_output",
    "empty_tool_calls": "agent_no_output",
    "failed": "agent_no_output",
    "parse_error": "agent_parse_error",
    "context_window_exceeded": "agent_context_limit",
}


_FORCED_SUBMIT_REASON_RE = re.compile(
    r"ReActV2 failed to produce final outputs after (?P<reason>\w+):"
)


def _reason_from_react_exc(exc: BaseException) -> str | None:
    """Extract the public termination_reason from a DSPy 3.4 forced-submit raise."""
    if isinstance(exc, ContextWindowExceededError):
        return "context_window_exceeded"
    if isinstance(exc, AdapterParseError):
        return "parse_error"
    if isinstance(exc, ValueError):
        match = _FORCED_SUBMIT_REASON_RE.search(str(exc))
        return match.group("reason") if match else None
    return None


def _capture_history(history: Any) -> dspy.History:
    """Return a ``dspy.History`` the program will mutate in place.

    ReActV2's loop appends each turn to the ``dspy.History`` object it was
    passed without ever copying it, so the engine keeps a handle it can read
    when a failure escapes the program's own boundary handling — the same
    partial history the old engine-side monkeypatch preserved, now through
    DSPy's public semantics only.
    """
    return history if isinstance(history, dspy.History) else dspy.History(messages=[])


def _map_react_raise(
    exc: BaseException, captured: dspy.History | None = None
) -> AgentRunResult | None:
    """Map a ReActV2 raise that escaped the program into a public failure."""
    reason = _reason_from_react_exc(exc)
    if reason is None:
        return None
    return AgentRunResult(
        status="failed",
        answer=None,
        process_summary=None,
        termination_reason=reason,
        error_code=_REASON_TO_PUBLIC_CODE.get(reason, "agent_no_output"),
        history=captured,
    )


_FORCED_SUBMIT_CAVEAT = (
    "The agent was stopped before completing its process; "
    "the answer was summarized from partial progress and may be incomplete."
)


def _map_result(prediction: dspy.Prediction) -> AgentRunResult:
    reason = getattr(prediction, "termination_reason", None)
    answer = getattr(prediction, "answer", None) or None

    usage: dict[str, int] = {}
    for model_usage in (prediction.get_lm_usage() or {}).values():
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            usage[key] = usage.get(key, 0) + int(model_usage.get(key) or 0)

    if answer is not None:
        caveats = list(getattr(prediction, "caveats", None) or [])
        if reason == "forced_submit" and _FORCED_SUBMIT_CAVEAT not in caveats:
            caveats.append(_FORCED_SUBMIT_CAVEAT)
        return AgentRunResult(
            status="completed",
            answer=scrub_public_text(answer),
            process_summary=scrub_public_text(
                getattr(prediction, "process_summary", None) or ""
            )
            or None,
            key_decisions=scrub_public_lines(
                list(getattr(prediction, "key_decisions", None) or [])
            ),
            caveats=scrub_public_lines(caveats),
            termination_reason=reason,
            history=getattr(prediction, "history", None),
            usage=usage,
            evidence_status=getattr(prediction, "evidence_status", None),
            evidence_reason=getattr(prediction, "evidence_reason", None),
            output_intent=getattr(prediction, "output_intent", "none"),
        )

    return AgentRunResult(
        status="failed",
        answer=None,
        process_summary=None,
        termination_reason=reason,
        error_code=_REASON_TO_PUBLIC_CODE.get(reason or "", "agent_no_output"),
        history=getattr(prediction, "history", None),
        usage=usage,
    )


class _ThreadedProgram(dspy.Module):  # type: ignore[misc]
    """Expose predictors while keeping cancellation outside the worker lifetime."""

    def __init__(self, program: DspyProgram) -> None:
        super().__init__()
        self.program = program

    async def acall(self, **kwargs: Any) -> dspy.Prediction:
        with anyio.CancelScope(shield=True):
            return await anyio.to_thread.run_sync(
                partial(self.program, **kwargs), abandon_on_cancel=False
            )


class DspyAgentEngine:
    """Runs an application-owned DSPy program under a scoped DSPy context."""

    def __init__(
        self,
        *,
        program_factory: ProgramFactory,
        lm: dspy.BaseLM,
        adapter: dspy.Adapter | None = None,
        callbacks: list[BaseCallback] | None = None,
        cleanup: Callable[[], None] | None = None,
        export_report: Callable[[AgentRunContext, AgentRunResult], None] | None = None,
    ) -> None:
        self._program_factory = program_factory
        self._lm = lm
        self._adapter = adapter
        self._callbacks = list(callbacks or [])
        self._cleanup = cleanup
        self._export_report = export_report

    async def run(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AgentRunResult:
        return await anyio.to_thread.run_sync(
            self._run_sync, user_request, history, context, abandon_on_cancel=False
        )

    async def stream(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AsyncIterator[AgentStreamUpdate]:
        """Emit streamed synthesis fields, then the authoritative result.

        Programs that expose ``synthesis_stream_fields`` (the routed program)
        stream their public answer/summary fields token-by-token through
        ``dspy.streamify``; every other program falls back to the settled
        ``final_fields`` + ``result`` pair.  This deliberately avoids
        accessing ``program.react.tools['submit']``: the AG-UI contract stays
        unchanged while the DSPy program remains a black box to the runtime.
        """
        try:
            program = self._program_factory()
        except BaseException:
            self._close_resources()
            raise
        stream_fields = getattr(program, "synthesis_stream_fields", None)
        if not stream_fields:
            result = await anyio.to_thread.run_sync(
                self._run_sync_with_program,
                program,
                user_request,
                history,
                context,
            )
            if result.answer is not None or result.process_summary is not None:
                yield AgentStreamUpdate(
                    kind="final_fields",
                    answer=result.answer,
                    process_summary=result.process_summary,
                )
            yield AgentStreamUpdate(kind="result", result=result)
            return

        try:
            captured = _capture_history(history)
            scrubbers = {
                field_name: StreamingScrubber() for field_name in stream_fields
            }
            callbacks = compose_callbacks(program, self._callbacks)
            prediction: dspy.Prediction | None = None
            try:
                with dspy.context(
                    lm=self._lm,
                    adapter=self._adapter,
                    callbacks=callbacks,
                    track_usage=True,
                ):
                    streamer = dspy.streamify(
                        _ThreadedProgram(program),
                        is_async_program=True,
                        stream_listeners=synthesis_stream_listeners(stream_fields),
                        include_final_prediction_in_output_stream=True,
                    )
                    async with aclosing(
                        streamer(user_request=user_request, history=captured)
                    ) as stream:
                        async for value in stream:
                            if isinstance(value, dspy.Prediction):
                                prediction = value
                            elif isinstance(value, StreamResponse):
                                scrubber = scrubbers.get(value.signature_field_name)
                                if scrubber is None:
                                    continue
                                safe_delta = scrubber.push(value.chunk or "")
                                if safe_delta:
                                    yield AgentStreamUpdate(
                                        kind="token",
                                        stream_field=value.signature_field_name,
                                        delta=safe_delta,
                                    )
            except BaseException as exc:
                # streamify can surface a worker's error while its task group
                # unwinds cancellation. The worker has finished at this point;
                # preserve cancellation before mapping any provider failure.
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise asyncio.CancelledError from None
                mapped = _map_react_raise(exc, captured)
                if mapped is None:
                    raise
                result = mapped
            else:
                # End of stream: release the scrubbers' held-back tails so the
                # streamed text is complete before the settled fields arrive.
                for field_name, scrubber in scrubbers.items():
                    tail = scrubber.flush()
                    if tail:
                        yield AgentStreamUpdate(
                            kind="token", stream_field=field_name, delta=tail
                        )
                if prediction is None:
                    raise RuntimeError("streaming program ended without a prediction")
                result = _map_result(prediction)
                if (
                    self._export_report
                    and result.output_intent == "managed_report"
                    and result.answer
                ):
                    await asyncio.to_thread(self._export_report, context, result)
        finally:
            self._close_resources()

        if result.answer is not None or result.process_summary is not None:
            yield AgentStreamUpdate(
                kind="final_fields",
                answer=result.answer,
                process_summary=result.process_summary,
            )
        yield AgentStreamUpdate(kind="result", result=result)

    def _run_sync(
        self,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AgentRunResult:
        return self._run_sync_with_program(None, user_request, history, context)

    def _run_sync_with_program(
        self,
        program: DspyProgram | None,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AgentRunResult:
        try:
            program = program or self._program_factory()
            captured = _capture_history(history)
            callbacks = compose_callbacks(program, self._callbacks)
            with dspy.context(
                lm=self._lm,
                adapter=self._adapter,
                callbacks=callbacks,
                track_usage=True,
            ):
                # Invoke the Module through __call__, never forward(), so DSPy
                # usage tracking, callbacks, caller-module context, and future
                # optimizer/runtime hooks remain active.
                try:
                    prediction = program(user_request=user_request, history=captured)
                except (
                    ValueError,
                    AdapterParseError,
                    ContextWindowExceededError,
                ) as exc:
                    mapped = _map_react_raise(exc, captured)
                    if mapped is None:
                        raise
                    return mapped
            result = _map_result(prediction)
            if (
                self._export_report
                and result.output_intent == "managed_report"
                and result.answer
            ):
                self._export_report(context, result)
            return result
        finally:
            self._close_resources()

    def _close_resources(self) -> None:
        cleanup, self._cleanup = self._cleanup, None
        if cleanup is not None:
            try:
                cleanup()
            except Exception:
                logger.exception("agent run resource cleanup failed")
