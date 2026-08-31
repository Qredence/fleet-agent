import json

import dspy
from httpx import ASGITransport, AsyncClient

from app.agent.approval import ApprovalRegistry
from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import DspyAgentEngine
from app.agent.program import FleetAgent
from app.agent.tool_registry import ToolMetadata
from app.agent.tooling import create_dspy_tool
from app.agui.event_bus import RunEventBus
from app.main import create_app
from app.settings import Settings
from tests.conftest import requires_db
from tests.helpers.scripted_lm import ScriptedLM, submit_call
from tests.test_live_coordinator import scripted_builder

pytestmark = requires_db


def run_input(thread_id: str, text: str = "Hello engine") -> dict:
    return {
        "threadId": thread_id,
        "runId": "run-e2e",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }


async def seed_thread(app) -> str:
    from app.persistence.repositories import ProjectsRepository, ThreadsRepository

    project = await ProjectsRepository(app.state.db_sessions).create(name="E2E")
    thread = await ThreadsRepository(app.state.db_sessions).create(
        project_id=project.id, title="Thread"
    )
    return thread.id


async def post(app, body: dict, *, headers: dict[str, str] | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/agent", json=body, headers=headers)


async def test_engine_mode_streams_live_run_through_http(db_sessions):
    app = create_app()
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)
    app.state.db_sessions = db_sessions
    app.state.engine_builder = scripted_builder(
        [
            [{"name": "search_docs", "args": {"query": "hello"}}],
            [submit_call(answer="Live engine answer.")],
        ]
    )
    thread_id = await seed_thread(app)

    response = await post(app, run_input(thread_id))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    types = [e["type"] for e in events]
    assert types[0] == "RUN_STARTED"
    assert types[1] == "TEXT_MESSAGE_START"
    assert types[2] == "STATE_SNAPSHOT"
    assert "TOOL_CALL_START" in types
    assert types[-1] == "RUN_FINISHED"

    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "Live engine answer." in text


async def test_engine_mode_rejects_unknown_thread(db_sessions):
    app = create_app()
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)
    app.state.db_sessions = db_sessions

    response = await post(app, run_input("thread-does-not-exist"))
    assert response.status_code == 404


async def test_engine_mode_rejects_invalid_provider_headers():
    app = create_app()
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)

    response = await post(
        app,
        run_input("thread-does-not-matter"),
        headers={"X-OpenRouter-Model": "vendor/model"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "The selected provider settings are invalid."}


async def test_fixtures_mode_remains_default():
    app = create_app()
    assert app.state.settings.agent_mode == "fixtures"

    response = await post(app, run_input("any-thread-id"))
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    # Fixture replay, keyword-routed: default fixture ends with RUN_FINISHED.
    assert events[-1]["type"] == "RUN_FINISHED"


async def test_engine_mode_approval_resume_uses_native_events_and_persists_safe_state(
    db_sessions,
):
    app = create_app()
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)
    app.state.db_sessions = db_sessions
    registry = ApprovalRegistry()
    calls: list[tuple[str, str]] = []

    def write(path: str, content: str) -> str:
        """Write a test file."""
        calls.append((path, content))
        return "write completed"

    tool = create_dspy_tool(write, name="write")
    policy = {
        "write": ToolMetadata(
            name="write",
            capability="workspace_write",
            read_only=False,
            idempotent=False,
            parallelizable=False,
            requires_approval=True,
        )
    }
    builder_calls = 0

    def builder(
        bus: RunEventBus,
        *,
        thread_id: str,
        provider_override=None,
    ) -> DspyAgentEngine:
        nonlocal builder_calls
        del thread_id
        steps = (
            [[{"name": "write", "args": {"path": "notes.txt", "content": "secret"}}]]
            if builder_calls == 0
            else [[submit_call(answer="saved")]]
        )
        builder_calls += 1
        lifecycle = AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)

        def program_factory() -> FleetAgent:
            return FleetAgent(
                tools=[tool],
                max_iters=4,
                approval_policy=policy,
                lifecycle=lifecycle,
            )

        return DspyAgentEngine(
            program_factory=program_factory,
            lm=ScriptedLM(steps),  # type: ignore[arg-type]
            adapter=dspy.JSONAdapter(),
            approval_registry=registry,
            provider_override=provider_override,
            lifecycle=lifecycle,
        )

    app.state.engine_builder = builder
    thread_id = await seed_thread(app)
    user = {"id": "user-approval-http", "role": "user", "content": "save"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first_response = await client.post(
            "/api/agent",
            json={
                "threadId": thread_id,
                "runId": "run-approval-http",
                "state": None,
                "messages": [user],
                "tools": [],
                "context": [],
                "forwardedProps": None,
            },
        )
        first_events = [
            json.loads(line.removeprefix("data: "))
            for line in first_response.text.splitlines()
            if line.startswith("data: ")
        ]
        interrupt = next(
            event["outcome"]["interrupts"][0]
            for event in first_events
            if event["type"] == "RUN_FINISHED"
        )
        assistant = {
            "id": "msg-run-approval-http",
            "role": "assistant",
            "content": "Approval is pending.",
        }
        second_response = await client.post(
            "/api/agent",
            json={
                "threadId": thread_id,
                "runId": "run-approval-http-resume",
                "state": None,
                "messages": [user, assistant],
                "tools": [],
                "context": [],
                "forwardedProps": None,
                "resume": [
                    {
                        "interruptId": interrupt["id"],
                        "status": "resolved",
                        "payload": {"approved": True},
                    }
                ],
            },
        )

    second_events = [
        json.loads(line.removeprefix("data: "))
        for line in second_response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_events[-1]["outcome"]["type"] == "interrupt"
    assert not any(event["type"] == "RUN_ERROR" for event in first_events)
    result_events = [
        event for event in second_events if event["type"] == "TOOL_CALL_RESULT"
    ]
    assert len(result_events) == 1
    assert result_events[0]["toolCallId"] == interrupt["toolCallId"]
    assert any(event["type"] == "RUN_FINISHED" for event in second_events)
    assert calls == [("notes.txt", "secret")]
    public = first_response.text + second_response.text
    # The approval interrupt carries a bounded preview naming the gated
    # action's target; the argument values (the file content) never reach
    # the browser.
    assert "write notes.txt (6 chars)" in public
    assert "secret" not in public

    from app.persistence.repositories import DspyHistoriesRepository, RunsRepository

    first_run = await RunsRepository(db_sessions).get("run-approval-http")
    second_run = await RunsRepository(db_sessions).get("run-approval-http-resume")
    assert first_run is not None and first_run.status == "interrupted"
    assert second_run is not None and second_run.status == "completed"
    assert await DspyHistoriesRepository(db_sessions).get(thread_id) is not None
