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
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any, cast

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
    InlineDataEvent,
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
_INLINE_PHASES = (
    ("planning", "Planning"),
    ("research", "Parallel research"),
    ("critique", "Verification"),
    ("synthesis", "Synthesis"),
)


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


class _ResearchTaskTimeout(RunCancelledError):
    """Cooperative timeout for one researcher inside DSPy's worker pool."""


class _TaskCancelToken(RunCancelToken):
    def __init__(self, parent: RunCancelToken, timeout_seconds: float) -> None:
        super().__init__()
        self._parent = parent
        self._deadline = time.monotonic() + timeout_seconds

    @property
    def cancelled(self) -> bool:
        return (
            self._parent.cancelled
            or super().cancelled
            or time.monotonic() >= self._deadline
        )

    def check(self) -> None:
        self._parent.check()
        if super().cancelled or time.monotonic() >= self._deadline:
            raise _ResearchTaskTimeout("research task timed out")


class _ParallelResearchModule(dspy.Module):  # type: ignore[misc]
    """Adapter that lets DSPy Parallel run one isolated ReAct worker."""

    def __init__(
        self,
        engine: StagedDspyEngine,
        *,
        task: ResearchTask,
        user_request: str,
        step_id: str,
        index: int,
        cancel_token: RunCancelToken,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._task = task
        self._user_request = user_request
        self._step_id = step_id
        self._index = index
        self._cancel_token = cancel_token
        self._task_timeout_seconds = engine._task_timeout_seconds

    def forward(self, user_request: str) -> _WorkerOutcome:
        del user_request
        task_cancel_token = _TaskCancelToken(
            self._cancel_token, self._task_timeout_seconds
        )
        outcome: _WorkerOutcome | None = None

        def run_research() -> None:
            nonlocal outcome
            try:
                outcome = self._engine._research_sync(
                    self._task,
                    self._user_request,
                    self._step_id,
                    task_cancel_token,
                )
            except _BudgetExceeded as exc:
                outcome = _WorkerOutcome(
                    task=self._task,
                    status="failed",
                    error_code=exc.code,
                    error_message=(
                        "The research task was skipped because the run budget "
                        "was exhausted."
                    ),
                )
            except _ResearchTaskTimeout:
                outcome = _WorkerOutcome(
                    task=self._task,
                    status="failed",
                    error_code="task_timeout",
                    error_message="The research task exceeded its time limit.",
                )
            except RunCancelledError:
                outcome = _WorkerOutcome(
                    task=self._task,
                    status="cancelled",
                    error_code="run_cancelled",
                    error_message="The research task was cancelled.",
                )
            except TimeoutError:
                outcome = _WorkerOutcome(
                    task=self._task,
                    status="failed",
                    error_code="task_timeout",
                    error_message="The research task exceeded its time limit.",
                )
            except Exception:
                logger.exception("staged research task failed")
                outcome = _WorkerOutcome(
                    task=self._task,
                    status="failed",
                    error_code="research_failed",
                    error_message="The research task failed.",
                )

        worker = threading.Thread(
            target=run_research,
            name=f"staged-research-{self._index + 1}",
            daemon=True,
        )
        worker.start()
        worker.join(self._task_timeout_seconds)
        if worker.is_alive():
            task_cancel_token.cancel()
            outcome = _WorkerOutcome(
                task=self._task,
                status="failed",
                error_code="task_timeout",
                error_message="The research task exceeded its time limit.",
            )
        elif outcome is None:
            outcome = _WorkerOutcome(
                task=self._task,
                status="failed",
                error_code="research_failed",
                error_message="The research task failed.",
            )
        self._engine._settle_research_task(self._index, outcome)
        return outcome


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
        cleanup: Callable[[], None] | None = None,
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
        self._inline_lock = threading.Lock()
        self._phase_status: dict[str, str] = {
            "planning": "pending",
            "research": "pending",
            "critique": "pending",
            "synthesis": "pending",
        }
        self._research_task_states: list[dict[str, object]] = []
        self._research_step_settled: set[int] = set()
        self._report_requested = False
        self._report_status: dict[str, str] = {
            "research": "pending",
            "synthesis": "pending",
            "export": "pending",
        }
        self._inline_source_count = 0

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
        self._reset_inline_state(user_request)
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
            plan = await self._plan_async(user_request)
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
        self._inline_source_count = sum(len(outcome.sources) for outcome in outcomes)
        self._publish_inline_progress()
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
                critique = await self._critic_async(user_request, evidence)
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
        else:
            self._set_phase_status("critique", "skipped")
        self._publish(
            StepStarted(
                step_id="step-synthesis",
                phase="synthesis",
                title="Synthesizing the response",
            )
        )
        try:
            cancel_token.check()
            result = await self._synthesize_async(user_request, evidence, critique)
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
        self._research_task_states = [
            {
                "id": f"step-research-{index + 1}",
                "name": "research",
                "target": _short(task.title),
                "state": "running",
            }
            for index, task in enumerate(tasks)
        ]
        self._research_step_settled.clear()
        for index, task in enumerate(tasks):
            self._publish(
                StepStarted(
                    step_id=f"step-research-{index + 1}",
                    parent_id="step-research",
                    phase="research",
                    title=_short(task.title),
                )
            )
        self._publish_inline_progress()
        cancel_token.check()

        pairs = [
            (
                _ParallelResearchModule(
                    self,
                    task=task,
                    user_request=user_request,
                    step_id=f"step-research-{index + 1}",
                    index=index,
                    cancel_token=cancel_token,
                ),
                dspy.Example(
                    user_request=(
                        f"Research this independent subtask: {task.task}\n"
                        f"Original user request: {user_request}"
                    ).strip()
                ).with_inputs("user_request"),
            )
            for index, task in enumerate(tasks)
        ]

        # DSPy 3.3.1's Parallel is intentionally called from one async-to-sync
        # boundary. It owns the bounded worker pool and propagates the
        # dspy.context overrides into each isolated module invocation.
        result = await asyncio.to_thread(self._parallel_forward, pairs)
        if isinstance(result, tuple):
            raw_results: list[Any] = list(result[0])
        else:
            raw_results = list(result)

        outcomes: list[_WorkerOutcome] = []
        for index, raw in enumerate(raw_results or []):
            if isinstance(raw, _WorkerOutcome):
                outcomes.append(raw)
                continue
            task = tasks[index]
            outcome = _WorkerOutcome(
                task=task,
                status="cancelled" if cancel_token.cancelled else "failed",
                error_code=(
                    "run_cancelled" if cancel_token.cancelled else "research_failed"
                ),
                error_message=(
                    "The research task was cancelled."
                    if cancel_token.cancelled
                    else "The research task failed."
                ),
            )
            self._settle_research_task(index, outcome)
            outcomes.append(outcome)

        while len(outcomes) < len(tasks):
            index = len(outcomes)
            task = tasks[index]
            outcome = _WorkerOutcome(
                task=task,
                status="cancelled" if cancel_token.cancelled else "failed",
                error_code=(
                    "run_cancelled" if cancel_token.cancelled else "research_failed"
                ),
                error_message=(
                    "The research task was cancelled."
                    if cancel_token.cancelled
                    else "The research task failed."
                ),
            )
            self._settle_research_task(index, outcome)
            outcomes.append(outcome)
        return outcomes

    def _parallel_forward(
        self,
        pairs: list[tuple[dspy.Module, dspy.Example]],
    ) -> (
        list[_WorkerOutcome] | tuple[list[_WorkerOutcome | None], list[Any], list[Any]]
    ):
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=[],
            track_usage=True,
        ):
            parallel = dspy.Parallel(
                num_threads=min(self._max_parallel_tasks, len(pairs)) or 1,
                max_errors=len(pairs) or 1,
                return_failed_examples=True,
                disable_progress_bar=True,
                # The module wrapper enforces a hard per-task deadline. DSPy's
                # timeout resubmits stragglers rather than cancelling them.
                timeout=0,
                straggler_limit=0,
            )
            return cast(
                list[_WorkerOutcome]
                | tuple[list[_WorkerOutcome | None], list[Any], list[Any]],
                parallel(pairs),
            )

    async def _plan_async(self, user_request: str) -> ResearchPlan:
        # Preserve the synchronous override seam used by provider-free tests
        # and integrations while the production path uses DSPy's asyncify.
        if type(self)._plan_sync is not StagedDspyEngine._plan_sync:
            return await asyncio.to_thread(self._plan_sync, user_request)
        module = dspy.Predict(PlannerSignature)
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=self._budget_callbacks(),
            track_usage=True,
        ):
            prediction = await dspy.asyncify(module)(user_request=user_request)
        return self._parse_plan_prediction(prediction, user_request)

    def _plan_sync(self, user_request: str) -> ResearchPlan:
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=self._budget_callbacks(),
            track_usage=True,
        ):
            prediction = dspy.Predict(PlannerSignature)(user_request=user_request)
        return self._parse_plan_prediction(prediction, user_request)

    def _parse_plan_prediction(
        self, prediction: dspy.Prediction, user_request: str
    ) -> ResearchPlan:
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
            tools=self._registry.dspy_tools(
                read_only_only=True, allowed_names=allowed, isolate=True
            ),
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

    async def _critic_async(self, user_request: str, evidence: str) -> str:
        if type(self)._critic_sync is not StagedDspyEngine._critic_sync:
            return await asyncio.to_thread(self._critic_sync, user_request, evidence)
        module = dspy.Predict(CriticSignature)
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=self._budget_callbacks(),
            track_usage=True,
        ):
            prediction = await dspy.asyncify(module)(
                user_request=user_request, evidence_json=evidence
            )
        return _short(getattr(prediction, "critique", ""))

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

    async def _synthesize_async(
        self, user_request: str, evidence: str, critique: str
    ) -> AgentRunResult:
        if type(self)._synthesize_sync is not StagedDspyEngine._synthesize_sync:
            return await asyncio.to_thread(
                self._synthesize_sync, user_request, evidence, critique
            )
        module = dspy.Predict(SynthesisSignature)
        with dspy.context(
            lm=self._lm,
            adapter=self._adapter,
            callbacks=self._budget_callbacks(),
            track_usage=True,
        ):
            prediction = await dspy.asyncify(module)(
                user_request=user_request,
                evidence_json=evidence,
                critique=_short(critique),
            )
        return self._synthesis_result(prediction)

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
        return self._synthesis_result(prediction)

    def _synthesis_result(self, prediction: dspy.Prediction) -> AgentRunResult:
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
            self._set_report_status("export", "failed")
            return replace(
                result,
                caveats=[
                    *result.caveats,
                    "Report generation was requested but is not configured.",
                ],
            )
        tool_call_id = "staged-write-report"
        self._set_report_status("export", "writing")
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
            self._set_report_status("export", "done")
            self._publish(
                ToolCompleted(
                    tool_call_id=tool_call_id,
                    name="write_report",
                    output_preview=report.model_output,
                    duration_ms=int(report.metadata.get("durationMs", 0)),
                )
            )
            return result
        self._set_report_status("export", "failed")
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

    def _reset_inline_state(self, user_request: str) -> None:
        with self._inline_lock:
            self._phase_status = {key: "pending" for key, _ in _INLINE_PHASES}
            self._research_task_states = []
            self._research_step_settled.clear()
            self._report_requested = _requests_report(user_request)
            self._report_status = {
                "research": "pending",
                "synthesis": "pending",
                "export": "pending",
            }
            self._inline_source_count = 0

    def _set_phase_status(self, phase: str, status: str) -> None:
        with self._inline_lock:
            self._phase_status[phase] = status
        self._publish_inline_progress()
        self._publish_report_snapshot()

    def _settle_research_task(self, index: int, outcome: _WorkerOutcome) -> None:
        with self._inline_lock:
            if index in self._research_step_settled:
                return
            self._research_step_settled.add(index)
            if index < len(self._research_task_states):
                self._research_task_states[index]["state"] = (
                    "done" if outcome.status == "completed" else "failed"
                )
        step_id = f"step-research-{index + 1}"
        if outcome.status == "completed":
            self._publish(
                StepCompleted(
                    step_id=step_id,
                    public_summary="Research task completed with bounded evidence.",
                )
            )
        else:
            self._publish(
                StepFailed(
                    step_id=step_id,
                    public_summary=outcome.error_message or "Research task failed.",
                )
            )

    def _publish_inline_progress(self) -> None:
        with self._inline_lock:
            phases = [
                {
                    "id": key,
                    "label": label,
                    "status": self._phase_status[key],
                }
                for key, label in _INLINE_PHASES
            ]
            tools = [
                dict(task) for task in self._research_task_states[:_MAX_PLAN_TASKS]
            ]
            source_count = self._inline_source_count
        active_index = next(
            (
                index
                for index, phase in enumerate(phases)
                if phase["status"] in {"running", "pending"}
            ),
            len(phases),
        )
        value: dict[str, object] = {
            "schemaVersion": 1,
            "steps": phases,
            "activeIndex": active_index,
            "sourceCount": source_count,
        }
        if tools:
            value["tools"] = tools
        self._bus.publish_from_worker(
            InlineDataEvent(name="agent-progress", value=value)
        )

    def _set_report_status(self, section: str, status: str) -> None:
        with self._inline_lock:
            self._report_status[section] = status
        self._publish_report_snapshot()

    def _publish_report_snapshot(self) -> None:
        if not self._report_requested:
            return
        with self._inline_lock:
            sections = [
                {
                    "id": "research",
                    "heading": "Research evidence",
                    "state": self._report_status["research"],
                    "sources": self._inline_source_count,
                },
                {
                    "id": "synthesis",
                    "heading": "Synthesis",
                    "state": self._report_status["synthesis"],
                    "sources": self._inline_source_count,
                },
                {
                    "id": "export",
                    "heading": "Report file",
                    "state": self._report_status["export"],
                    "sources": 0,
                },
            ]
            source_count = self._inline_source_count
        self._bus.publish_from_worker(
            InlineDataEvent(
                name="research-report",
                value={
                    "schemaVersion": 1,
                    "title": "Research report",
                    "sections": sections,
                    "sourcesRead": source_count,
                },
            )
        )

    def _publish(self, event: Any) -> None:
        phase: str | None = None
        with self._inline_lock:
            if isinstance(event, StepStarted):
                self._open_steps.add(event.step_id)
                phase = _phase_for_step(event.step_id)
                if phase is not None:
                    self._phase_status[phase] = "running"
            elif isinstance(event, (StepCompleted, StepFailed)):
                self._open_steps.discard(event.step_id)
                phase = _phase_for_step(event.step_id)
                if phase is not None:
                    self._phase_status[phase] = (
                        "completed" if isinstance(event, StepCompleted) else "failed"
                    )
            if phase == "research":
                self._report_status[phase] = (
                    "done" if self._phase_status[phase] == "completed" else "writing"
                )
            elif phase == "synthesis":
                self._report_status[phase] = (
                    "done"
                    if self._phase_status[phase] == "completed"
                    else "failed"
                    if self._phase_status[phase] == "failed"
                    else "writing"
                )
        self._bus.publish_from_worker(event)
        if phase is not None:
            self._publish_inline_progress()
            self._publish_report_snapshot()

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


def _phase_for_step(step_id: str) -> str | None:
    return {
        "step-plan": "planning",
        "step-research": "research",
        "step-critique": "critique",
        "step-synthesis": "synthesis",
    }.get(step_id)
