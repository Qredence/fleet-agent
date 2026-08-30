"""Application-owned approval checkpoints for synchronous DSPy tools.

DSPy's ReActV2 catches exceptions raised by tools and turns them into model
observations.  That is useful for ordinary tool failures, but it cannot carry
an interactive approval decision.  This module keeps the pause/resume seam
outside DSPy: the loop checkpoints before the gated call, raises a private
pause signal, and resumes the same hidden turn after AG-UI supplies a boolean
decision.

Only interrupt identity and generic action text leave this module.  The
checkpoint contains the real history and arguments solely in process memory;
it is never serialized, logged, or included in an AgentRunResult.
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import dspy
from ag_ui.core import Interrupt, ResumeEntry
from dspy.predict.react_v2 import (
    AdapterParseError,
    ContextWindowExceededError,
    ToolCallResults,
    ToolCalls,
    _append_history_event,
    _coerce_history,
    _coerce_tool_calls,
    _ensure_tool_call_ids,
    format_error_for_lm,
)

from app.agent.tool_registry import ToolMetadata
from app.agui.cancel_token import RunCancelToken

APPROVAL_TTL_SECONDS = 5 * 60
_EXPIRED_TOMBSTONE_SECONDS = APPROVAL_TTL_SECONDS


class ToolLifecycle(Protocol):
    """The small callback surface needed by the application-owned loop."""

    def on_tool_start(
        self, call_id: str, instance: Any, inputs: dict[str, Any]
    ) -> None: ...

    def on_tool_end(
        self,
        call_id: str,
        outputs: Any | None,
        exception: BaseException | None = None,
    ) -> None: ...

    def resume_tool_end(
        self,
        call_id: str,
        instance: Any,
        outputs: Any | None,
        exception: BaseException | None = None,
    ) -> None: ...


class ApprovalDecisionError(RuntimeError):
    """A resume request cannot be safely applied to a live checkpoint."""

    def __init__(self, code: str) -> None:
        self.code = code
        # Keep the exception text stable and non-sensitive for internal logs.
        super().__init__(code)


class ApprovalDeniedError(RuntimeError):
    """Safe internal marker used to render a denied tool as a failed call."""

    def __init__(self) -> None:
        super().__init__("tool authorization was denied")


class ApprovalPause(RuntimeError):
    """Private control flow signal raised before a gated tool executes."""

    def __init__(self, interrupt: Interrupt) -> None:
        self.interrupt = interrupt
        super().__init__("approval required")


@dataclass(frozen=True)
class ApprovalCheckpoint:
    """Hidden continuation state for one model-generated tool-call batch."""

    profile_name: str
    history: dspy.History
    pending_inputs: dict[str, Any]
    prediction: dspy.Prediction
    tool_calls: ToolCalls
    values: tuple[Any, ...]
    errors: tuple[bool, ...]
    next_index: int
    turn_index: int
    tool_name: str
    tool_call_id: str
    assistant_message_id: str | None


@dataclass(frozen=True)
class _PendingApproval:
    interrupt: Interrupt
    checkpoint: ApprovalCheckpoint
    thread_id: str
    provider_binding: str
    expires_monotonic: float
    expires_at: str


@dataclass(frozen=True)
class ResolvedApproval:
    checkpoint: ApprovalCheckpoint
    approved: bool
    interrupt_id: str


class ApprovalRegistry:
    """Thread-safe, one-time, live-process approval checkpoint registry."""

    def __init__(self, *, ttl_seconds: int = APPROVAL_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError("approval TTL must be positive")
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._pending: dict[str, _PendingApproval] = {}
        self._expired: dict[str, float] = {}

    def create(
        self,
        *,
        checkpoint: ApprovalCheckpoint,
        thread_id: str,
        provider_binding: str,
        action_preview: str,
    ) -> Interrupt:
        """Store a hidden checkpoint and return its safe public interrupt.

        ``action_preview`` is the bounded, single-line description of the
        gated action the approver is deciding on; it is the only sanctioned
        tool-argument text exposed to the browser.
        """

        now = time.monotonic()
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
        interrupt_id = f"approval_{uuid.uuid4().hex}"
        interrupt = Interrupt(
            id=interrupt_id,
            reason="tool_call",
            message="Approval is required before this action can run.",
            tool_call_id=checkpoint.tool_call_id,
            expires_at=expires_at.isoformat().replace("+00:00", "Z"),
            metadata={
                "toolName": checkpoint.tool_name,
                "action": "approval_required",
                "toolPreview": action_preview,
            },
        )
        pending = _PendingApproval(
            interrupt=interrupt,
            checkpoint=checkpoint,
            thread_id=thread_id,
            provider_binding=provider_binding,
            expires_monotonic=now + self._ttl_seconds,
            expires_at=interrupt.expires_at or "",
        )
        with self._lock:
            self._cleanup_locked(now)
            self._pending[interrupt_id] = pending
        return interrupt

    def resolve(
        self,
        entries: list[ResumeEntry] | None,
        *,
        thread_id: str,
        provider_binding: str,
    ) -> ResolvedApproval | None:
        """Validate and consume exactly one native AG-UI resume entry."""

        if entries is None:
            return None
        if len(entries) != 1:
            raise ApprovalDecisionError("approval_invalid")

        entry = entries[0]
        interrupt_id = entry.interrupt_id
        if entry.status != "resolved":
            raise ApprovalDecisionError("approval_invalid")
        payload = entry.payload
        if (
            not isinstance(payload, dict)
            or set(payload) != {"approved"}
            or not isinstance(payload.get("approved"), bool)
        ):
            raise ApprovalDecisionError("approval_invalid")

        now = time.monotonic()
        with self._lock:
            self._cleanup_locked(now)
            pending = self._pending.get(interrupt_id)
            if pending is None:
                if interrupt_id in self._expired:
                    raise ApprovalDecisionError("approval_expired")
                # Consumed, unknown, and malformed ids intentionally share the
                # same public code so the registry does not become an oracle.
                raise ApprovalDecisionError("approval_invalid")
            if pending.expires_monotonic <= now:
                self._pending.pop(interrupt_id, None)
                self._expired[interrupt_id] = now + _EXPIRED_TOMBSTONE_SECONDS
                raise ApprovalDecisionError("approval_expired")
            if (
                pending.thread_id != thread_id
                or pending.provider_binding != provider_binding
            ):
                raise ApprovalDecisionError("approval_invalid")
            # Consume before invoking any model or tool.  A replay cannot
            # execute the original call a second time, even if the continuation
            # later fails for an unrelated reason.
            self._pending.pop(interrupt_id, None)

        return ResolvedApproval(
            checkpoint=pending.checkpoint,
            approved=payload["approved"],
            interrupt_id=interrupt_id,
        )

    def clear(self) -> None:
        """Clear live checkpoints; intended for tests and process shutdown."""

        with self._lock:
            self._pending.clear()
            self._expired.clear()

    def _cleanup_locked(self, now: float) -> None:
        expired = [
            interrupt_id
            for interrupt_id, pending in self._pending.items()
            if pending.expires_monotonic <= now
        ]
        for interrupt_id in expired:
            self._pending.pop(interrupt_id, None)
            self._expired[interrupt_id] = now + _EXPIRED_TOMBSTONE_SECONDS
        for interrupt_id, deadline in list(self._expired.items()):
            if deadline <= now:
                self._expired.pop(interrupt_id, None)


APPROVAL_REGISTRY = ApprovalRegistry()


@dataclass
class ApprovalContext:
    """Worker-thread context shared by FleetAgent and its profile loops."""

    thread_id: str
    run_id: str
    provider_binding: str
    registry: ApprovalRegistry
    lifecycle: ToolLifecycle | None = None
    cancel_token: RunCancelToken | None = None
    assistant_message_id: str | None = None
    resumed: ResolvedApproval | None = None

    def take_resumed_checkpoint(self, profile_name: str) -> ResolvedApproval | None:
        resolved = self.resumed
        if resolved is None:
            return None
        if resolved.checkpoint.profile_name != profile_name:
            raise ApprovalDecisionError("approval_invalid")
        self.resumed = None
        return resolved


_CURRENT_APPROVAL_CONTEXT: ContextVar[ApprovalContext | None] = ContextVar(
    "fleet_agent_approval_context", default=None
)


def current_approval_context() -> ApprovalContext | None:
    return _CURRENT_APPROVAL_CONTEXT.get()


def set_approval_context(
    context: ApprovalContext | None,
) -> Token[ApprovalContext | None]:
    """Set the worker-local context and return its reset token."""

    return _CURRENT_APPROVAL_CONTEXT.set(context)


def reset_approval_context(token: Any) -> None:
    _CURRENT_APPROVAL_CONTEXT.reset(token)


class ApprovalAwareReActV2(dspy.ReActV2):  # type: ignore[misc]
    """ReActV2 loop that pauses before policy-gated tool execution."""

    def __init__(
        self,
        signature: type[dspy.Signature],
        *,
        tools: list[Any],
        max_iters: int = 20,
        profile_name: str,
        approval_policy: Mapping[str, ToolMetadata | bool],
    ) -> None:
        super().__init__(signature, tools=tools, max_iters=max_iters)
        self.profile_name = profile_name
        self.approval_policy = dict(approval_policy)

    def forward(self, **input_args: Any) -> dspy.Prediction:
        max_iters = input_args.pop("max_iters", self.max_iters)
        history = _coerce_history(input_args.pop("history", None))
        pending_inputs = {
            name: input_args[name]
            for name in self.signature.input_fields
            if name in input_args
        }
        context = current_approval_context()
        resolved = (
            context.take_resumed_checkpoint(self.profile_name)
            if context is not None
            else None
        )

        break_reason = "max_iters"
        start_turn = 0
        if resolved is not None:
            checkpoint = resolved.checkpoint
            history = checkpoint.history
            pending_inputs = checkpoint.pending_inputs
            result = self._finish_tool_batch(
                context=context,
                resolved=resolved,
                checkpoint=checkpoint,
            )
            if result is not None:
                return result
            start_turn = checkpoint.turn_index + 1
            pending_inputs = {}

        for turn_index in range(start_turn, max_iters):
            if context is not None and context.cancel_token is not None:
                context.cancel_token.check()
            try:
                pred = self.react(
                    history=history,
                    tools=list(self.tools.values()),
                    **pending_inputs,
                )
                tool_calls = _coerce_tool_calls(getattr(pred, "tool_calls", None))
            except (AdapterParseError, ValueError):
                break_reason = "parse_error"
                break
            except ContextWindowExceededError:
                break_reason = "context_window_exceeded"
                break

            if not tool_calls.tool_calls:
                break_reason = "empty_tool_calls"
                break

            tool_calls = _ensure_tool_call_ids(tool_calls, turn_index)
            values, errors, final_outputs = self._execute_or_pause(
                context=context,
                pending_inputs=pending_inputs,
                prediction=pred,
                tool_calls=tool_calls,
                turn_index=turn_index,
                history=history,
                values=(),
                errors=(),
                start_index=0,
            )
            event = self._history_event(
                pending_inputs,
                pred,
                tool_calls,
                ToolCallResults.from_tool_calls_and_values(tool_calls, values, errors),
            )
            if final_outputs is not None:
                event.update(final_outputs)
            _append_history_event(history, event)
            pending_inputs = {}

            if final_outputs is not None:
                return dspy.Prediction(
                    **final_outputs, history=history, termination_reason="submit"
                )

        return self._forced_submit(history, pending_inputs, break_reason, max_iters)

    def _finish_tool_batch(
        self,
        *,
        context: ApprovalContext | None,
        resolved: ResolvedApproval,
        checkpoint: ApprovalCheckpoint,
    ) -> dspy.Prediction | None:
        values, errors, final_outputs = self._execute_or_pause(
            context=context,
            pending_inputs=checkpoint.pending_inputs,
            prediction=checkpoint.prediction,
            tool_calls=checkpoint.tool_calls,
            turn_index=checkpoint.turn_index,
            history=checkpoint.history,
            values=checkpoint.values,
            errors=checkpoint.errors,
            start_index=checkpoint.next_index,
            resolved=resolved,
        )
        event = self._history_event(
            checkpoint.pending_inputs,
            checkpoint.prediction,
            checkpoint.tool_calls,
            ToolCallResults.from_tool_calls_and_values(
                checkpoint.tool_calls, values, errors
            ),
        )
        if final_outputs is not None:
            event.update(final_outputs)
        _append_history_event(checkpoint.history, event)
        if final_outputs is not None:
            return dspy.Prediction(
                **final_outputs,
                history=checkpoint.history,
                termination_reason="submit",
            )
        return None

    def _execute_or_pause(
        self,
        *,
        context: ApprovalContext | None,
        pending_inputs: dict[str, Any],
        prediction: dspy.Prediction,
        tool_calls: ToolCalls,
        turn_index: int,
        history: dspy.History,
        values: tuple[Any, ...],
        errors: tuple[bool, ...],
        start_index: int,
        resolved: ResolvedApproval | None = None,
    ) -> tuple[list[Any], list[bool], dict[str, Any] | None]:
        next_values = list(values)
        next_errors = list(errors)
        final_outputs: dict[str, Any] | None = None
        for index in range(start_index, len(tool_calls.tool_calls)):
            call = tool_calls.tool_calls[index]
            call_id = str(call.id or f"call_{turn_index}_{index}")
            tool = self.tools.get(call.name)
            if tool is None:
                next_values.append(f"Unknown tool: {call.name}")
                next_errors.append(True)
                continue

            gated = _requires_approval(self.approval_policy.get(call.name))
            if resolved is not None and index == start_index:
                if (
                    resolved.checkpoint.tool_call_id != call_id
                    or resolved.checkpoint.tool_name != call.name
                    or not gated
                ):
                    raise ApprovalDecisionError("approval_invalid")
                if resolved.approved:
                    value, is_error = self._invoke_tool(
                        context, call_id, tool, call.args or {}, resume=True
                    )
                else:
                    denied = ApprovalDeniedError()
                    self._finish_tool(
                        context,
                        call_id,
                        tool,
                        None,
                        denied,
                        resumed=True,
                    )
                    value, is_error = (
                        "The tool call was not authorized by the user.",
                        True,
                    )
                next_values.append(value)
                next_errors.append(is_error)
                if call.name == "submit" and isinstance(value, dict) and not is_error:
                    final_outputs = value
                resolved = None
                continue

            if gated:
                if context is None:
                    raise ApprovalDecisionError("approval_invalid")
                self._start_tool(context, call_id, tool, call.args or {})
                checkpoint = ApprovalCheckpoint(
                    profile_name=self.profile_name,
                    history=copy.deepcopy(history),
                    pending_inputs=copy.deepcopy(pending_inputs),
                    prediction=copy.deepcopy(prediction),
                    tool_calls=tool_calls,
                    values=tuple(next_values),
                    errors=tuple(next_errors),
                    next_index=index,
                    turn_index=turn_index,
                    tool_name=call.name,
                    tool_call_id=call_id,
                    assistant_message_id=context.assistant_message_id,
                )
                interrupt = context.registry.create(
                    checkpoint=checkpoint,
                    thread_id=context.thread_id,
                    provider_binding=context.provider_binding,
                    action_preview=_action_preview(call.name, call.args or {}),
                )
                raise ApprovalPause(interrupt)

            value, is_error = self._invoke_tool(
                context, call_id, tool, call.args or {}, resume=False
            )
            next_values.append(value)
            next_errors.append(is_error)
            if call.name == "submit" and isinstance(value, dict) and not is_error:
                final_outputs = value

        return next_values, next_errors, final_outputs

    def _invoke_tool(
        self,
        context: ApprovalContext | None,
        call_id: str,
        tool: dspy.Tool,
        arguments: dict[str, Any],
        *,
        resume: bool,
    ) -> tuple[Any, bool]:
        self._start_tool(context, call_id, tool, arguments, emit=not resume)
        try:
            value = tool(**arguments)
        except Exception as exc:
            self._finish_tool(
                context,
                call_id,
                tool,
                None,
                exc,
                resumed=resume,
            )
            return (
                "Execution error in "
                f"{tool.name}: {format_error_for_lm(exc, traceback_frames=5)}",
                True,
            )
        self._finish_tool(context, call_id, tool, value, None, resumed=resume)
        return value, False

    @staticmethod
    def _start_tool(
        context: ApprovalContext | None,
        call_id: str,
        tool: dspy.Tool,
        arguments: dict[str, Any],
        *,
        emit: bool = True,
    ) -> None:
        if context is not None and context.cancel_token is not None:
            context.cancel_token.check()
        if (
            emit
            and tool.name != "submit"
            and context is not None
            and context.lifecycle is not None
        ):
            context.lifecycle.on_tool_start(call_id, tool, {"kwargs": arguments})

    @staticmethod
    def _finish_tool(
        context: ApprovalContext | None,
        call_id: str,
        tool: dspy.Tool,
        value: Any | None,
        exception: BaseException | None,
        *,
        resumed: bool,
    ) -> None:
        if context is None or context.lifecycle is None:
            return
        if tool.name == "submit":
            return
        if resumed:
            context.lifecycle.resume_tool_end(call_id, tool, value, exception)
        else:
            context.lifecycle.on_tool_end(call_id, value, exception)

    def _history_event(
        self,
        pending_inputs: dict[str, Any],
        pred: dspy.Prediction,
        tool_calls: ToolCalls,
        tool_call_results: ToolCallResults,
    ) -> dict[str, Any]:
        event = dict(pending_inputs)
        if hasattr(pred, "next_thought") and pred.next_thought is not None:
            event["next_thought"] = pred.next_thought
        if tool_calls.tool_calls:
            event["tool_calls"] = tool_calls.model_copy(
                update={"tool_call_results": tool_call_results}
            )
        return event


def _requires_approval(metadata: ToolMetadata | bool | None) -> bool:
    if isinstance(metadata, bool):
        return metadata
    return bool(metadata and metadata.requires_approval)


def _action_preview(tool_name: str, arguments: Mapping[str, Any]) -> str:
    """Bounded, single-line preview of one gated action for the approver.

    This is the one intentional, user-safe tool-argument exposure: the
    approver must see what they are deciding on (for example the requested
    command), while full arguments remain server-side.
    """
    if tool_name == "bash":
        command = arguments.get("command")
        if isinstance(command, str) and command.strip():
            return _preview_line(command, 160)
    if tool_name in {"write", "edit"}:
        path = arguments.get("path")
        if isinstance(path, str) and path.strip():
            content = arguments.get("content") if tool_name == "write" else None
            suffix = f" ({len(content)} chars)" if isinstance(content, str) else ""
            return _preview_line(f"{tool_name} {path}{suffix}", 160)
    return f"{tool_name} ({len(arguments)} argument(s))"


def _preview_line(value: str, limit: int) -> str:
    """Collapse to one bounded line so the preview cannot smuggle layout."""
    line = " ".join(value.split())
    if len(line) <= limit:
        return line
    return line[:limit] + "…"
