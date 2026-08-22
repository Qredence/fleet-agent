import json

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings
from tests.conftest import requires_db
from tests.helpers.scripted_lm import submit_call
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


async def post(app, body: dict):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/agent", json=body)


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
    assert types[1] == "STATE_SNAPSHOT"
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
