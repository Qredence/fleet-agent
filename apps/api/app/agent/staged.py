"""Feature-flagged staged DSPy reasoning.

The planner, critic, and synthesizer are ordinary DSPy modules.  Each
research task gets an isolated ReActV2 instance and callback, while the
orchestrator keeps fan-out, cancellation, and budgets outside the model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

import dspy
from pydantic import BaseModel, Field

from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import AgentRunContext, AgentRunResult, _map_result
from app.agent.instrumented import sanitize_args
from app.agent.signature import AgentSignature
from app.agent.tool_registry import ToolRegistry
from app.agui.cancel_token import RunCancelledError, RunCancelToken
from app.agui.event_bus import RunEventBus
from app.contracts.domain import (
    SourceResult,
    StepCompleted,
    StepFailed,
    StepStarted,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

logger = logging.getLogger(__name__)

_MAX_PLAN_TASKS = 4
_MAX_TEXT = 1200
_MAX_EVIDENCE = 8000


class PlannerSignature(dspy.Signature):  # type: ignore[misc]
    """Create a small, independent research plan from the user request."""

    user_request: str = dspy.InputField(desc="The user's request.")
    plan_json: str = dspy.OutputField(
        desc=(
            "JSON object with tasks, each containing task, title, and tools; "
            "maximum four independent read-only tasks."
        )
    )
    verification_required: bool = dspy.OutputField(
        desc="Whether the final answer should verify evidence before synthesis."
    )


class CriticSignature(dspy.Signature):  # type: ignore[misc]
    """Assess evidence quality without exposing hidden reasoning."""

    user_request: str = dspy.InputField(desc="The user's request.")
    evidence_json: str = dspy.InputField(desc="Bounded research evidence.")
    critique: str = dspy.OutputField(desc="Concise evidence-quality assessment.")


class SynthesisSignature(dspy.Signature):  # type: ignore[misc]
    """Produce the same safe public fields as the default ReAct path."""

    user_request: str = dspy.InputField(desc="The user's request.")
    evidence_json: str = dspy.InputField(desc="Bounded successful and failed evidence.")
    critique: str = dspy.InputField(desc="Bounded optional evidence critique.")
    answer: str = dspy.OutputField(desc="Direct final answer to the user.")
    process_summary: str = dspy.OutputField(desc="Concise user-safe process summary.")
    key_decisions: list[str] = dspy.OutputField(desc="Important decisions made.")
    caveats: list[str] = dspy.OutputField(desc="Remaining uncertainty or limitations.")


class ResearchTask(BaseModel):
    title: str
    task: str
    tools: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    tasks: list[ResearchTask] = Field(default_factory=list)
    verification_required: bool = False


class _WorkerOutcome(BaseModel):
    task: ResearchTask
    status: str
    answer: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    sources: list[SourceResult] = Field(default_factory=list)


class _Budget:
    def __init__(self, max_model_calls: int, max_tool_calls: int) -> None:
        self._lock = threading.Lock()
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.model_calls = 0
        self.tool_calls = 0

    def model(self) -> None:
        with self._lock:
            if self.model_calls >= self.max_model_calls:
                raise _BudgetExceeded("model_call_budget_exhausted")
            self.model_calls += 1

    def tool(self, _name: str) -> None:
        with self._lock:
            if self.tool_calls >= self.max_tool_calls:
                raise _BudgetExceeded("tool_call_budget_exhausted")
            self.tool_calls += 1


class _BudgetExceeded(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class StagedDspyEngine:
    """AgentEngine implementation for the opt-in staged strategy."""

    def __init__(
        self,
        *,
        lm: dspy.LM,
        adapter: dspy.Adapter | None,
        registry: ToolRegistry,
        bus: RunEventBus,
        max_parallel_tasks: int,
        max_model_calls: int,
        max_tool_calls: int,
        task_timeout_seconds: float,
        researcher_max_iters: int,
        cleanup: Any | None = None,
    ) -> None:
        self._lm = lm
        self._adapter = adapter
        self._registry = registry
        self._bus = bus
        self._max_parallel_tasks = max_parallel_tasks
        self._max_model_calls = max_model_calls
        self._max_tool_calls = max_tool_calls
        self._task_timeout_seconds = task_timeout_seconds
        self._researcher_max_iters = researcher_max_iters
        self._cleanup = cleanup
        self._open_steps: set[str] = set()
        self._active_budget: _Budget | None = None

    async def run(
        self,
        *,
        user_request: str,
        history: Any | None,
        context: AgentRunContext,
    ) -> AgentRunResult:
        del context
        # Keep the entire staged lifecycle in one worker thread.  In
        # particular, per-run HTTP clients are closed there after nested DSPy
        # workers have finished, even if the outer asyncio task is cancelled.
        return await asyncio.to_thread(
            self._run_sync, user_request, history, self._bus.cancel_token
        )

    def _run_sync(
        self, user_request: str, history: Any | None, cancel_token: RunCancelToken
    ) -> AgentRunResult:
        del history
        try:
            return asyncio.run(self._run_async(user_request, cancel_token))
        except RunCancelledError:
            self._fail_open_steps("The staged reasoning step was cancelled.")
            return AgentRunResult(
                status="failed",
                answer=None,
                process_summary="The staged reasoning run was cancelled.",
                termination_reason="cancelled",
                error_code="run_cancelled",
            )
        except Exception:
            logger.exception("staged DSPy run failed")
            self._fail_open_steps("The staged reasoning step failed.")
            return AgentRunResult(
                status="failed",
                answer=None,
                process_summary="The staged reasoning run could not be completed.",
                termination_reason="failed",
                error_code="internal_error",
            )
        finally:
            if self._cleanup is not None:
                try:
                    self._cleanup()
                except Exception:
                    logger.exception("staged agent resource cleanup failed")

    async def _run_async(
        self, user_request: str, cancel_token: RunCancelToken
    ) -> AgentRunResult:
        budget = _Budget(self._max_model_calls, self._max_tool_calls)
        self._active_budget = budget
        self._publish(
            StepStarted(
                step_id="step-plan",
                phase="planning",
                title="Planning the research",
            )
        )
        try:
            plan = await asyncio.to_thread(self._plan_sync, user_request)
        except _BudgetExceeded:
            self._publish(
                StepFailed(
                    step_id="step-plan",
                    public_summary=(
                        "Planning stopped because the model budget was exhausted."
                    ),
                )
            )
            return AgentRunResult(
                status="failed",
                answer=None,
                process_summary=None,
                termination_reason="model_call_budget_exhausted",
                error_code="agent_no_output",
            )
        cancel_token.check()
        self._publish(
            StepCompleted(
                step_id="step-plan",
                public_summary=f"Prepared {len(plan.tasks)} bounded research task(s).",
            )
        )
        self._publish(
            StepStarted(
                step_id="step-research",
                phase="research",
                title="Researching in parallel",
            )
        )

        tasks = plan.tasks[:_MAX_PLAN_TASKS]
        outcomes = await self._research_parallel(tasks, user_request, cancel_token)
        cancel_token.check()
        failed = sum(outcome.status != "completed" for outcome in outcomes)
        self._publish(
            StepCompleted(
                step_id="step-research",
                public_summary=(
                    f"Completed {len(outcomes) - failed} of "
                    f"{len(outcomes)} research task(s)."
                ),
            )
        )

        evidence = _evidence_json(outcomes)
        should_criticize = (
            plan.verification_required
            or len(outcomes) > 1
            or failed > 0
            or _has_conflicting_answers(outcomes)
        )
        critique = ""
        if should_criticize:
            cancel_token.check()
            self._publish(
                StepStarted(
                    step_id="step-critique",
                    phase="critique",
                    title="Checking the evidence",
                )
            )
            try:
                critique = await asyncio.to_thread(
                    self._critic_sync, user_request, evidence
                )
                self._publish(
                    StepCompleted(
                        step_id="step-critique",
                        public_summary=(
                            "Checked source coverage and conflicting evidence."
                        ),
                    )
                )
            except _BudgetExceeded:
                self._publish(
                    StepFailed(
                        step_id="step-critique",
                        public_summary=(
                            "Evidence checking was skipped because the model budget "
                            "was exhausted."
                        ),
                    )
                )
                critique = (
                    "Evidence checking was skipped because the model budget "
                    "was exhausted."
                )
        self._publish(
            StepStarted(
                step_id="step-synthesis",
                phase="synthesis",
                title="Synthesizing the response",
            )
        )
        try:
            cancel_token.check()
            result = await asyncio.to_thread(
                self._synthesize_sync, user_request, evidence, critique
            )
            result = self._maybe_write_report(result, user_request)
            self._publish(
                StepCompleted(
                    step_id="step-synthesis",
                    public_summary=(
                        result.process_summary or "Composed the final answer."
                    ),
                )
            )
            return result
        except _BudgetExceeded:
            self._publish(
                StepFailed(
                    step_id="step-synthesis",
                    public_summary=(
                        "Synthesis could not run because the model budget was "
                        "exhausted."
                    ),
                )
            )
            return AgentRunResult(
                status="failed",
                answer=None,
                process_summary=None,
                termination_reason="model_call_budget_exhausted",
                error_code="agent_no_output",
            )

    async def _research_parallel(
        self,
        tasks: list[ResearchTask],
        user_request: str,
        cancel_token: RunCancelToken,
    ) -> list[_WorkerOutcome]:
        semaphore = asyncio.Semaphore(self._max_parallel_tasks)

        async def run_one(index: int, task: ResearchTask) -> _WorkerOutcome:
            step_id = f"step-research-{index + 1}"
            self._publish(
                StepStarted(
                    step_id=step_id,
                    parent_id="step-research",
                    phase="research",
                    title=task.title,
                )
            )
            try:
                cancel_token.check()
                async with semaphore:
                    outcome = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._research_sync,
                            task,
                            user_request,
                            step_id,
                            cancel_token,
                        ),
                        timeout=self._task_timeout_seconds,
                    )
                if outcome.status == "completed":
                    self._publish(
                        StepCompleted(
                            step_id=step_id,
                            public_summary=(
                                "Research task completed with bounded evidence."
                            ),
                        )
                    )
                else:
                    self._publish(
                        StepFailed(
                            step_id=step_id,
                            public_summary=outcome.error_message
                            or "Research task failed.",
                        )
                    )
                return outcome
            except _BudgetExceeded as exc:
                outcome = _WorkerOutcome(
                    task=task,
                    status="failed",
                    error_code=exc.code,
                    error_message=(
                        "The research task was skipped because the run budget "
                        "was exhausted."
                    ),
                )
            except TimeoutError:
                outcome = _WorkerOutcome(
                    task=task,
                    status="failed",
                    error_code="task_timeout",
                    error_message="The research task exceeded its time limit.",
                )
            except RunCancelledError:
                outcome = _WorkerOutcome(
                    task=task,
                    status="cancelled",
                    error_code="run_cancelled",
                    error_message="The research task was cancelled.",
                )
            except Exception:
                logger.exception("staged research task failed")
                outcome = _WorkerOutcome(
                    task=task,
                    status="failed",
                    error_code="research_failed",
                    error_message="The research task failed.",
                )
            self._publish(
                StepFailed(
                    step_id=step_id,
                    public_summary=(outcome.error_message or "Research task failed."),
                )
            )
            return outcome

        task_to_research = {
            asyncio.create_task(run_one(index, task)): task
            for index, task in enumerate(tasks)
        }
        pending = set(task_to_research)
        results: list[_WorkerOutcome] = []
        while pending:
            done, pending = await asyncio.wait(pending, timeout=0.1)
            results.extend(task.result() for task in done)
            if cancel_token.cancelled:
                for task in pending:
                    task.cancel()
                cancelled = await asyncio.gather(*pending, return_exceptions=True)
                for task_handle, value in zip(pending, cancelled, strict=True):
                    if isinstance(value, _WorkerOutcome):
                        results.append(value)
                    else:
                        results.append(
                            _WorkerOutcome(
                                task=task_to_research[task_handle],
                                status="cancelled",
                                error_code="run_cancelled",
                                error_message="The research task was cancelled.",
                            )
                        )
                pending = set()
        results.sort(key=lambda outcome: tasks.index(outcome.task))
        return results

    def _plan_sync(self, user_request: str) -> ResearchPlan:
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=self._budget_callbacks(),
            track_usage=True,
        ):
            prediction = dspy.Predict(PlannerSignature)(user_request=user_request)
        try:
            payload = json.loads(str(getattr(prediction, "plan_json", "{}")))
            if isinstance(payload, dict):
                raw_tasks = payload.get("tasks", [])
            elif isinstance(payload, list):
                raw_tasks = payload
            else:
                raw_tasks = []
            tasks = [
                ResearchTask(
                    title=_short(item.get("title") or f"Research task {index + 1}"),
                    task=_short(item.get("task") or item.get("query") or user_request),
                    tools=[str(tool) for tool in item.get("tools", [])],
                )
                for index, item in enumerate(raw_tasks[:_MAX_PLAN_TASKS])
                if isinstance(item, dict)
            ]
            if tasks:
                return ResearchPlan(
                    tasks=tasks,
                    verification_required=_as_bool(
                        getattr(prediction, "verification_required", False)
                    ),
                )
        except Exception:
            logger.warning("planner output did not match the staged plan shape")
        return ResearchPlan(
            tasks=[
                ResearchTask(
                    title="Find relevant evidence",
                    task=_short(user_request),
                    tools=list(self._registry.names()),
                )
            ]
        )

    def _research_sync(
        self,
        task: ResearchTask,
        user_request: str,
        step_id: str,
        cancel_token: RunCancelToken,
    ) -> _WorkerOutcome:
        cancel_token.check()
        allowed = [
            name
            for name in task.tools
            if name in self._registry.names()
            and self._registry.get(name).metadata.read_only
            and self._registry.get(name).metadata.parallelizable
        ]
        if not allowed:
            allowed = [
                name
                for name in self._registry.names()
                if self._registry.get(name).metadata.read_only
                and self._registry.get(name).metadata.parallelizable
            ]
        callback = AgUiRunCallback(
            bus=self._bus,
            cancel_token=cancel_token,
            id_prefix=f"research-{step_id}-",
            step_id=step_id,
            before_tool=(
                self._active_budget.tool if self._active_budget is not None else None
            ),
            before_model=(
                self._active_budget.model if self._active_budget is not None else None
            ),
        )
        worker = dspy.ReActV2(
            AgentSignature,
            tools=self._registry.dspy_tools(read_only_only=True, allowed_names=allowed),
            max_iters=self._researcher_max_iters,
        )
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=[callback],
            track_usage=True,
        ):
            prediction = worker(
                user_request=(
                    f"Research this independent subtask: {task.task}\n"
                    f"Original user request: {user_request}"
                ),
                history=None,
            )
        result = _map_result(prediction)
        return _WorkerOutcome(
            task=task,
            status=result.status,
            answer=_short(result.answer) if result.answer else None,
            error_code=result.error_code,
            error_message=(
                "The research worker did not produce evidence."
                if result.status != "completed"
                else None
            ),
            sources=callback.sources,
        )

    def _critic_sync(self, user_request: str, evidence: str) -> str:
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=self._budget_callbacks(),
            track_usage=True,
        ):
            prediction = dspy.Predict(CriticSignature)(
                user_request=user_request, evidence_json=evidence
            )
        return _short(getattr(prediction, "critique", ""))

    def _synthesize_sync(
        self, user_request: str, evidence: str, critique: str
    ) -> AgentRunResult:
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=self._budget_callbacks(),
            track_usage=True,
        ):
            prediction = dspy.Predict(SynthesisSignature)(
                user_request=user_request,
                evidence_json=evidence,
                critique=_short(critique),
            )
        answer = _short(getattr(prediction, "answer", ""))
        if not answer:
            return AgentRunResult(
                status="failed",
                answer=None,
                process_summary=None,
                termination_reason="empty_tool_calls",
                error_code="agent_no_output",
            )
        return AgentRunResult(
            status="completed",
            answer=answer,
            process_summary=_short(getattr(prediction, "process_summary", "")),
            key_decisions=_short_list(getattr(prediction, "key_decisions", [])),
            caveats=_short_list(getattr(prediction, "caveats", [])),
            termination_reason="submit",
        )

    def _maybe_write_report(
        self, result: AgentRunResult, user_request: str
    ) -> AgentRunResult:
        """Run the side-effecting report tool only after synthesis."""

        if result.status != "completed" or not _requests_report(user_request):
            return result
        if "write_report" not in self._registry.names():
            return replace(
                result,
                caveats=[
                    *result.caveats,
                    "Report generation was requested but is not configured.",
                ],
            )
        tool_call_id = "staged-write-report"
        self._publish(
            ToolStarted(
                tool_call_id=tool_call_id,
                name="write_report",
                input_preview=sanitize_args(
                    {"title": "Agent report", "content": result.answer or ""}
                ),
                step_id="step-synthesis",
            )
        )
        report = self._registry.execute(
            "write_report",
            {"title": "Agent report", "content": result.answer or ""},
            cancel_token=self._bus.cancel_token,
        )
        if report.status == "completed":
            self._publish(
                ToolCompleted(
                    tool_call_id=tool_call_id,
                    name="write_report",
                    output_preview=report.model_output,
                    duration_ms=int(report.metadata.get("durationMs", 0)),
                )
            )
            return result
        self._publish(
            ToolFailed(
                tool_call_id=tool_call_id,
                name="write_report",
                error_message=(
                    report.error_message or "The report could not be written."
                ),
                duration_ms=int(report.metadata.get("durationMs", 0)),
            )
        )
        return replace(
            result,
            caveats=[
                *result.caveats,
                "The final answer was ready, but the requested report could "
                "not be written.",
            ],
        )

    def _publish(self, event: Any) -> None:
        if isinstance(event, StepStarted):
            self._open_steps.add(event.step_id)
        elif isinstance(event, (StepCompleted, StepFailed)):
            self._open_steps.discard(event.step_id)
        self._bus.publish_from_worker(event)

    def _budget_callbacks(self) -> list[AgUiRunCallback]:
        return [
            AgUiRunCallback(
                bus=self._bus,
                cancel_token=self._bus.cancel_token,
                before_model=(
                    self._active_budget.model
                    if self._active_budget is not None
                    else None
                ),
            )
        ]

    def _fail_open_steps(self, message: str) -> None:
        for step_id in tuple(self._open_steps):
            self._publish(StepFailed(step_id=step_id, public_summary=message))


def _short(value: Any) -> str:
    return str(value or "").strip()[:_MAX_TEXT]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _short_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_short(value)] if value else []
    return [_short(item) for item in list(value or [])[:8] if str(item).strip()]


def _evidence_json(outcomes: Iterable[_WorkerOutcome]) -> str:
    entries = []
    for outcome in outcomes:
        entries.append(
            {
                "task": _short(outcome.task.task),
                "status": outcome.status,
                "answer": _short(outcome.answer),
                "errorCode": outcome.error_code,
                "errorMessage": _short(outcome.error_message),
                "sources": [
                    {"title": _short(source.title), "uri": source.uri}
                    for source in outcome.sources[:8]
                ],
            }
        )
    return json.dumps(entries, ensure_ascii=True)[:_MAX_EVIDENCE]


def _has_conflicting_answers(outcomes: list[_WorkerOutcome]) -> bool:
    answers = {outcome.answer for outcome in outcomes if outcome.answer}
    return len(answers) > 1


def _requests_report(user_request: str) -> bool:
    normalized = user_request.lower()
    return any(
        phrase in normalized
        for phrase in (
            "write a report",
            "create a report",
            "generate a report",
            "export a report",
        )
    )
