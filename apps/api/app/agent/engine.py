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
from dspy.utils.callback import BaseCallback

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentRunContext:
    thread_id: str
    run_id: str


@dataclass(frozen=True)
class AgentRunResult:
    status: Literal["completed", "failed"]
    answer: str | None
    process_summary: str | None
    key_decisions: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    termination_reason: str | None = None
    error_code: str | None = None
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
    """Public incremental update followed by the authoritative run result.

    The DSPy 3.3.1 ReActV2 completion hook is private. The engine therefore
    emits final public fields from the settled Prediction instead of mutating
    ReActV2's internal ``submit`` tool. True token streaming belongs in a
    separate public ``dspy.streamify`` integration.
    """

    kind: Literal["final_fields", "result"]
    answer: str | None = None
    process_summary: str | None = None
    result: AgentRunResult | None = None


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
            answer=answer,
            process_summary=getattr(prediction, "process_summary", None) or None,
            key_decisions=list(getattr(prediction, "key_decisions", None) or []),
            caveats=caveats,
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
        lm: dspy.LM,
        adapter: dspy.Adapter | None = None,
        callbacks: list[BaseCallback] | None = None,
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        self._program_factory = program_factory
        self._lm = lm
        self._adapter = adapter
        self._callbacks = list(callbacks or [])
        self._cleanup = cleanup

    async def run(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AgentRunResult:
        del context  # run identity is consumed by the AG-UI bridge
        prediction = await asyncio.to_thread(self._run_sync, user_request, history)
        return _map_result(prediction)

    async def stream(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AsyncIterator[AgentStreamUpdate]:
        """Emit settled public fields and then the authoritative result.

        This deliberately avoids accessing ``program.react.tools['submit']``.
        The AG-UI contract stays unchanged, while the DSPy program remains a
        black box to the runtime adapter.
        """
        del context
        prediction = await asyncio.to_thread(self._run_sync, user_request, history)
        result = _map_result(prediction)

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
    ) -> dspy.Prediction:
        try:
            program = self._program_factory()
            with dspy.context(
                lm=self._lm,
                adapter=self._adapter,
                callbacks=self._callbacks,
                track_usage=True,
            ):
                # Invoke the Module through __call__, never forward(), so DSPy
                # usage tracking, callbacks, caller-module context, and future
                # optimizer/runtime hooks remain active.
                return program(user_request=user_request, history=history)
        finally:
            if self._cleanup is not None:
                try:
                    self._cleanup()
                except Exception:
                    logger.exception("agent run resource cleanup failed")
