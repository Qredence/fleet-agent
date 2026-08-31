import asyncio
import copy
import threading

import jsonpatch

from app.agent.engine import AgentRunResult
from app.agui.event_bus import DONE, RunEventBus
from app.agui.trace_reducer import TraceReducer
from app.contracts.agent_state import AgentWorkspaceState
from app.contracts.domain import (
    ArtifactReady,
    ArtifactResult,
    ArtifactStarted,
    SourceDiscovered,
    SourceResult,
    StepCompleted,
    StepStarted,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)


def validate(state: dict) -> None:
    AgentWorkspaceState.model_validate(state)


class WireConsumer:
    """Independently applies the coordinator's patch stream and validates the
    resulting state after every single delta — like the browser does."""

    def __init__(self, reducer: TraceReducer) -> None:
        self.state = copy.deepcopy(reducer.state)
        validate(self.state)

    def feed(self, ops: list) -> dict:
        self.state = jsonpatch.apply_patch(self.state, ops)
        validate(self.state)
        return self.state

    def matches(self, reducer: TraceReducer) -> None:
        assert self.state == reducer.state


async def test_bus_cross_thread_fifo_order():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)

    def worker() -> None:
        for i in range(5):
            bus.publish_from_worker(
                ToolStarted(
                    tool_call_id=f"tool_{i}",
                    name="t",
                    arguments_json="{}",
                    input_preview="{}",
                )
            )
        loop.call_soon_threadsafe(bus.close_from_loop)

    threading.Thread(target=worker).start()

    ids = []
    while True:
        event = await bus.next()
        if event is DONE:
            break
        ids.append(event.tool_call_id)
    assert ids == [f"tool_{i}" for i in range(5)]


def _state_after(reducer: TraceReducer, wire: WireConsumer, ops: list) -> dict:
    return wire.feed(ops)


def successful_result() -> AgentRunResult:
    return AgentRunResult(
        status="completed",
        answer="Final answer.",
        process_summary="Looked up docs and summarized.",
        key_decisions=["Used search_docs first"],
        caveats=["Docs may be stale"],
        termination_reason="submit",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


def test_full_tool_run_stays_schema_valid_at_every_patch():
    reducer = TraceReducer(thread_id="t-1", run_id="r-1")
    validate(reducer.state)
    wire = WireConsumer(reducer)

    state = _state_after(reducer, wire, reducer.begin())
    assert state["steps"][0]["status"] == "running"

    started = ToolStarted(
        tool_call_id="tool_a",
        name="search_docs",
        arguments_json='{"query":"x"}',
        input_preview='{"query": "x"}',
    )
    state = _state_after(reducer, wire, reducer.apply_tool_event(started))
    assert [s["id"] for s in state["steps"]] == [
        "step-understand",
        "step-research",
    ]
    assert state["run"]["activeStepId"] == "step-research"
    assert state["run"]["toolCallCount"] == 1
    assert state["toolCalls"][0]["status"] == "running"

    completed = ToolCompleted(
        tool_call_id="tool_a",
        name="search_docs",
        output_preview="3 docs",
        duration_ms=42,
    )
    state = _state_after(reducer, wire, reducer.apply_tool_event(completed))
    tool = state["toolCalls"][0]
    assert tool["status"] == "completed"
    assert tool["durationMs"] == 42

    state = _state_after(reducer, wire, reducer.complete_run(successful_result()))
    wire.matches(reducer)
    assert state["run"]["status"] == "completed"
    assert state["run"]["terminationReason"] == "submit"
    assert "activeStepId" not in state["run"]
    assert state["sources"] == []
    assert state["decisions"][0]["title"] == "Used search_docs first"
    assert state["caveats"] == ["Docs may be stale"]
    assert state["metrics"]["totalTokens"] == 15
    assert state["metrics"]["toolCallCount"] == 1


def test_partial_usage_omits_missing_optional_metrics():
    reducer = TraceReducer(thread_id="t-1", run_id="r-1")
    wire = WireConsumer(reducer)
    wire.feed(reducer.begin())

    result = AgentRunResult(
        status="completed",
        answer="Final answer.",
        process_summary="Done.",
        usage={"prompt_tokens": 10},
    )
    state = wire.feed(reducer.complete_run(result))

    assert state["metrics"]["inputTokens"] == 10
    assert "outputTokens" not in state["metrics"]
    assert "totalTokens" not in state["metrics"]


def test_failed_tool_marks_tool_not_run():
    reducer = TraceReducer(thread_id="t-1", run_id="r-1")
    wire = WireConsumer(reducer)
    wire.feed(reducer.begin())
    started = ToolStarted(
        tool_call_id="tool_a",
        name="search_docs",
        arguments_json="{}",
        input_preview="{}",
    )
    wire.feed(reducer.apply_tool_event(started))
    failed = ToolFailed(
        tool_call_id="tool_a",
        name="search_docs",
        error_message="The search_docs tool call failed.",
        duration_ms=500,
    )
    state = _state_after(reducer, wire, reducer.apply_tool_event(failed))
    tool = state["toolCalls"][0]
    assert tool["status"] == "failed"
    assert tool["errorMessage"] == "The search_docs tool call failed."

    failed_result = AgentRunResult(
        status="failed",
        answer=None,
        process_summary=None,
        termination_reason="max_iters",
        error_code="agent_no_output",
    )
    state = _state_after(reducer, wire, reducer.complete_run(failed_result))
    wire.matches(reducer)
    assert state["run"]["status"] == "failed"
    assert state["run"]["errorCode"] == "agent_no_output"
    # A failed run must still complete its public steps — no forever-running UI.
    assert all(s["status"] == "completed" for s in state["steps"])


def test_no_tool_run_completes_without_research_step():
    reducer = TraceReducer(thread_id="t-1", run_id="r-1")
    wire = WireConsumer(reducer)
    wire.feed(reducer.begin())
    state = _state_after(reducer, wire, reducer.complete_run(successful_result()))
    wire.matches(reducer)
    assert [s["id"] for s in state["steps"]] == ["step-understand", "step-synthesis"]
    assert state["run"]["toolCallCount"] == 0


def test_live_synthesis_summary_starts_step_with_started_at():
    reducer = TraceReducer(thread_id="t-1", run_id="r-1")
    wire = WireConsumer(reducer)
    wire.feed(reducer.begin())
    state = _state_after(reducer, wire, reducer.live_synthesis_summary("Drafting..."))
    wire.matches(reducer)
    synthesis = state["steps"][-1]
    assert synthesis["id"] == "step-synthesis"
    assert synthesis["status"] == "running"
    assert synthesis["startedAt"]
    assert synthesis["publicSummary"] == "Drafting..."
    assert state["run"]["activeStepId"] == "step-synthesis"

    # A second chunk must not restart or duplicate the running step.
    started_at = synthesis["startedAt"]
    ops = reducer.live_synthesis_summary("Drafting the rest...")
    state = _state_after(reducer, wire, ops)
    wire.matches(reducer)
    assert state["steps"][-1]["startedAt"] == started_at
    assert len([s for s in state["steps"] if s["id"] == "step-synthesis"]) == 1

    final = _state_after(reducer, wire, reducer.complete_run(successful_result()))
    wire.matches(reducer)
    finished = next(s for s in final["steps"] if s["id"] == "step-synthesis")
    assert finished["status"] == "completed"
    assert finished["durationMs"] >= 0
    assert finished["publicSummary"] == "Looked up docs and summarized."


def test_staged_child_steps_and_out_of_order_tools_stay_schema_valid():
    reducer = TraceReducer(thread_id="t-1", run_id="r-staged")
    wire = WireConsumer(reducer)
    wire.feed(reducer.begin())

    for step in (
        StepStarted(
            step_id="step-plan",
            phase="planning",
            title="Planning the research",
        ),
        StepStarted(
            step_id="step-research",
            phase="research",
            title="Researching in parallel",
        ),
        StepStarted(
            step_id="step-research-1",
            parent_id="step-research",
            phase="research",
            title="Find source one",
        ),
        StepStarted(
            step_id="step-research-2",
            parent_id="step-research",
            phase="research",
            title="Find source two",
        ),
    ):
        wire.feed(reducer.apply_event(step))

    for tool_id, step_id in (
        ("tool-2", "step-research-2"),
        ("tool-1", "step-research-1"),
    ):
        wire.feed(
            reducer.apply_event(
                ToolStarted(
                    tool_call_id=tool_id,
                    name="search_docs",
                    arguments_json="{}",
                    input_preview="{}",
                    step_id=step_id,
                )
            )
        )
    wire.feed(
        reducer.apply_event(
            ToolCompleted(
                tool_call_id="tool-1",
                name="search_docs",
                output_preview="first",
                duration_ms=5,
            )
        )
    )
    state = wire.feed(
        reducer.apply_event(
            StepCompleted(
                step_id="step-research-1",
                public_summary="Completed.",
            )
        )
    )

    assert state["steps"][3]["parentId"] == "step-research"
    assert state["steps"][3]["toolCallIds"] == ["tool-1"]
    assert state["steps"][4]["toolCallIds"] == ["tool-2"]
    wire.feed(
        reducer.apply_event(
            StepCompleted(step_id="step-research-2", public_summary="Completed.")
        )
    )
    wire.feed(
        reducer.apply_event(
            StepCompleted(step_id="step-research", public_summary="All tasks done.")
        )
    )
    state = wire.feed(reducer.complete_run(successful_result()))
    assert len({step["id"] for step in state["steps"]}) == len(state["steps"])


def test_second_run_inherits_prior_evidence():
    """Turn 2 (no artifacts of its own) must not erase turn 1's sources/artifacts."""
    reducer = TraceReducer(thread_id="t-1", run_id="run-1")
    wire = WireConsumer(reducer)

    wire.feed(reducer.begin())
    started = ToolStarted(
        tool_call_id="tool_a",
        name="search_docs",
        arguments_json="{}",
        input_preview="{}",
    )
    wire.feed(reducer.apply_event(started))
    for source in (
        SourceDiscovered(
            tool_call_id="tool_a",
            source=SourceResult(id="doc-1", title="Doc 1", source_type="web"),
        ),
        SourceDiscovered(
            tool_call_id="tool_a",
            source=SourceResult(id="doc-2", title="Doc 2", source_type="web"),
        ),
    ):
        wire.feed(reducer.apply_event(source))
    completed = ToolCompleted(
        tool_call_id="tool_a",
        name="search_docs",
        output_preview="found",
        duration_ms=10,
    )
    wire.feed(reducer.apply_event(completed))
    artifact_event = ArtifactStarted(
        artifact=ArtifactResult(
            id="a-1",
            name="report.md",
            media_type="text/markdown",
            storage_key="t-1/a-1/report.md",
        )
    )
    wire.feed(reducer.apply_event(artifact_event))
    ready = ArtifactReady(
        artifact=ArtifactResult(
            id="a-1",
            name="report.md",
            media_type="text/markdown",
            storage_key="t-1/a-1/report.md",
            size_bytes=64,
        ),
        download_url="/api/artifacts/a-1",
    )
    wire.feed(reducer.apply_event(ready))
    first_state = wire.feed(reducer.complete_run(successful_result()))
    assert len(first_state["sources"]) == 2
    assert len(first_state["artifacts"]) == 1

    # Turn 2: a fresh reducer seeded with turn 1's final state.
    reducer2 = TraceReducer(thread_id="t-1", run_id="run-2", prior_state=first_state)
    wire2 = WireConsumer(reducer2)
    wire2.feed(reducer2.begin())
    second_state = wire2.feed(reducer2.complete_run(successful_result()))
    wire2.matches(reducer2)

    assert len(second_state["artifacts"]) == 1
    assert second_state["artifacts"][0]["name"] == "report.md"
    assert len(second_state["sources"]) == 2
    assert second_state["metrics"]["toolCallCount"] == 0
