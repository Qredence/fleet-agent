import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.agent import _reservation_http_error
from app.main import create_app
from app.services.run_persistence import ReservationErrorCode, RunReservationError

THREAD_ID = "thread-abc"
RUN_ID = "run-xyz"


def run_input(text: str = "Hello") -> dict:
    return {
        "threadId": THREAD_ID,
        "runId": RUN_ID,
        "state": None,
        "messages": [{"id": "m-user", "role": "user", "content": text}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }


@pytest.fixture
def app():
    return create_app()


async def post_agent(app, text: str = "Hello") -> tuple[int, dict, str]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/agent",
            json=run_input(text),
            headers={"Accept": "text/event-stream"},
        )
        return response.status_code, dict(response.headers), response.text


def test_reservation_conflicts_use_fixed_public_details() -> None:
    for code in ReservationErrorCode:
        error = _reservation_http_error(RunReservationError(code))
        assert "driver" not in str(error.detail).lower()
        assert "password" not in str(error.detail).lower()
        assert str(code.value) not in str(error.detail)


def parse_sse(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


async def test_endpoint_returns_sse_with_streaming_headers(app):
    status, headers, _ = await post_agent(app)
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"


async def test_invalid_body_gets_validation_error(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/agent", json={"nope": True})
    assert response.status_code == 422


async def test_successful_run_event_sequence(app):
    _, _, body = await post_agent(app)
    events = parse_sse(body)
    types = [event["type"] for event in events]

    # Lifecycle framing and ordering.
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert types.count("RUN_FINISHED") + types.count("RUN_ERROR") == 1

    # Snapshot always precedes its deltas.
    first_snapshot = types.index("STATE_SNAPSHOT")
    first_delta = types.index("STATE_DELTA")
    assert first_snapshot < first_delta

    # Tool call lifecycle is complete.
    for cycle in ("START", "ARGS", "END", "RESULT"):
        assert f"TOOL_CALL_{cycle}" in types

    # Final assistant text streams between lifecycle events.
    assert (
        types.index("TEXT_MESSAGE_START")
        < types.index("TEXT_MESSAGE_CONTENT")
        < types.index("TEXT_MESSAGE_END")
    )

    # The client's thread/run ids are rebound onto fixture placeholders.
    for event in events:
        if "threadId" in event:
            assert event["threadId"] == THREAD_ID
        if "runId" in event:
            assert event["runId"] == RUN_ID

    # Text chunks concatenate into the full answer.
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "JSON snapshot" in text


async def test_tool_error_run_recovers(app):
    _, _, body = await post_agent(app, text="trigger tool error please")
    events = parse_sse(body)
    types = [event["type"] for event in events]

    assert types[-1] == "RUN_FINISHED"
    results = [e for e in events if e["type"] == "TOOL_CALL_RESULT"]
    assert len(results) == 2

    deltas = [e for e in events if e["type"] == "STATE_DELTA"]
    tool_ops = [op for d in deltas for op in d["delta"] if op["path"] == "/toolCalls/-"]
    statuses = {op["value"]["status"] for op in tool_ops}
    assert statuses == {"failed", "completed"}


async def test_forced_submit_run_emits_run_error(app):
    _, _, body = await post_agent(app, text="give me no output")
    events = parse_sse(body)
    types = [event["type"] for event in events]

    assert types[-1] == "RUN_ERROR"
    assert "RUN_FINISHED" not in types
    error = events[-1]
    assert error["code"] == "agent_no_output"
    # Public message only — no implementation details.
    assert "Traceback" not in error["message"]
    assert "Exception" not in error["message"]
    # No assistant text was produced.
    assert "TEXT_MESSAGE_START" not in types
