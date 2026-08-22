"""Integration: LiveDSPyCoordinator streams a real (scripted) engine run."""

import asyncio
import json

import dspy

from app.agent.engine import DspyReActV2Engine
from app.agent.instrumented import instrument_tool
from app.agent.signature import AgentSignature
from app.agent.tools import search_docs
from app.agui.event_bus import RunEventBus
from app.agui.live_coordinator import LiveDSPyCoordinator
from tests.helpers.scripted_lm import ScriptedLM, submit_call


def scripted_builder(steps, tools=None, max_iters=4):
    base_tools = tools if tools is not None else [search_docs]

    def build(bus: RunEventBus, *, thread_id: str = "t-test"):
        wrapped = [instrument_tool(tool, bus) for tool in base_tools]

        def agent_factory() -> dspy.ReActV2:
            return dspy.ReActV2(AgentSignature, tools=wrapped, max_iters=max_iters)

        return DspyReActV2Engine(
            agent_factory=agent_factory,
            lm=ScriptedLM(steps),  # type: ignore[arg-type]
            adapter=dspy.JSONAdapter(),
        )

    return build


def run_input(text="Explain state sync", thread="thread-live", run="run-live"):
    return {
        "threadId": thread,
        "runId": run,
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }


async def collect(
    steps,
    text="Explain state sync",
    thread="thread-live",
    run="run-live",
    tools=None,
    max_iters=4,
) -> list[dict]:
    from ag_ui.core import RunAgentInput

    coordinator = LiveDSPyCoordinator()
    stream = coordinator.stream(
        input_data=RunAgentInput.model_validate(run_input(text, thread, run)),
        engine_builder=scripted_builder(steps, tools=tools, max_iters=max_iters),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    events = []
    async for chunk in stream:
        events.append(json.loads(chunk.removeprefix("data: ").strip()))
    return events


async def _false() -> bool:
    return False


def apply_state(events: list[dict]) -> dict:
    import jsonpatch

    state = next(e["snapshot"] for e in events if e["type"] == "STATE_SNAPSHOT")
    for event in events:
        if event["type"] == "STATE_DELTA":
            state = jsonpatch.apply_patch(state, event["delta"])
    return state


async def test_tool_activity_streams_before_final_answer():
    steps = [
        [{"name": "search_docs", "args": {"query": "state sync"}}],
        [submit_call(answer="It patches state.")],
    ]
    events = await collect(steps)
    types = [e["type"] for e in events]

    assert types[0] == "RUN_STARTED"
    assert types[1] == "STATE_SNAPSHOT"
    assert types.index("STATE_DELTA") == 2  # understanding starts
    # Tool lifecycle completes before any assistant text.
    assert types.index("TOOL_CALL_START") < types.index("TEXT_MESSAGE_START")
    assert types.index("TOOL_CALL_RESULT") < types.index("TEXT_MESSAGE_START")
    assert types[-1] == "RUN_FINISHED"
    assert "RUN_ERROR" not in types

    # Final answer arrives as text content.
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "It patches state." in text

    # State ends completed with the tool execution recorded.
    state = apply_state(events)
    assert state["run"]["status"] == "completed"
    assert len(state["toolCalls"]) == 1
    assert state["toolCalls"][0]["name"] == "search_docs"
    assert state["decisions"] == [
        {
            "id": "decision-0",
            "title": "kept scope tight",
            "alternatives": [],
            "status": "accepted",
        }
    ]


async def test_every_tool_event_carries_matching_ids():
    from app.agent.tools import get_current_time

    steps = [
        [
            {"name": "search_docs", "args": {"query": "x"}},
            {"name": "get_current_time", "args": {}},
        ],
        [submit_call()],
    ]
    events = await collect(steps, tools=[search_docs, get_current_time])
    starts = [e for e in events if e["type"] == "TOOL_CALL_START"]
    results = {e["toolCallId"] for e in events if e["type"] == "TOOL_CALL_RESULT"}
    assert len(starts) == 2
    assert {s["toolCallId"] for s in starts} == results

    state = apply_state(events)
    assert {t["id"] for t in state["toolCalls"]} == results
    for event in events:
        if "threadId" in event:
            assert event["threadId"] == "thread-live"
        if "runId" in event:
            assert event["runId"] == "run-live"


async def test_recoverable_tool_error_keeps_stream_valid():
    def exploding(query: str) -> str:
        """Always fails."""
        raise RuntimeError("internal provider detail: sk-secret-987")

    steps = [
        [{"name": "exploding", "args": {"query": "x"}}],
        [submit_call(answer="Recovered from failure.")],
    ]
    events = await collect(steps, tools=[exploding])
    types = [e["type"] for e in events]

    assert "RUN_ERROR" not in types
    assert types[-1] == "RUN_FINISHED"

    state = apply_state(events)
    (tool,) = state["toolCalls"]
    assert tool["status"] == "failed"
    assert tool["errorMessage"] == "The exploding tool call failed."

    body = json.dumps(events)
    assert "sk-secret-987" not in body
    assert "internal provider detail" not in body
    assert "next_thought" not in body


async def test_missing_output_yields_safe_run_error():
    steps = [
        [{"name": "search_docs", "args": {"query": "x"}}],
        [
            {
                "name": "submit",
                "args": {
                    "process_summary": "tried",
                    "key_decisions": [],
                    "caveats": [],
                },
            }
        ],
    ]
    events = await collect(steps, max_iters=1)
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "agent_no_output"
    assert "Traceback" not in events[-1]["message"]

    state = apply_state(events)
    assert state["run"]["status"] == "failed"
    assert state["run"]["errorCode"] == "agent_no_output"
    assert all(s["status"] == "completed" for s in state["steps"])


async def test_engine_crash_yields_internal_error_not_stack_trace():
    builder = scripted_builder([RuntimeError("boom with api_key=sk-xyz")])

    from ag_ui.core import RunAgentInput

    async def call():
        stream = LiveDSPyCoordinator().stream(
            input_data=RunAgentInput.model_validate(run_input()),
            engine_builder=builder,
            accept="text/event-stream",
            is_disconnected=lambda: _false(),
        )
        return [json.loads(c.removeprefix("data: ").strip()) async for c in stream]

    events = await call()
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "internal_error"
    assert events[-1]["message"] == "The agent run failed."
    assert "sk-xyz" not in json.dumps(events)

    state = apply_state(events)
    assert state["run"]["status"] == "failed"
    assert state["run"]["errorCode"] == "internal_error"


async def test_two_concurrent_runs_stay_isolated():
    events_a, events_b = await asyncio.gather(
        collect([[submit_call(answer="Answer A")]], run="run-a"),
        collect([[submit_call(answer="Answer B")]], run="run-b"),
    )
    body_a = json.dumps([e for e in events_a if e["type"].startswith("TEXT_MESSAGE")])
    body_b = json.dumps([e for e in events_b if e["type"].startswith("TEXT_MESSAGE")])
    assert "Answer A" in body_a and "Answer B" not in body_a
    assert "Answer B" in body_b and "Answer A" not in body_b

    state_a = apply_state(events_a)
    state_b = apply_state(events_b)
    assert state_a["run"]["id"] == "run-a"
    assert state_b["run"]["id"] == "run-b"
