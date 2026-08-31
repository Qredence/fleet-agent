"""Provider-independent runtime boundary for a first-class DSPy program.

FastAPI routes depend on ``AgentEngine.run()`` and ``AgentRunResult``. They do
not know whether the program uses ReActV2, a compiled FleetAgent, or another
DSPy Module. Raw ``dspy.History`` stays server-side because it may contain
``next_thought`` and tool observations.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import dspy
from ag_ui.core import Interrupt, ResumeEntry
from dspy.streaming.messages import StreamResponse
from dspy.utils.callback import BaseCallback

from app.agent.approval import (
    APPROVAL_REGISTRY,
    ApprovalContext,
    ApprovalDecisionError,
    ApprovalPause,
    ApprovalRegistryProtocol,
    ToolLifecycle,
    reset_approval_context,
    set_approval_context,
)
from app.agent.provider import ProviderOverride
from app.agent.synthesis_stream import synthesis_stream_listeners
from app.agui.cancel_token import RunCancelToken
from app.services.content_safety import (
    StreamingScrubber,
    scrub_public_lines,
    scrub_public_text,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentRunContext:
    thread_id: str
    run_id: str
    assistant_message_id: str | None = None


@dataclass(frozen=True)
class AgentRunResult:
    status: Literal["completed", "failed", "interrupted"]
    answer: str | None
    process_summary: str | None
    key_decisions: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    termination_reason: str | None = None
    error_code: str | None = None
    # Server-side only. Never serialize this field to the browser.
    history: Any | None = None
    usage: dict[str, int] = field(default_factory=dict)
    interrupts: list[Interrupt] = field(default_factory=list)


class AgentEngine(Protocol):
    async def run(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
        resume: list[ResumeEntry] | None = None,
    ) -> AgentRunResult: ...


class DspyProgram(Protocol):
    """Minimal callable contract implemented by FleetAgent and DSPy Modules."""

    def __call__(
        self,
        *,
        user_request: str,
        history: Any | None,
    ) -> dspy.Prediction: ...


ProgramFactory = Callable[[], DspyProgram]


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

_FORCED_SUBMIT_CAVEAT = (
    "The agent was stopped before completing its process; "
    "the answer was summarized from partial progress and may be incomplete."
)


def _flatten_exception_group(
    group: BaseExceptionGroup[BaseException],
) -> list[BaseException]:
    """Flatten nested exception groups into their leaf exceptions."""
    flat: list[BaseException] = []
    for exc in group.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            flat.extend(_flatten_exception_group(exc))
        else:
            flat.append(exc)
    return flat


def _approval_result_from_exceptions(
    exceptions: list[BaseException],
) -> AgentRunResult | None:
    """Map approval signals escaping a task group; None re-raises the rest.

    ``dspy.streamify`` executes the program inside an anyio task group, so a
    pause (or an approval-validation failure) raised in the worker thread
    reaches this boundary wrapped in an exception group rather than bare. Any
    non-approval exception means the run failed for its own reason and must
    keep propagating.
    """
    pause = next((exc for exc in exceptions if isinstance(exc, ApprovalPause)), None)
    decision = next(
        (exc for exc in exceptions if isinstance(exc, ApprovalDecisionError)), None
    )
    unrelated = [
        exc
        for exc in exceptions
        if not isinstance(exc, (ApprovalPause, ApprovalDecisionError))
    ]
    if unrelated or (pause is None and decision is None):
        return None
    if pause is not None:
        return AgentRunResult(
            status="interrupted",
            answer=None,
            process_summary=(
                "The agent is waiting for approval before running an action."
            ),
            termination_reason="approval_required",
            interrupts=[pause.interrupt],
        )
    assert decision is not None
    return AgentRunResult(
        status="failed",
        answer=None,
        process_summary="The approval response could not be applied.",
        termination_reason=decision.code,
        error_code=decision.code,
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
        approval_registry: ApprovalRegistryProtocol | None = None,
        provider_override: ProviderOverride | None = None,
        lifecycle: ToolLifecycle | None = None,
        cancel_token: RunCancelToken | None = None,
    ) -> None:
        self._program_factory = program_factory
        self._lm = lm
        self._adapter = adapter
        self._callbacks = list(callbacks or [])
        self._cleanup = cleanup
        self._approval_registry = approval_registry or APPROVAL_REGISTRY
        self._provider_binding = (
            provider_override.fingerprint if provider_override is not None else "server"
        )
        self._lifecycle = lifecycle
        self._cancel_token = cancel_token

    async def run(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
        resume: list[ResumeEntry] | None = None,
    ) -> AgentRunResult:
        return await asyncio.to_thread(
            self._run_sync, user_request, history, context, resume
        )

    async def stream(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
        resume: list[ResumeEntry] | None = None,
    ) -> AsyncIterator[AgentStreamUpdate]:
        """Emit streamed synthesis fields, then the authoritative result.

        Programs that expose ``synthesis_stream_fields`` (the routed program)
        stream their public answer/summary fields token-by-token through
        ``dspy.streamify``; every other program falls back to the settled
        ``final_fields`` + ``result`` pair.  This deliberately avoids
        accessing ``program.react.tools['submit']``: the AG-UI contract stays
        unchanged while the DSPy program remains a black box to the runtime.
        """
        program = self._program_factory()
        stream_fields = getattr(program, "synthesis_stream_fields", None)
        if not stream_fields:
            result = await asyncio.to_thread(
                self._run_sync_with_program,
                program,
                user_request,
                history,
                context,
                resume,
            )
            if result.answer is not None or result.process_summary is not None:
                yield AgentStreamUpdate(
                    kind="final_fields",
                    answer=result.answer,
                    process_summary=result.process_summary,
                )
            yield AgentStreamUpdate(kind="result", result=result)
            return

        scrubbers = {field_name: StreamingScrubber() for field_name in stream_fields}
        approval_context = ApprovalContext(
            thread_id=context.thread_id,
            run_id=context.run_id,
            provider_binding=self._provider_binding,
            registry=self._approval_registry,
            lifecycle=self._lifecycle,
            cancel_token=self._cancel_token,
            assistant_message_id=context.assistant_message_id,
        )
        approval_token = set_approval_context(approval_context)
        try:
            # The durable registry bridges DB work onto this loop and must
            # not be called from the loop thread, so resolve off-loop.
            approval_context.resumed = await asyncio.to_thread(
                self._approval_registry.resolve,
                resume,
                thread_id=context.thread_id,
                provider_binding=self._provider_binding,
            )
            if (
                approval_context.resumed is not None
                and approval_context.resumed.checkpoint.assistant_message_id
                != context.assistant_message_id
            ):
                # The visible assistant message is the public binding for the
                # hidden checkpoint.  A resume from another branch (or a
                # forged/replayed payload without that id) must fail closed.
                raise ApprovalDecisionError("approval_invalid")
            program_history = (
                approval_context.resumed.checkpoint.history
                if approval_context.resumed is not None
                else history
            )
            callbacks = (
                []
                if getattr(program, "application_tool_lifecycle", False)
                else self._callbacks
            )
            prediction: dspy.Prediction | None = None
            with dspy.context(
                lm=self._lm,
                adapter=self._adapter,
                callbacks=callbacks,
                track_usage=True,
            ):
                streamer = dspy.streamify(
                    program,
                    stream_listeners=synthesis_stream_listeners(stream_fields),
                    include_final_prediction_in_output_stream=True,
                )
                async for value in streamer(
                    user_request=user_request, history=program_history
                ):
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
        except ApprovalPause as pause:
            result = AgentRunResult(
                status="interrupted",
                answer=None,
                process_summary=(
                    "The agent is waiting for approval before running an action."
                ),
                termination_reason="approval_required",
                interrupts=[pause.interrupt],
            )
        except ApprovalDecisionError as exc:
            result = AgentRunResult(
                status="failed",
                answer=None,
                process_summary="The approval response could not be applied.",
                termination_reason=exc.code,
                error_code=exc.code,
            )
        except BaseExceptionGroup as group:
            # dspy.streamify runs the program inside an anyio task group, so
            # a pause raised in the worker thread surfaces as an exception
            # group. Map the approval signals; re-raise anything else loudly.
            handled = _approval_result_from_exceptions(_flatten_exception_group(group))
            if handled is None:
                raise
            result = handled
        finally:
            reset_approval_context(approval_token)
            if self._cleanup is not None:
                try:
                    self._cleanup()
                except Exception:
                    logger.exception("agent run resource cleanup failed")

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
        resume: list[ResumeEntry] | None,
    ) -> AgentRunResult:
        return self._run_sync_with_program(None, user_request, history, context, resume)

    def _run_sync_with_program(
        self,
        program: DspyProgram | None,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
        resume: list[ResumeEntry] | None,
    ) -> AgentRunResult:
        approval_context = ApprovalContext(
            thread_id=context.thread_id,
            run_id=context.run_id,
            provider_binding=self._provider_binding,
            registry=self._approval_registry,
            lifecycle=self._lifecycle,
            cancel_token=self._cancel_token,
            assistant_message_id=context.assistant_message_id,
        )
        approval_token = set_approval_context(approval_context)
        try:
            approval_context.resumed = self._approval_registry.resolve(
                resume,
                thread_id=context.thread_id,
                provider_binding=self._provider_binding,
            )
            if (
                approval_context.resumed is not None
                and approval_context.resumed.checkpoint.assistant_message_id
                != context.assistant_message_id
            ):
                # The visible assistant message is the public binding for the
                # hidden checkpoint.  A resume from another branch (or a
                # forged/replayed payload without that id) must fail closed.
                raise ApprovalDecisionError("approval_invalid")
            program = program or self._program_factory()
            callbacks = (
                []
                if getattr(program, "application_tool_lifecycle", False)
                else self._callbacks
            )
            with dspy.context(
                lm=self._lm,
                adapter=self._adapter,
                callbacks=callbacks,
                track_usage=True,
            ):
                # Invoke the Module through __call__, never forward(), so DSPy
                # usage tracking, callbacks, caller-module context, and future
                # optimizer/runtime hooks remain active.
                prediction = program(
                    user_request=user_request,
                    history=(
                        approval_context.resumed.checkpoint.history
                        if approval_context.resumed is not None
                        else history
                    ),
                )
            return _map_result(prediction)
        except ApprovalPause as pause:
            return AgentRunResult(
                status="interrupted",
                answer=None,
                process_summary=(
                    "The agent is waiting for approval before running an action."
                ),
                termination_reason="approval_required",
                interrupts=[pause.interrupt],
            )
        except ApprovalDecisionError as exc:
            return AgentRunResult(
                status="failed",
                answer=None,
                process_summary="The approval response could not be applied.",
                termination_reason=exc.code,
                error_code=exc.code,
            )
        finally:
            reset_approval_context(approval_token)
            if self._cleanup is not None:
                try:
                    self._cleanup()
                except Exception:
                    logger.exception("agent run resource cleanup failed")
