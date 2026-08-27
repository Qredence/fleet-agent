"""DSPy ReActV2 engine behind a provider-independent boundary.

FastAPI routes never touch ReActV2 internals: they see `AgentEngine.run()`
returning an `AgentRunResult`. The public fields of the result are model-
written, user-safe text (see AgentSignature); `history` is the raw
`dspy.History` for server-side continuation only — it contains `next_thought`
and MUST NOT cross to the browser (enforced by tests).
"""

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


@dataclass(frozen=True)
class AgentStreamUpdate:
    """Incremental engine output delivered before the run settles.

    ``final_fields`` carries the finish tool's public answer/process_summary
    the moment ReActV2's submit tool executes; ``result`` is the
    authoritative AgentRunResult that ends the stream. Engines without
    incremental delivery simply keep the ``run()`` contract.
    """

    kind: Literal["final_fields", "result"]
    answer: str | None = None
    process_summary: str | None = None
    result: AgentRunResult | None = None


class _StreamFailed:
    """Wakes the stream consumer so it re-raises the producer's exception."""

    __slots__ = ("error",)

    def __init__(self, error: BaseException) -> None:
        self.error = error


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
        callbacks: list[BaseCallback] | None = None,
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        self._agent_factory = agent_factory
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
        del context  # run identity is consumed by the bridge (PR 6)
        prediction = await asyncio.to_thread(self._run_sync, user_request, history)
        return _map_result(prediction)

    async def stream(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AsyncIterator[AgentStreamUpdate]:
        """Deliver final fields at submit time, then the settled result.

        Wraps the per-run submit tool so the public answer/process_summary are
        bridged to the event loop the moment the finish tool executes inside
        the worker thread — before ReActV2 settles the prediction. The hook is
        deliberately best-effort: a closed loop must not turn delivery into a
        submit failure (ReActV2 would then fall through to forced submit).
        """
        del context  # run identity is consumed by the bridge (PR 6)
        loop = asyncio.get_running_loop()
        updates: asyncio.Queue[AgentStreamUpdate | _StreamFailed] = asyncio.Queue()

        def on_agent_ready(agent: dspy.ReActV2) -> None:
            submit = agent.tools.get("submit")
            if submit is None:
                return
            original = submit.func

            def submit_hook(**kwargs: Any) -> Any:
                value = original(**kwargs)
                final = AgentStreamUpdate(
                    kind="final_fields",
                    answer=str(kwargs["answer"]) if kwargs.get("answer") else None,
                    process_summary=(
                        str(kwargs["process_summary"])
                        if kwargs.get("process_summary")
                        else None
                    ),
                )
                try:
                    loop.call_soon_threadsafe(updates.put_nowait, final)
                except RuntimeError:
                    logger.debug("stream bridge loop closed before final fields")
                return value

            submit.func = submit_hook

        async def produce() -> None:
            try:
                prediction = await asyncio.to_thread(
                    self._run_sync,
                    user_request,
                    history,
                    on_agent_ready=on_agent_ready,
                )
            except BaseException as exc:
                updates.put_nowait(_StreamFailed(exc))
                raise
            await updates.put(
                AgentStreamUpdate(kind="result", result=_map_result(prediction))
            )

        producer = asyncio.create_task(produce())
        try:
            while True:
                update = await updates.get()
                if isinstance(update, _StreamFailed):
                    raise update.error
                yield update
                if update.kind == "result":
                    break
            await producer
        finally:
            if not producer.done():
                producer.cancel()

    def _run_sync(
        self,
        user_request: str,
        history: Any | None,
        *,
        on_agent_ready: Callable[[dspy.ReActV2], None] | None = None,
    ) -> dspy.Prediction:
        try:
            agent = self._agent_factory()
            if on_agent_ready is not None:
                on_agent_ready(agent)
            with dspy.context(
                lm=self._lm,
                adapter=self._adapter,
                callbacks=self._callbacks,
                track_usage=True,
            ):
                return agent(user_request=user_request, history=history)
        finally:
            if self._cleanup is not None:
                try:
                    self._cleanup()
                except Exception:
                    logger.exception("agent run resource cleanup failed")
