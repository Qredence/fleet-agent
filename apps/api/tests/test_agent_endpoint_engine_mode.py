import json

import dspy
from httpx import ASGITransport, AsyncClient

from app.agent.engine import DspyAgentEngine
from app.agent.event_bus import RunEventBus
from app.agent.program import FleetAgent
from app.main import create_app
from app.settings import Settings
from tests.conftest import requires_db
from tests.helpers.scripted_lm import (
    ScriptedLM,
    evidence_end,
    fixed_route_agent,
    submit_call,
    synthesis_call,
)
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


async def test_engine_mode_is_the_default():
    """The product default must be the live DSPy bridge, not the mock replay."""
    app = create_app()
    assert app.state.settings.agent_mode == "engine"


async def test_fixtures_mode_is_an_explicit_opt_in():
    app = create_app()
    app.state.settings = Settings(agent_mode="fixtures", llm_api_key=None)

    response = await post(app, run_input("any-thread-id"))
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    # Fixture replay, keyword-routed: default fixture ends with RUN_FINISHED.
    assert events[-1]["type"] == "RUN_FINISHED"


async def test_run_approval_travels_with_the_request(db_sessions):
    """Approval is decided per request, before the model ever sees a tool.

    The endpoint must forward the request's approval decision to the engine
    builder, so a gated tool is withheld unless this run authorized it.
    """
    app = create_app()
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)
    app.state.db_sessions = db_sessions
    seen: list[frozenset[str] | None] = []

    def builder(
        bus: RunEventBus,
        *,
        thread_id: str,
        provider_override=None,
        approved: frozenset[str] | None = None,
    ) -> DspyAgentEngine:
        del thread_id, provider_override
        seen.append(approved)

        def program_factory() -> FleetAgent:
            return fixed_route_agent(
                "direct", tool_profiles={"direct": []}, max_iters=2
            )

        return DspyAgentEngine(
            program_factory=program_factory,
            lm=ScriptedLM([evidence_end(), synthesis_call(answer="ok")]),  # type: ignore[arg-type]
            adapter=dspy.JSONAdapter(),
        )

    app.state.engine_builder = builder
    thread_id = await seed_thread(app)

    unapproved = run_input(thread_id)
    unapproved["runId"] = "run-unapproved"
    approved = run_input(thread_id)
    approved["runId"] = "run-approved"
    approved["forwardedProps"] = {"approvedTools": ["write"]}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/agent", json=unapproved, headers={"Accept": "text/event-stream"}
        )
        second = await client.post(
            "/api/agent", json=approved, headers={"Accept": "text/event-stream"}
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert seen[0] is None, "no approval in the request must mean no approval"
    assert seen[1] == frozenset({"write"})


async def test_wildcard_approval_is_accepted(db_sessions):
    app = create_app()
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)
    app.state.db_sessions = db_sessions
    seen: list[frozenset[str] | None] = []

    def builder(
        bus: RunEventBus,
        *,
        thread_id: str,
        provider_override=None,
        approved: frozenset[str] | None = None,
    ) -> DspyAgentEngine:
        del thread_id, provider_override
        seen.append(approved)

        def program_factory() -> FleetAgent:
            return fixed_route_agent(
                "direct", tool_profiles={"direct": []}, max_iters=2
            )

        return DspyAgentEngine(
            program_factory=program_factory,
            lm=ScriptedLM([evidence_end(), synthesis_call(answer="ok")]),  # type: ignore[arg-type]
            adapter=dspy.JSONAdapter(),
        )

    app.state.engine_builder = builder
    thread_id = await seed_thread(app)
    body = run_input(thread_id)
    body["runId"] = "run-wildcard"
    body["forwardedProps"] = {"approvedTools": "*"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/agent", json=body, headers={"Accept": "text/event-stream"}
        )

    assert response.status_code == 200
    assert seen == [frozenset({"*"})]
