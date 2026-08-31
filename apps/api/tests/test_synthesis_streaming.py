"""DSPy-native synthesis streaming: engine tokens, scrubbing, coordinator SSE.

These tests pin the Phase 3 contract: the routed program's synthesis fields
stream token-by-token through ``dspy.streamify`` + ``StreamListener``,
emission-time scrubbing holds back text that might contain a split secret,
and the coordinator turns tokens into incremental AG-UI message/state events
exactly once.
"""

from __future__ import annotations

import json
from typing import Any

import dspy
from ag_ui.core import RunAgentInput

from app.agent.engine import AgentRunContext, DspyAgentEngine
from app.agent.factory import build_tool_profiles
from app.agent.program import FleetAgent
from app.agent.tool_registry import ToolMetadata, ToolRegistry
from app.agent.tooling import create_dspy_tool
from app.agui.event_bus import RunEventBus
from app.agui.live_coordinator import LiveDSPyCoordinator
from tests.helpers.scripted_lm import (
    StreamingScriptedLM,
    router_call,
    synthesis_call,
)

CTX = AgentRunContext(
    thread_id="thread-stream",
    run_id="run-stream",
    assistant_message_id="assistant-stream",
)


def _lookup_tool(calls: list[str] | None = None) -> dspy.Tool:
    def lookup(query: str) -> str:
        """Look up one deterministic value."""
        if calls is not None:
            calls.append(query)
        return f"found:{query}"

    return create_dspy_tool(lookup)


def _routed_engine(steps: list[Any], *, lm_cls: type = StreamingScriptedLM):
    def lookup(query: str) -> str:
        """Look up one deterministic value."""
        return f"found:{query}"

    registry = ToolRegistry(
        [(lookup, ToolMetadata(name="lookup", capability="retrieval"))]
    )
    profiles = build_tool_profiles(registry)
    return DspyAgentEngine(
        program_factory=lambda: FleetAgent(tool_profiles=profiles, max_iters=3),
        lm=lm_cls(steps),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
    )


def _stream_steps(answer: str = "Use the streaming seam.") -> list[Any]:
    return [
        router_call("research"),
        [{"name": "lookup", "args": {"query": "streaming"}}],
        {"calls": [], "content": '{"next_thought": "enough evidence"}'},
        synthesis_call(
            answer=answer, summary="Routed, gathered evidence, synthesized."
        ),
    ]


async def test_routed_program_streams_synthesis_tokens() -> None:
    engine = _routed_engine(_stream_steps())

    updates = [
        update
        async for update in engine.stream(
            user_request="look it up", history=None, context=CTX
        )
    ]

    kinds = [update.kind for update in updates]
    # Tokens first (both fields), then the settled fields, then the result.
    assert kinds[0] == "token"
    assert kinds.count("token") >= 2
    assert kinds[-2:] == ["final_fields", "result"]

    answer_text = "".join(
        update.delta
        for update in updates
        if update.kind == "token" and update.stream_field == "answer"
    )
    summary_text = "".join(
        update.delta
        for update in updates
        if update.kind == "token" and update.stream_field == "process_summary"
    )
    # The streamed fields reconstruct exactly: no adapter boilerplate leaks.
    assert answer_text == "Use the streaming seam."
    assert summary_text == "Routed, gathered evidence, synthesized."

    final = updates[-1].result
    assert final is not None
    assert final.status == "completed"
    assert final.answer == "Use the streaming seam."
    assert final.termination_reason == "synthesis"
    assert final.history is not None


async def test_non_streaming_lm_falls_back_to_settled_fields() -> None:
    """A gateway that cannot stream still gets the full run, just unstreamed."""
    from tests.helpers.scripted_lm import ScriptedLM

    engine = _routed_engine(_stream_steps(), lm_cls=ScriptedLM)

    updates = [
        update
        async for update in engine.stream(
            user_request="look it up", history=None, context=CTX
        )
    ]

    assert [update.kind for update in updates] == ["final_fields", "result"]
    assert updates[-1].result is not None
    assert updates[-1].result.status == "completed"


async def test_streamed_secret_is_never_emitted_even_when_split() -> None:
    """A secret split across synthesis deltas must never reach the stream."""
    # The key is longer than the scripted chunk size, so it straddles deltas.
    answer = "The gateway key is sk-ant-1234567890abcdef1234 and that is the risk."
    engine = _routed_engine(_stream_steps(answer))

    updates = [
        update
        async for update in engine.stream(
            user_request="look it up", history=None, context=CTX
        )
    ]

    streamed = "".join(
        update.delta
        for update in updates
        if update.kind == "token" and update.stream_field == "answer"
    )
    assert "sk-ant-1234567890abcdef1234" not in streamed
    assert "sk-ant-" not in streamed
    # The settled answer is masked, and the streamed text matches it exactly
    # (the scrubber releases the held-back tail on flush).
    final = updates[-1].result
    assert final is not None
    assert final.answer == ("The gateway key is [redacted] and that is the risk.")
    assert streamed == final.answer


async def test_approval_pause_in_streamed_evidence_loop_interrupts() -> None:
    """A gated tool in the evidence loop pauses the streamed run cleanly."""
    from app.agent.approval import ApprovalRegistry
    from app.agent.tool_registry import ToolMetadata as TM
    from tests.helpers.scripted_lm import ScriptedLM

    def write(path: str, content: str) -> str:
        """Write a test workspace file."""
        raise AssertionError("gated tool must not run before approval")

    write_tool = create_dspy_tool(write)
    registry = ToolRegistry(
        [
            (
                write_tool,
                TM(
                    name="write",
                    capability="workspace_write",
                    read_only=False,
                    idempotent=False,
                    parallelizable=False,
                    requires_approval=True,
                ),
            )
        ]
    )
    profiles = build_tool_profiles(registry)
    engine = DspyAgentEngine(
        program_factory=lambda: FleetAgent(
            tool_profiles=profiles,
            max_iters=3,
            approval_policy=registry.approval_policy(),
        ),
        lm=ScriptedLM(
            [
                router_call("workspace_write"),
                [{"name": "write", "args": {"path": "notes.txt", "content": "s"}}],
            ]
        ),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
        approval_registry=ApprovalRegistry(),
    )

    updates = [
        update
        async for update in engine.stream(
            user_request="save this", history=None, context=CTX
        )
    ]

    assert [update.kind for update in updates][-1] == "result"
    result = updates[-1].result
    assert result is not None
    assert result.status == "interrupted"
    assert result.termination_reason == "approval_required"
    assert len(result.interrupts) == 1
    # No synthesis tokens are emitted for a paused run.
    assert not [u for u in updates if u.kind == "token"]


async def test_streamed_resume_completes_after_approval() -> None:
    """An approved resume streams the synthesis after the evidence continues."""
    from ag_ui.core import ResumeEntry

    from app.agent.approval import ApprovalRegistry

    def write(path: str, content: str) -> str:
        """Write a test workspace file."""
        return "write completed"

    calls: list[tuple[str, str]] = []

    def tracked_write(path: str, content: str) -> str:
        """Write a test workspace file."""
        calls.append((path, content))
        return "write completed"

    tracked = create_dspy_tool(tracked_write, name="write")
    registry = ToolRegistry(
        [
            (
                tracked,
                ToolMetadata(
                    name="write",
                    capability="workspace_write",
                    read_only=False,
                    idempotent=False,
                    parallelizable=False,
                    requires_approval=True,
                ),
            )
        ]
    )
    profiles = build_tool_profiles(registry)
    approvals = ApprovalRegistry()
    engine = DspyAgentEngine(
        program_factory=lambda: FleetAgent(
            tool_profiles=profiles,
            max_iters=3,
            approval_policy=registry.approval_policy(),
        ),
        lm=StreamingScriptedLM(
            [
                router_call("workspace_write"),
                [{"name": "write", "args": {"path": "notes.txt", "content": "s"}}],
                {"calls": [], "content": '{"next_thought": "evidence done"}'},
                synthesis_call(answer="Saved.", summary="Wrote the file."),
            ]
        ),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
        approval_registry=approvals,
    )

    first = [
        update
        async for update in engine.stream(
            user_request="save this", history=None, context=CTX
        )
    ]
    result = first[-1].result
    assert result is not None and result.status == "interrupted"
    interrupt = result.interrupts[0]

    second = [
        update
        async for update in engine.stream(
            user_request="save this",
            history=None,
            context=CTX,
            resume=[
                ResumeEntry.model_validate(
                    {
                        "interruptId": interrupt.id,
                        "status": "resolved",
                        "payload": {"approved": True},
                    }
                )
            ],
        )
    ]
    final = second[-1].result
    assert final is not None and final.status == "completed"
    assert final.answer == "Saved."
    assert calls == [("notes.txt", "s")]
    answer_text = "".join(
        u.delta for u in second if u.kind == "token" and u.stream_field == "answer"
    )
    assert answer_text == "Saved."


def _coordinator_stream(engine: DspyAgentEngine, run_id: str):
    def builder(bus: RunEventBus, *, thread_id: str):
        del bus, thread_id
        return engine

    payload: dict[str, Any] = {
        "threadId": "thread-stream",
        "runId": run_id,
        "state": None,
        "messages": [{"id": f"user-{run_id}", "role": "user", "content": "go"}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }
    return LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(payload),
        engine_builder=builder,
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )


async def _false() -> bool:
    return False


async def test_coordinator_emits_incremental_answer_tokens_once() -> None:
    engine = _routed_engine(_stream_steps())

    events = [
        json.loads(chunk.removeprefix("data: ").strip())
        async for chunk in _coordinator_stream(engine, "run-stream-sse")
    ]

    # Answer text arrives as incremental content events DURING the run (before
    # RUN_FINISHED), and the joined text equals the answer exactly once.
    content_events = [e for e in events if e["type"] == "TEXT_MESSAGE_CONTENT"]
    joined = "".join(e["delta"] for e in content_events)
    assert joined == "Use the streaming seam."
    assert events[-1]["type"] == "RUN_FINISHED"
    finished_index = len(events) - 1
    assert all(events.index(e) < finished_index for e in content_events), (
        "tokens must stream before the run finishes"
    )
    # The summary tokens surface as synthesis-step state deltas.
    assert any(e["type"] == "STATE_DELTA" for e in events)


def test_evidence_json_extracts_live_and_round_tripped_history_events() -> None:
    """The synthesizer must see tool results in both event shapes.

    Live in-process events carry ToolCalls pydantic objects; histories
    restored from persistence carry plain dicts. The original renderer only
    matched dict messages with a ``role`` key that dspy never emits, so
    streamed runs synthesized from empty evidence.
    """
    from dspy.adapters.types.tool import ToolCallResults, ToolCalls

    from app.agent.program import _evidence_json

    tool_calls = ToolCalls.model_validate(
        {"tool_calls": [{"id": "c1", "name": "probe", "args": {"query": "q"}}]}
    )
    results = ToolCallResults.from_tool_calls_and_values(
        tool_calls, ["probe returned 42"], [False]
    )
    live = dspy.History(
        messages=[
            {
                "user_request": "look it up",
                "next_thought": "gather",
                "tool_calls": tool_calls.model_copy(
                    update={"tool_call_results": results}
                ),
            }
        ]
    )
    live_text = _evidence_json(live)
    assert '"probe"' in live_text
    assert "probe returned 42" in live_text

    round_tripped = dspy.History.model_validate(
        {
            "messages": [
                {
                    "user_request": "look it up",
                    "next_thought": "gather",
                    "tool_calls": {
                        "tool_calls": [
                            {"id": "c1", "name": "probe", "args": {"query": "q"}}
                        ],
                        "tool_call_results": [
                            {
                                "name": "probe",
                                "value": "probe returned 42",
                                "is_error": False,
                            }
                        ],
                    },
                }
            ]
        }
    )
    assert _evidence_json(round_tripped) == live_text


async def test_continuation_turn_synthesizes_from_prior_evidence() -> None:
    """Turn two's synthesis sees turn one's tool results (streamed path)."""
    import app.agent.program as program_module
    from app.agent.engine import AgentRunContext, DspyAgentEngine
    from app.agent.factory import build_tool_profiles
    from app.agent.program import FleetAgent
    from app.agent.tool_registry import ToolMetadata, ToolRegistry
    from tests.helpers.scripted_lm import ScriptedLM, router_call, synthesis_call

    def probe(query: str) -> str:
        """Return one deterministic value."""
        return "report file AG-UI-State-Sync-How-It-Works.md written"

    registry = ToolRegistry(
        [(probe, ToolMetadata(name="probe", capability="retrieval"))]
    )
    ctx = AgentRunContext(
        thread_id="t-cont", run_id="r-cont", assistant_message_id="m-cont"
    )
    captured: list[str] = []
    original = program_module._evidence_json

    def spy(history: object, **kwargs: object) -> str:
        value = original(history, **kwargs)  # type: ignore[arg-type]
        captured.append(value)
        return value

    program_module._evidence_json = spy
    try:
        engine = DspyAgentEngine(
            program_factory=lambda: FleetAgent(
                tool_profiles=build_tool_profiles(registry), max_iters=4
            ),
            lm=ScriptedLM(
                [
                    router_call("research"),
                    [{"name": "probe", "args": {"query": "report"}}],
                    {"calls": [], "content": '{"next_thought": "done"}'},
                    synthesis_call(answer="Report written.", summary="Gathered."),
                    router_call("direct"),
                    {"calls": [], "content": '{"next_thought": "recall prior turn"}'},
                    synthesis_call(
                        answer="It was AG-UI-State-Sync-How-It-Works.md.",
                        summary="Recalled.",
                    ),
                ]
            ),  # type: ignore[arg-type]
            adapter=dspy.JSONAdapter(use_native_function_calling=True),
        )
        first = [
            update
            async for update in engine.stream(
                user_request="write the report", history=None, context=ctx
            )
        ]
        first_result = first[-1].result
        assert first_result is not None and first_result.status == "completed"
        assert "AG-UI-State-Sync" in captured[0]

        second = [
            update
            async for update in engine.stream(
                user_request="what did you name that file?",
                history=first_result.history,
                context=ctx,
            )
        ]
        second_result = second[-1].result
        assert second_result is not None and second_result.status == "completed"
        assert "AG-UI-State-Sync" in captured[1]
    finally:
        program_module._evidence_json = original
