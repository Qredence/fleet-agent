import asyncio
import json
import threading
import time
from typing import Any

import dspy
import pytest

from app.agent.engine import AgentRunContext, AgentRunResult
from app.agent.staged import (
    ResearchPlan,
    ResearchTask,
    StagedDspyEngine,
    _WorkerOutcome,
)
from app.agent.tool_registry import ToolRegistry
from app.agui.event_bus import DONE, RunEventBus
from app.contracts.domain import StepCompleted, StepFailed, StepStarted
from tests.helpers.scripted_lm import ScriptedLM, submit_call


class FakeStagedEngine(StagedDspyEngine):
    def __init__(self, *args: Any, fail_index: int | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.fail_index = fail_index
        self.research_started = threading.Barrier(4)
        self.critic_calls = 0

    def _plan_sync(self, user_request: str) -> ResearchPlan:
        del user_request
        return ResearchPlan(
            tasks=[
                ResearchTask(title=f"Task {index}", task=f"question {index}")
                for index in range(4)
            ]
        )

    def _research_sync(
        self,
        task: ResearchTask,
        user_request: str,
        step_id: str,
        cancel_token,
    ) -> _WorkerOutcome:
        del user_request, step_id
        cancel_token.check()
        self.research_started.wait(timeout=2)
        index = int(task.title.split()[-1])
        time.sleep((4 - index) * 0.01)
        if self.fail_index == index:
            return _WorkerOutcome(
                task=task,
                status="failed",
                error_code="research_failed",
                error_message="The research task failed.",
            )
        return _WorkerOutcome(
            task=task,
            status="completed",
            answer=f"Evidence {index}",
        )

    def _critic_sync(self, user_request: str, evidence: str) -> str:
        del user_request, evidence
        self.critic_calls += 1
        return "The evidence is sufficient."

    def _synthesize_sync(
        self, user_request: str, evidence: str, critique: str
    ) -> AgentRunResult:
        del user_request, evidence, critique
        return AgentRunResult(
            status="completed",
            answer="Synthesized answer.",
            process_summary="Combined independent evidence.",
            key_decisions=["Compared research tasks"],
        )


def _make_engine(bus: RunEventBus, **kwargs: Any) -> FakeStagedEngine:
    return FakeStagedEngine(
        lm=ScriptedLM([]),
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
        registry=ToolRegistry([]),
        bus=bus,
        max_parallel_tasks=4,
        max_model_calls=8,
        max_tool_calls=12,
        task_timeout_seconds=2,
        researcher_max_iters=1,
        **kwargs,
    )


async def _run_engine(engine: StagedDspyEngine) -> AgentRunResult:
    return await engine.run(
        user_request="compare four sources",
        history=None,
        context=AgentRunContext(thread_id="thread", run_id="run"),
    )


async def _drain(bus: RunEventBus) -> list[Any]:
    bus.close_from_loop()
    events = []
    while True:
        event = await bus.next()
        if event is DONE:
            return events
        events.append(event)


@pytest.mark.asyncio
async def test_staged_engine_fans_out_four_tasks_and_critiques_partial_failure():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    engine = _make_engine(bus, fail_index=2)

    result = await _run_engine(engine)
    events = await _drain(bus)

    assert result.status == "completed"
    assert engine.critic_calls == 1
    children = [
        event
        for event in events
        if isinstance(event, StepStarted) and event.parent_id == "step-research"
    ]
    assert len(children) == 4
    assert any(isinstance(event, StepFailed) for event in events)
    assert any(
        isinstance(event, StepCompleted) and event.step_id == "step-synthesis"
        for event in events
    )


@pytest.mark.asyncio
async def test_staged_engine_cleanup_waits_for_cancelled_worker():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    cleaned = threading.Event()

    class SlowPlanner(FakeStagedEngine):
        def _plan_sync(self, user_request: str) -> ResearchPlan:
            del user_request
            time.sleep(0.1)
            return ResearchPlan(tasks=[ResearchTask(title="Task", task="q")])

    engine = SlowPlanner(
        lm=ScriptedLM([]),
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
        registry=ToolRegistry([]),
        bus=bus,
        max_parallel_tasks=1,
        max_model_calls=8,
        max_tool_calls=12,
        task_timeout_seconds=2,
        researcher_max_iters=1,
        cleanup=cleaned.set,
    )
    task = asyncio.create_task(_run_engine(engine))
    await asyncio.sleep(0.02)
    bus.cancel_token.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(20):
        if cleaned.is_set():
            break
        await asyncio.sleep(0.02)
    assert cleaned.is_set()


@pytest.mark.asyncio
async def test_staged_engine_uses_dspy_planner_critic_and_synthesizer():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    plan = {
        "plan_json": json.dumps(
            {"tasks": [{"title": "One source", "task": "Find evidence"}]}
        ),
        "verification_required": True,
    }
    synth = {
        "answer": "Synthesized from evidence.",
        "process_summary": "Planned, checked, and synthesized.",
        "key_decisions": ["Used one read-only task"],
        "caveats": [],
    }
    lm = ScriptedLM(
        [
            {"calls": [], "content": json.dumps(plan)},
            [submit_call(answer="Evidence found")],
            {"calls": [], "content": json.dumps({"critique": "Sufficient."})},
            {"calls": [], "content": json.dumps(synth)},
        ]
    )
    engine = StagedDspyEngine(
        lm=lm,
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
        registry=ToolRegistry([]),
        bus=bus,
        max_parallel_tasks=1,
        max_model_calls=4,
        max_tool_calls=4,
        task_timeout_seconds=2,
        researcher_max_iters=1,
    )

    result = await _run_engine(engine)
    events = await _drain(bus)

    assert result.status == "completed"
    assert result.answer == "Synthesized from evidence."
    assert any(
        isinstance(event, StepCompleted) and event.step_id == "step-critique"
        for event in events
    )
