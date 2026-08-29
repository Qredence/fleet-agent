"""Hardening: auth, size limits, duplicate-run idempotency, concurrency cap,
run timeout, cancellation settling, rate-limit mapping, orphan reconciliation,
and metrics."""

import json

import pytest
from ag_ui.core import RunAgentInput
from httpx import ASGITransport, AsyncClient

from app.agui.live_coordinator import LiveDSPyCoordinator
from app.main import create_app
from app.persistence.repositories import (
    ProjectsRepository,
    RunsRepository,
    ThreadsRepository,
)
from app.settings import Settings
from tests.conftest import make_test_app, requires_db
from tests.helpers.scripted_lm import submit_call
from tests.test_live_coordinator import scripted_builder

pytestmark = requires_db


def run_input(thread_id: str, run_id: str = "run-h", text: str = "hi") -> dict:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }


async def seed_thread(app) -> str:
    project = await ProjectsRepository(app.state.db_sessions).create(name="H")
    thread = await ThreadsRepository(app.state.db_sessions).create(
        project_id=project.id, title="T"
    )
    return thread.id


async def post(app, body, headers=None):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/agent", json=body, headers=headers or {})


# --- auth + request size ------------------------------------------------------


async def test_api_key_required_when_configured():
    app = make_test_app(api_key="secret-1")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.post("/api/agent", json=run_input("t"))
        allowed = await client.post(
            "/api/agent", json=run_input("t"), headers={"x-api-key": "secret-1"}
        )
        health = await client.get("/health")
    assert denied.status_code == 401
    assert allowed.status_code != 401  # fixtures mode streams
    assert health.status_code == 200


async def test_request_size_cap_returns_413():
    app = make_test_app(max_body_bytes="16")
    response = await post(app, run_input("t", text="x" * 100))
    assert response.status_code == 413


async def test_request_id_header_present():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.headers.get("x-request-id")


# --- duplicate run + concurrency cap ------------------------------------------


async def test_duplicate_run_id_returns_409(db_sessions):
    app = create_app()
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)
    app.state.db_sessions = db_sessions
    app.state.engine_builder = scripted_builder([[submit_call()]])
    thread_id = await seed_thread(app)

    first = await post(app, run_input(thread_id, "run-dup"))
    assert first.status_code == 200

    second = await post(app, run_input(thread_id, "run-dup"))
    assert second.status_code == 409


@pytest.fixture()
def slow_engine_app(db_sessions):
    """Engine-mode app whose scripted engine takes a bounded sleep — holds the
    run semaphore long enough for saturation assertions."""
    app = make_test_app(agent_mode="engine", max_concurrent_runs="1")
    app.state.db_sessions = db_sessions

    import time as _time

    import dspy

    from app.agent.engine import DspyAgentEngine
    from app.agent.instrumented import instrument_tool
    from app.agent.signature import AgentSignature
    from tests.helpers.scripted_lm import ScriptedLM, submit_call

    def encoder_side(query: str) -> str:
        """Blocks so the first run holds the semaphore."""
        _time.sleep(0.4)
        return "ok"

    def build(bus, *, thread_id: str = "t"):
        tools = [instrument_tool(encoder_side, bus)]

        def factory():
            return dspy.ReActV2(AgentSignature, tools=tools, max_iters=3)

        return DspyAgentEngine(
            program_factory=factory,
            lm=ScriptedLM(
                [[{"name": "encoder_side", "args": {"query": "x"}}], [submit_call()]]
            ),
            adapter=dspy.JSONAdapter(),
        )

    app.state.engine_builder = build
    return app


async def test_concurrency_cap_returns_429(
    db_sessions, slow_engine_app, live_server_factory
):
    project = await ProjectsRepository(db_sessions).create(name="CC")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="T"
    )
    base_url = await live_server_factory(slow_engine_app)

    async with AsyncClient(base_url=base_url) as client:
        # Hold the first SSE open (semaphore occupied) while the second arrives.
        stream = client.stream("POST", "/api/agent", json=run_input(thread.id, "run-1"))
        first = await stream.__aenter__()
        try:
            second = await client.post("/api/agent", json=run_input(thread.id, "run-2"))
        finally:
            await stream.__aexit__(None, None, None)

    assert sorted([first.status_code, second.status_code]) == [200, 429]


# --- cancellation --


async def test_disconnect_marks_run_cancelled(db_sessions):
    app = create_app()
    app.state.db_sessions = db_sessions
    thread_id = await seed_thread(app)

    calls = 0

    async def disconnect_after_2() -> bool:
        nonlocal calls
        calls += 1
        return calls > 2

    import dspy

    from app.agent.engine import DspyAgentEngine
    from app.agent.instrumented import instrument_tool
    from app.agent.signature import AgentSignature
    from app.agent.tools.docs import SearchDocsTool
    from app.services.run_persistence import RunPersistence
    from tests.helpers.scripted_lm import ScriptedLM

    def build(bus, *, thread_id: str = "t"):
        tools = [instrument_tool(SearchDocsTool(), bus)]

        def factory():
            return dspy.ReActV2(AgentSignature, tools=tools, max_iters=4)

        return DspyAgentEngine(
            program_factory=factory,
            lm=ScriptedLM(
                [[{"name": "search_docs", "args": {"query": "x"}}], [submit_call()]]
            ),
            adapter=dspy.JSONAdapter(),
        )

    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(run_input(thread_id, "run-cancel")),
        engine_builder=build,
        accept="text/event-stream",
        is_disconnected=disconnect_after_2,
        persistence=RunPersistence(db_sessions),
    )
    events = []
    async for chunk in stream:
        events.append(chunk)
    for chunk in events:
        assert "RUN_FINISHED" not in chunk and "RUN_ERROR" not in chunk

    run = await RunsRepository(db_sessions).get("run-cancel")
    assert run is not None
    assert run.status == "cancelled"
    assert run.error_code == "run_cancelled"


# --- timeout + rate limit mapping ---------------------------------------------


async def test_run_times_out_with_public_code():
    import dspy

    from app.agent.engine import DspyAgentEngine
    from app.agent.signature import AgentSignature
    from tests.helpers.scripted_lm import ScriptedLM

    def sleepy(query: str) -> str:
        """Sleeps past the configured timeout."""
        import time as _t

        _t.sleep(1.5)
        return "slept"

    from app.agent.instrumented import instrument_tool

    def build(bus, *, thread_id: str = "t"):
        tools = [instrument_tool(sleepy, bus)]

        def factory():
            return dspy.ReActV2(AgentSignature, tools=tools, max_iters=4)

        return DspyAgentEngine(
            program_factory=factory,
            lm=ScriptedLM(
                [[{"name": "sleepy", "args": {"query": "x"}}], [submit_call()]]
            ),
            adapter=dspy.JSONAdapter(),
        )

    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(run_input("t-timeout", "run-timeout")),
        engine_builder=build,
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
        run_timeout_s=0.3,
    )
    events = [json.loads(c.removeprefix("data: ").strip()) async for c in stream]
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "agent_timeout"
    assert "did not finish in time" in events[-1]["message"]


async def _false() -> bool:
    return False


async def test_provider_rate_limit_maps_public_code():
    from litellm import RateLimitError

    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(run_input("t-rl", "run-rl")),
        engine_builder=lambda bus, **kw: (_ for _ in ()).throw(
            RateLimitError("boom", "openai", "none")
        ),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    events = [json.loads(c.removeprefix("data: ").strip()) async for c in stream]
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "rate_limited"


# --- orphan reconciliation + metrics -------------------------------------------


async def test_orphaned_running_runs_corrected_at_startup(db_sessions):
    thread_id = "thread-orphan"
    project = await ProjectsRepository(db_sessions).create(name="O")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="T"
    )
    thread_id = thread.id
    await RunsRepository(db_sessions).started(run_id="run-old", thread_id=thread_id)

    app = create_app()
    app.state.db_sessions = db_sessions
    async with app.router.lifespan_context(app):
        pass

    run = await RunsRepository(db_sessions).get("run-old")
    assert run is not None
    assert run.status == "failed"
    assert run.termination_reason == "server_restart"


async def test_metrics_registry_counts():
    from app.services.metrics import MetricsRegistry

    registry = MetricsRegistry()
    app = create_app()
    app.state.metrics = registry
    app.state.db_sessions = None
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)
    threadless = app.state.db_sessions  # noqa: F841

    # Direct coordinator use with scripted builder:
    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(
            {
                "threadId": "t-m",
                "runId": "run-m",
                "state": None,
                "messages": [{"id": "m1", "role": "user", "content": "hi"}],
                "tools": [],
                "context": [],
                "forwardedProps": None,
            }
        ),
        engine_builder=scripted_builder([[submit_call(answer="m")]]),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
        metrics=registry,
    )
    async for _ in stream:
        pass

    snapshot = registry.snapshot()
    assert snapshot["counters"]["agent_runs_total"] == 1
    assert "agent_run_errors_total" not in snapshot["counters"]
    assert snapshot["durations"]["agent_run_duration_ms"]["count"] == 1


async def test_metrics_endpoint_reports_shape():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "counters" in body and "gauges" in body and "durations" in body
