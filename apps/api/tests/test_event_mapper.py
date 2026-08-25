from app.agui.event_mapper import map_domain_event, map_tool_event
from app.agui.trace_reducer import TraceReducer
from app.contracts.domain import (
    InlineDataEvent,
    SourceDiscovered,
    SourceResult,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)


def ops(value: dict) -> list:
    return [{"op": "add", "path": "/toolCalls/-", "value": value}]


def test_tool_started_maps_to_call_lifecycle_plus_delta():
    event = ToolStarted(
        tool_call_id="tool_1", name="search_docs", input_preview='{"q": "x"}'
    )
    events = map_tool_event(
        event, tools_message_id="msg-tools-r1", state_delta_ops=ops({"id": "tool_1"})
    )
    types = [e.type.value for e in events]
    assert types[:3] == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"]
    assert events[0].tool_call_id == "tool_1"
    assert events[0].parent_message_id == "msg-tools-r1"
    assert events[1].delta == '{"q": "x"}'
    assert events[3].type.value == "STATE_DELTA"


def test_tool_completed_maps_result_linked_to_same_ids():
    event = ToolCompleted(
        tool_call_id="tool_1", name="search_docs", output_preview="ok", duration_ms=5
    )
    events = map_tool_event(event, tools_message_id="msg-tools-r1", state_delta_ops=[])
    [result] = [e for e in events if e.type.value == "TOOL_CALL_RESULT"]
    assert result.message_id == "msg-tools-r1"
    assert result.tool_call_id == "tool_1"
    assert result.content == "ok"


def test_tool_failed_maps_public_error_only():
    event = ToolFailed(
        tool_call_id="tool_1",
        name="search_docs",
        error_message="The search_docs tool call failed.",
        duration_ms=5,
    )
    events = map_tool_event(event, tools_message_id="msg-tools-r1", state_delta_ops=[])
    [result] = [e for e in events if e.type.value == "TOOL_CALL_RESULT"]
    assert result.content == "The search_docs tool call failed."


def test_long_results_are_truncated_for_the_thread():
    event = ToolCompleted(
        tool_call_id="tool_1",
        name="search_docs",
        output_preview="y" * 5000,
        duration_ms=1,
    )
    events = map_tool_event(event, tools_message_id="m", state_delta_ops=[])
    [result] = [e for e in events if e.type.value == "TOOL_CALL_RESULT"]
    assert len(result.content) <= 2001


def test_inline_events_are_custom_parts_and_do_not_change_public_state():
    reducer = TraceReducer(thread_id="thread-1", run_id="run-1")
    event = InlineDataEvent(
        name="agent-progress",
        value={
            "schemaVersion": 1,
            "steps": [{"id": "planning", "label": "Planning", "status": "running"}],
            "activeIndex": 0,
        },
    )

    events = map_domain_event(
        event,
        tools_message_id="msg-tools-run-1",
        reducer=reducer,
    )

    assert [mapped.type.value for mapped in events] == ["CUSTOM"]
    assert events[0].name == "agent-progress"
    assert events[0].value["schemaVersion"] == 1
    assert reducer.state["steps"][0]["id"] == "step-understand"


def test_source_events_only_update_authoritative_state():
    reducer = TraceReducer(thread_id="thread-1", run_id="run-1")
    source = SourceResult(
        id="w1",
        title="Official docs",
        source_type="web",
        uri="https://example.com/secret-path",
        excerpt="untrusted excerpt",
    )

    first = map_domain_event(
        SourceDiscovered(tool_call_id="tool-1", source=source),
        tools_message_id="msg-tools-run-1",
        reducer=reducer,
    )
    second = map_domain_event(
        SourceDiscovered(tool_call_id="tool-2", source=source),
        tools_message_id="msg-tools-run-1",
        reducer=reducer,
    )

    assert not [event for event in first if event.type.value == "CUSTOM"]
    assert not [event for event in second if event.type.value == "CUSTOM"]
