"""DSPy ReActV2 engine behind a provider-independent boundary.

FastAPI routes never touch ReActV2 internals: they see `AgentEngine.run()`
returning an `AgentRunResult`. The public fields of the result are model-
written, user-safe text (see AgentSignature); `history` is the raw
`dspy.History` for server-side continuation only — it contains `next_thought`
and MUST NOT cross to the browser (enforced by tests).
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import dspy


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
    # Server-side only — contains raw next_thought. Never serialized to clients.
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
    reason = prediction.termination_reason
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
            history=prediction.history,
            usage=usage,
        )

    return AgentRunResult(
        status="failed",
        answer=None,
        process_summary=None,
        termination_reason=reason,
        error_code=_REASON_TO_PUBLIC_CODE.get(reason or "", "agent_no_output"),
        history=prediction.history,
        usage=usage,
    )


class DspyReActV2Engine:
    def __init__(
        self,
        *,
        agent_factory: Callable[[], dspy.ReActV2],
        lm: dspy.LM,
        adapter: dspy.Adapter | None = None,
    ) -> None:
        self._agent_factory = agent_factory
        self._lm = lm
        self._adapter = adapter

    async def run(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AgentRunResult:
        del context  # run identity is consumed by the bridge (PR 6)
        prediction = await asyncio.to_thread(self._run_sync, user_request, history)
        return _map_result(prediction)

    def _run_sync(self, user_request: str, history: Any | None) -> dspy.Prediction:
        agent = self._agent_factory()
        with dspy.context(lm=self._lm, adapter=self._adapter, track_usage=True):
            return agent(user_request=user_request, history=history)
