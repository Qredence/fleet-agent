import json
from collections.abc import AsyncIterator

from ag_ui.core import RunAgentInput

from app.agui.run import RunCoordinator
from app.services.mock_run import load_fixture


def make_input() -> RunAgentInput:
    return RunAgentInput.model_validate(
        {
            "threadId": "t-client",
            "runId": "r-client",
            "state": None,
            "messages": [{"id": "m1", "role": "user", "content": "hi"}],
            "tools": [],
            "context": [],
            "forwardedProps": None,
        }
    )


async def collect(stream: AsyncIterator[str]) -> list[dict]:
    events: list[dict] = []
    async for chunk in stream:
        events.append(json.loads(chunk.removeprefix("data: ").strip()))
    return events


def coordinator(events) -> AsyncIterator[str]:
    return RunCoordinator(time_scale=0).stream(
        input_data=make_input(),
        events=events,
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )


async def _false() -> bool:
    return False


async def test_fixture_ids_are_rebound_to_client_ids():
    events = await collect(coordinator(load_fixture("successful-run")))
    run_started = events[0]
    assert run_started["type"] == "RUN_STARTED"
    assert run_started["threadId"] == "t-client"
    assert run_started["runId"] == "r-client"
    tool_start = next(event for event in events if event["type"] == "TOOL_CALL_START")
    tool_result = next(event for event in events if event["type"] == "TOOL_CALL_RESULT")
    text_start = next(
        event for event in events if event["type"] == "TEXT_MESSAGE_START"
    )
    assert tool_start["parentMessageId"] == "msg-1-r-client"
    assert tool_result["messageId"] == "msg-tool-tc-1-r-client"
    assert text_start["messageId"] == "msg-1-r-client"


async def test_terminal_event_exactly_once_when_fixture_lacks_it():
    only_start = [load_fixture("successful-run")[0]]  # RUN_STARTED only
    events = await collect(coordinator(only_start))
    types = [e["type"] for e in events]
    assert types == ["RUN_STARTED", "RUN_FINISHED"]


async def test_terminal_event_stops_late_fixture_events():
    fixture = load_fixture("successful-run")
    fixture.append(fixture[0])
    events = await collect(coordinator(fixture))
    types = [event["type"] for event in events]
    assert types.count("RUN_FINISHED") == 1
    assert types[-1] == "RUN_FINISHED"


async def test_disconnect_stops_stream_before_later_events():
    calls = 0

    async def disconnect_after_first() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    stream = RunCoordinator(time_scale=0).stream(
        input_data=make_input(),
        events=load_fixture("successful-run"),
        accept="text/event-stream",
        is_disconnected=disconnect_after_first,
    )
    events = await collect(stream)
    assert [e["type"] for e in events] == ["RUN_STARTED"]


async def test_broken_event_source_yields_safe_run_error():
    def boom():
        yield load_fixture("successful-run")[0]
        raise RuntimeError("sensitive implementation detail: provider key leak")

    stream = RunCoordinator(time_scale=0).stream(
        input_data=make_input(),
        events=boom(),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    events = await collect(stream)
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "internal_error"
    assert events[-1]["message"] == "The agent run failed."
    assert "provider key" not in json.dumps(events)


async def test_timed_events_preserve_order_with_zero_time_scale():
    events = await collect(coordinator(load_fixture("tool-error-run")))
    types = [e["type"] for e in events]
    assert types[-1] == "RUN_FINISHED"
    assert types.index("TEXT_MESSAGE_START") < types.index("TOOL_CALL_RESULT")


async def test_bind_run_ids_rewrites_custom_event_ids_without_mutating_source():
    from ag_ui.core import CustomEvent, EventType

    from app.agui.run import TimedEvent

    source_value = {"type": "artifact", "runId": "fixture-run", "messageId": "msg-1"}
    timed = [
        TimedEvent(
            at_ms=0,
            event=CustomEvent(
                type=EventType.CUSTOM, name="artifact", value=source_value
            ),
        )
    ]
    events = await collect(coordinator(timed))
    custom = next(event for event in events if event["type"] == "CUSTOM")
    assert custom["value"]["runId"] == "r-client"
    assert custom["value"]["messageId"] == "msg-1-r-client"
    assert source_value == {
        "type": "artifact",
        "runId": "fixture-run",
        "messageId": "msg-1",
    }


async def test_run_coordinator_timeout_emits_agent_timeout_and_records_metrics():
    from ag_ui.core import EventType, RunStartedEvent

    from app.agui.run import TimedEvent
    from app.services.metrics import MetricsRegistry

    registry = MetricsRegistry()
    slow_events = [
        TimedEvent(
            at_ms=500,
            event=RunStartedEvent(
                type=EventType.RUN_STARTED, thread_id="t-src", run_id="r-src"
            ),
        )
    ]
    stream = RunCoordinator(time_scale=1.0).stream(
        input_data=make_input(),
        events=slow_events,
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
        run_timeout_s=0.02,
        metrics=registry,
    )
    events = await collect(stream)
    assert len(events) == 1
    assert events[0]["type"] == "RUN_ERROR"
    assert events[0]["code"] == "agent_timeout"
    snapshot = registry.snapshot()
    assert snapshot["counters"]["agent_runs_total"] == 1
    assert snapshot["counters"]["agent_run_errors_total"] == 1
    assert snapshot["durations"]["agent_run_duration_ms"]["count"] == 1
