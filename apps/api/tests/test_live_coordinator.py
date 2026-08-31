"""Integration: LiveDSPyCoordinator streams a real (scripted) engine run."""

import asyncio
import json
import logging

import dspy

from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import DspyAgentEngine
from app.agent.instrumented import instrument_tool
from app.agent.signature import AgentSignature
from app.agent.tools import search_docs
from app.agui.event_bus import RunEventBus
from app.agui.live_coordinator import LiveDSPyCoordinator
from app.contracts.domain import SourceResult
from tests.helpers.scripted_lm import ScriptedLM, submit_call


def scripted_builder(steps, tools=None, max_iters=4):
    base_tools = tools if tools is not None else [search_docs]

    def build(bus: RunEventBus, *, thread_id: str = "t-test"):
        wrapped = [instrument_tool(tool, bus) for tool in base_tools]

        def program_factory() -> dspy.ReActV2:
            return dspy.ReActV2(AgentSignature, tools=wrapped, max_iters=max_iters)

        return DspyAgentEngine(
            program_factory=program_factory,
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


async def test_settlement_failure_after_answer_still_finishes_once():
    """A persistence outage must not leave an accepted SSE stream open-ended."""

    from types import SimpleNamespace

    from ag_ui.core import RunAgentInput

    class FailingPersistence:
        async def get_run(self, run_id):
            del run_id
            return SimpleNamespace(continuation_message_id=None)

        async def get_latest_state(self, thread_id, head_message_id):
            del thread_id, head_message_id
            return None

        async def mark_running(self, *, run_id, state_json):
            del run_id, state_json

        async def get_continuation_history(self, thread_id, head_message_id):
            del thread_id, head_message_id
            return None

        async def run_completed(self, **kwargs):
            del kwargs
            raise RuntimeError("database driver detail must stay server-side")

    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(run_input()),
        engine_builder=scripted_builder([[submit_call(answer="Persist later")]]),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
        persistence=FailingPersistence(),  # type: ignore[arg-type]
    )
    events = [
        json.loads(chunk.removeprefix("data: ").strip()) async for chunk in stream
    ]
    types = [event["type"] for event in events]

    assert types.count("RUN_FINISHED") + types.count("RUN_ERROR") == 1
    assert types[-1] == "RUN_FINISHED"
    assert "database driver detail" not in json.dumps(events)
    assert apply_state(events)["run"]["status"] == "completed"


async def test_unexpected_failure_still_emits_terminal_when_settlement_fails(caplog):
    caplog.set_level(logging.ERROR)
    from types import SimpleNamespace

    from ag_ui.core import RunAgentInput

    class FailingPersistence:
        async def get_run(self, run_id):
            del run_id
            return SimpleNamespace(continuation_message_id=None)

        async def get_latest_state(self, thread_id, head_message_id):
            del thread_id, head_message_id
            return None

        async def mark_running(self, *, run_id, state_json):
            del run_id, state_json

        async def get_continuation_history(self, thread_id, head_message_id):
            del thread_id, head_message_id
            return None

        async def run_failed(self, **kwargs):
            del kwargs
            raise RuntimeError("sensitive persistence detail")

    def broken_builder(bus, *, thread_id):
        del bus, thread_id
        raise RuntimeError("provider stack trace")

    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(run_input()),
        engine_builder=broken_builder,
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
        persistence=FailingPersistence(),  # type: ignore[arg-type]
    )
    events = [
        json.loads(chunk.removeprefix("data: ").strip()) async for chunk in stream
    ]
    types = [event["type"] for event in events]

    assert types.count("RUN_FINISHED") + types.count("RUN_ERROR") == 1
    assert types[-1] == "RUN_ERROR"
    assert "sensitive persistence detail" not in json.dumps(events)
    assert "provider stack trace" not in json.dumps(events)
    assert "provider stack trace" not in caplog.text


async def test_tool_activity_streams_before_final_answer():
    steps = [
        [{"name": "search_docs", "args": {"query": "state sync"}}],
        [submit_call(answer="It patches state.")],
    ]
    events = await collect(steps)
    types = [e["type"] for e in events]

    assert types[0] == "RUN_STARTED"
    assert types[1] == "TEXT_MESSAGE_START"
    assert types[2] == "STATE_SNAPSHOT"
    assert types.index("STATE_DELTA") == 3  # understanding starts
    # Tool lifecycle completes before any assistant text.
    assert types.index("TEXT_MESSAGE_START") < types.index("TOOL_CALL_START")
    assert types.index("TOOL_CALL_RESULT") < types.index("TEXT_MESSAGE_CONTENT")
    assert types.count("TEXT_MESSAGE_START") == 1
    assert types.count("TEXT_MESSAGE_END") == 1
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


async def test_web_search_and_sources_are_transcript_custom_events():
    source = SourceResult(
        id="w1",
        title="DSPy docs",
        source_type="web",
        uri="https://dspy.ai/api",
    )

    def web_search(query: str) -> str:
        web_search.last_sources = [source]
        return f"result for {query}"

    web_search.last_sources = []

    def builder(bus: RunEventBus, *, thread_id: str = "thread-live"):
        del thread_id
        callback = AgUiRunCallback(bus=bus)

        def program_factory() -> dspy.ReActV2:
            return dspy.ReActV2(
                AgentSignature,
                tools=[web_search],
                max_iters=2,
            )

        return DspyAgentEngine(
            program_factory=program_factory,
            lm=ScriptedLM(
                [
                    [{"name": "web_search", "args": {"query": "DSPy"}}],
                    [submit_call(answer="Found DSPy docs.")],
                ]
            ),
            adapter=dspy.JSONAdapter(use_native_function_calling=True),
            callbacks=[callback],
        )

    from ag_ui.core import RunAgentInput

    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(run_input()),
        engine_builder=builder,
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    events = [
        json.loads(chunk.removeprefix("data: ").strip()) async for chunk in stream
    ]

    custom = [event for event in events if event["type"] == "CUSTOM"]
    assert [event["name"] for event in custom] == [
        "web-search",
        "sources",
        "web-search",
    ]
    assert custom[0]["value"]["searching"] is True
    assert custom[1]["value"]["sources"] == [
        {"title": "DSPy docs", "domain": "dspy.ai"}
    ]
    assert custom[2]["value"]["results"] == [
        {"title": "DSPy docs", "domain": "dspy.ai"}
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


# --- finish-tool incremental streaming -------------------------------------


async def test_engine_stream_delivers_final_fields_before_result():
    """engine.stream() yields the submit tool's fields, then the result."""
    engine = scripted_builder([[submit_call("Fresh answer.", "Fresh summary.")]])(
        RunEventBus(asyncio.get_running_loop()), thread_id="t-stream"
    )
    from app.agent.engine import AgentRunContext

    updates = []
    async for update in engine.stream(
        user_request="Explain state sync",
        history=None,
        context=AgentRunContext(thread_id="t-stream", run_id="r-stream"),
    ):
        updates.append(update)
    assert [u.kind for u in updates] == ["final_fields", "result"]
    assert updates[0].answer == "Fresh answer."
    assert updates[0].process_summary == "Fresh summary."
    assert updates[1].result is not None
    assert updates[1].result.status == "completed"
    assert updates[1].result.answer == "Fresh answer."


async def test_streaming_coordinator_emits_answer_once_before_run_finished():
    """The finish-tool answer arrives as ONE text message ahead of settlement."""
    events = await collect([[submit_call("Answer early.", "Summary early.")]])
    types = [e["type"] for e in events]
    starts = [
        e
        for e in events
        if e["type"] == "TEXT_MESSAGE_START" and e["messageId"] == "msg-run-live"
    ]
    assert len(starts) == 1
    assert types.index("TEXT_MESSAGE_END") < types.index("RUN_FINISHED")
    assert types[-1] == "RUN_FINISHED"
    # Raw reasoning never crosses the wire.
    assert all("next_thought" not in json.dumps(e) for e in events)
    # The synthesis step ends up with the model's own summary.
    state = apply_state(events)
    synthesis = next(s for s in state["steps"] if s["id"] == "step-synthesis")
    assert synthesis["publicSummary"] == "Summary early."
    assert state["run"]["status"] == "completed"


class _RunOnlyEngine:
    """Fallback engine without incremental delivery (no .stream)."""

    async def run(self, *, user_request, history, context):  # noqa: ANN001, ANN202
        """
        Provide a completed fallback agent result.

        Parameters:
            user_request: The current user request.
            history: The conversation history.
            context: The execution context.

        Returns:
            AgentRunResult: A completed result containing a fallback answer and summary.
        """
        from app.agent.engine import AgentRunResult

        return AgentRunResult(
            status="completed",
            answer="Fallback answer.",
            process_summary="Fallback summary.",
            key_decisions=[],
            caveats=[],
            termination_reason="submit",
        )


async def test_run_only_engine_falls_back_to_completion_time_answer():
    """Engines without .stream still emit the answer message at completion."""
    coordinator = LiveDSPyCoordinator()
    from ag_ui.core import RunAgentInput

    def builder(bus, *, thread_id="t-test"):  # noqa: ANN001, ANN202
        """
        Create a run-only test engine.

        Parameters:
            bus: Event bus accepted for builder compatibility.
            thread_id (str): Thread identifier accepted for builder compatibility.

        Returns:
            _RunOnlyEngine: A test engine exposing only the run interface.
        """
        return _RunOnlyEngine()

    stream = coordinator.stream(
        input_data=RunAgentInput.model_validate(run_input()),
        engine_builder=builder,
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    events = [
        json.loads(chunk.removeprefix("data: ").strip()) async for chunk in stream
    ]
    types = [e["type"] for e in events]
    starts = [
        e
        for e in events
        if e["type"] == "TEXT_MESSAGE_START" and e["messageId"] == "msg-run-live"
    ]
    assert len(starts) == 1
    assert starts[0] is not None
    deltas = [i for i, t in enumerate(types) if t == "STATE_DELTA"]
    assert types.index("TEXT_MESSAGE_START") < deltas[-1]
    assert types[-1] == "RUN_FINISHED"
    content = [e for e in events if e["type"] == "TEXT_MESSAGE_CONTENT"]
    assert "".join(e["delta"] for e in content) == "Fallback answer."
