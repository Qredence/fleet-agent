"""Hardening: auth, size limits, duplicate-run idempotency, concurrency cap,
run timeout, cancellation settling, rate-limit mapping, orphan reconciliation,
and metrics."""

import json

import pytest
from ag_ui.core import RunAgentInput
from httpx import ASGITransport, AsyncClient

from app.agent.callbacks import AgUiRunCallback
from app.agui.run import LiveDSPyCoordinator
from app.main import create_app
from app.persistence.repositories import (
    ProjectsRepository,
    RunsRepository,
    RunStatesRepository,
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
    app = make_test_app(api_key="secret-1", agent_mode="fixtures")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.post("/api/agent", json=run_input("t"))
        allowed = await client.post(
            "/api/agent", json=run_input("t"), headers={"x-api-key": "secret-1"}
        )
        health = await client.get("/health")
    assert denied.status_code == 401
    assert denied.headers.get("x-request-id")
    assert allowed.status_code != 401  # fixtures mode streams
    assert health.status_code == 200


async def test_api_key_protects_unprefixed_routes_too():
    """Regression: /metrics shipped unauthenticated.

    The gate used to require ``path.startswith("/api/")``, so routes registered
    without that prefix (and the OpenAPI docs) bypassed auth entirely.
    """
    app = make_test_app(api_key="secret-1", agent_mode="fixtures")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        metrics = await client.get("/metrics")
        openapi = await client.get("/openapi.json")
        health = await client.get("/health")
        ready = await client.get("/ready")
        authorized = await client.get("/metrics", headers={"x-api-key": "secret-1"})

    assert metrics.status_code == 401
    assert openapi.status_code == 401
    assert health.status_code == 200  # explicitly public liveness probe
    assert ready.status_code in (200, 503)  # explicitly public readiness probe
    assert authorized.status_code == 200


async def test_metrics_is_open_when_no_api_key_is_configured():
    """Local/dev runs without a key stay fully open (advisory logged at startup)."""
    app = make_test_app(agent_mode="fixtures")
    app.state.settings = Settings(agent_mode="fixtures", api_key=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/metrics")
    assert response.status_code == 200


async def test_request_size_cap_returns_413():
    app = make_test_app(max_body_bytes="16")
    response = await post(app, run_input("t", text="x" * 100))
    assert response.status_code == 413
    assert response.headers.get("x-request-id")


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
    from tests.helpers.scripted_lm import ScriptedLM, submit_call
    from tests.helpers.signatures import AgentSignature

    def encoder_side(query: str) -> str:
        """Blocks so the first run holds the semaphore."""
        _time.sleep(0.4)
        return "ok"

    def build(
        bus,
        *,
        thread_id,
        provider_override=None,
        approved=None,
    ):
        del provider_override, approved
        tools = [encoder_side]

        def factory():
            return dspy.ReAct(AgentSignature, tools=tools, max_iters=3)

        return DspyAgentEngine(
            program_factory=factory,
            lm=ScriptedLM(
                [[{"name": "encoder_side", "args": {"query": "x"}}], [submit_call()]]
            ),
            adapter=dspy.JSONAdapter(),
            callbacks=[AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)],
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
    from app.agent.tools.docs import SearchDocsTool
    from app.persistence.run_persistence import RunPersistence
    from tests.helpers.scripted_lm import ScriptedLM
    from tests.helpers.signatures import AgentSignature

    def build(
        bus,
        *,
        thread_id: str = "t",
        provider_override=None,
        approved=None,
    ):
        del provider_override, approved
        tools = [SearchDocsTool()]

        def factory():
            return dspy.ReAct(AgentSignature, tools=tools, max_iters=4)

        return DspyAgentEngine(
            program_factory=factory,
            lm=ScriptedLM(
                [[{"name": "search_docs", "args": {"query": "x"}}], [submit_call()]]
            ),
            adapter=dspy.JSONAdapter(),
            callbacks=[AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)],
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
    from tests.helpers.scripted_lm import ScriptedLM
    from tests.helpers.signatures import AgentSignature

    def sleepy(query: str) -> str:
        """Sleeps past the configured timeout."""
        import time as _t

        _t.sleep(1.5)
        return "slept"

    def build(
        bus,
        *,
        thread_id: str = "t",
        provider_override=None,
        approved=None,
    ):
        del provider_override, approved
        tools = [sleepy]

        def factory():
            return dspy.ReAct(AgentSignature, tools=tools, max_iters=4)

        return DspyAgentEngine(
            program_factory=factory,
            lm=ScriptedLM(
                [[{"name": "sleepy", "args": {"query": "x"}}], [submit_call()]]
            ),
            adapter=dspy.JSONAdapter(),
            callbacks=[AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)],
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


async def test_dspy_rate_limit_maps_public_code():
    import dspy

    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(run_input("t-rl2", "run-rl2")),
        engine_builder=lambda bus, **kw: (_ for _ in ()).throw(
            dspy.LMRateLimitError("boom", status=429)
        ),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    events = [json.loads(c.removeprefix("data: ").strip()) async for c in stream]
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "rate_limited"


async def test_dspy_auth_error_in_exception_group_maps_public_code():
    import dspy

    inner = dspy.LMAuthError(
        "401 unsupported type",
        model="databricks-test",
        provider="openai-compatible",
        status=401,
    )
    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(run_input("t-auth", "run-auth")),
        engine_builder=lambda bus, **kw: (_ for _ in ()).throw(
            ExceptionGroup("streamify", [inner])
        ),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    events = [json.loads(c.removeprefix("data: ").strip()) async for c in stream]
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "provider_unauthorized"
    assert events[-1]["message"] == (
        "The language model rejected the configured API key. "
        "Check the provider credentials and base URL."
    )


# --- orphan reconciliation + metrics -------------------------------------------


async def test_orphaned_running_runs_corrected_at_startup(db_sessions):
    thread_id = "thread-orphan"
    project = await ProjectsRepository(db_sessions).create(name="O")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="T"
    )
    thread_id = thread.id
    # Put one run in "running" the way the engine does: reserve, then start it.
    async with db_sessions() as session:
        await RunsRepository.reserve_in_session(
            session,
            run_id="run-old",
            thread_id=thread_id,
            input_message_id=None,
            continuation_message_id=None,
        )
        await RunsRepository.mark_running_in_session(session, run_id="run-old")
        await session.commit()

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


async def test_startup_sweep_also_rewrites_the_restored_snapshot(db_sessions):
    """The browser restores the panel from the snapshot, not from the run row.

    Rewriting only `runs.status` would leave a snapshot telling the panel a run is
    still live, and the UI has no way to act on that. This pins both halves: the
    orphaned row *and* the AgentWorkspaceState snapshot it points at.
    """
    project = await ProjectsRepository(db_sessions).create(name="S")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="Snapshot sweep"
    )
    async with db_sessions() as session:
        await RunsRepository.reserve_in_session(
            session,
            run_id="run-snapshot",
            thread_id=thread.id,
            input_message_id=None,
            continuation_message_id=None,
        )
        await RunsRepository.mark_running_in_session(session, run_id="run-snapshot")
        await RunStatesRepository.upsert_in_session(
            session,
            thread_id=thread.id,
            state_json={
                "schemaVersion": 1,
                "threadId": thread.id,
                "run": {
                    "id": "run-snapshot",
                    "status": "interrupted",
                    "terminationReason": "approval_required",
                },
                "steps": [],
                "toolCalls": [],
                "sources": [],
                "artifacts": [],
                "decisions": [],
                "metrics": {},
            },
            run_id="run-snapshot",
        )
        await session.commit()

    app = create_app()
    app.state.db_sessions = db_sessions
    async with app.router.lifespan_context(app):
        pass

    state = await RunStatesRepository(db_sessions).get(thread.id)
    assert state is not None
    run = state["run"]
    assert run["status"] == "failed"
    assert run["terminationReason"] == "server_restart"
    assert run["errorCode"] == "internal_error"


@pytest.mark.parametrize("raw_length", ["-5", "not-a-number"])
async def test_request_guard_rejects_invalid_content_length(raw_length: str):
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/agent",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": raw_length},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Content-Length header."


async def test_request_guard_enforces_limit_on_streaming_chunked_body():
    app = create_app()
    app.state.settings = Settings(max_body_bytes=64, agent_mode="fixtures")

    async def oversized_chunks():
        yield b'{"threadId":"t","runId":"r","state":null,'
        yield (
            b'"messages":[{"id":"m1","role":"user","content":"' + (b"x" * 100) + b'"}]}'
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/agent",
            content=oversized_chunks(),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large."


def test_settings_rejects_wildcard_cors_with_credentials():
    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError, match="cors_allow_credentials"):
        Settings(cors_origins=["*"], cors_allow_credentials=True)

    assert Settings(cors_origins=["*"], cors_allow_credentials=False).cors_origins == [
        "*"
    ]
    assert Settings(
        cors_origins=["http://localhost:5173"], cors_allow_credentials=True
    ).cors_origins == ["http://localhost:5173"]


async def test_run_agent_prestream_failure_releases_semaphore_and_fails_run(
    db_sessions, monkeypatch
):
    import asyncio

    from app.agui.run import LiveDSPyCoordinator
    from app.persistence.repositories import RunsRepository

    project = await ProjectsRepository(db_sessions).create(name="H")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="Pre-stream cleanup"
    )

    def broken_stream(self, **kwargs):
        del self, kwargs
        raise RuntimeError("pre-stream boom")

    monkeypatch.setattr(LiveDSPyCoordinator, "stream", broken_stream)

    app = create_app()
    app.state.db_sessions = db_sessions
    app.state.settings = Settings(
        agent_mode="engine", llm_api_key=None, max_concurrent_runs=1
    )
    app.state.run_semaphore = asyncio.Semaphore(1)
    app.state.engine_builder = scripted_builder([[submit_call(answer="ok")]])

    payload = {
        "threadId": thread.id,
        "runId": "run-prestream-fail",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "hi"}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/agent", json=payload)

    assert response.status_code == 503
    assert "pre-stream boom" not in response.text
    assert app.state.run_semaphore._value == 1
    run = await RunsRepository(db_sessions).get("run-prestream-fail")
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "internal_error"


async def test_run_agent_missing_engine_builder_does_not_leak_semaphore_or_run(
    db_sessions,
):
    import asyncio

    from app.persistence.repositories import RunsRepository

    project = await ProjectsRepository(db_sessions).create(name="H2")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="Missing builder"
    )
    app = create_app()
    app.state.db_sessions = db_sessions
    app.state.settings = Settings(
        agent_mode="engine", llm_api_key=None, max_concurrent_runs=1
    )
    app.state.run_semaphore = asyncio.Semaphore(1)

    payload = {
        "threadId": thread.id,
        "runId": "run-no-builder",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "hi"}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/agent", json=payload)

    assert response.status_code == 500
    assert app.state.run_semaphore._value == 1
    assert await RunsRepository(db_sessions).get("run-no-builder") is None


async def test_fixtures_mode_enforces_concurrency_cap_and_metrics(monkeypatch):
    import asyncio

    from ag_ui.core import EventType, RunStartedEvent

    from app.agui.run import TimedEvent
    from app.api import agent as agent_api
    from app.services.metrics import MetricsRegistry

    app = create_app()
    app.state.settings = Settings(
        agent_mode="fixtures", max_concurrent_runs=1, run_timeout_seconds=0.02
    )
    app.state.run_semaphore = asyncio.Semaphore(1)
    app.state.metrics = MetricsRegistry()

    payload = {
        "threadId": "any-thread",
        "runId": "fixture-run-1",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "hi"}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }

    await app.state.run_semaphore.acquire()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            busy = await client.post("/api/agent", json=payload)
        assert busy.status_code == 429
    finally:
        app.state.run_semaphore.release()

    monkeypatch.setattr(
        agent_api,
        "load_fixture",
        lambda name: [
            TimedEvent(
                at_ms=500,
                event=RunStartedEvent(
                    type=EventType.RUN_STARTED, thread_id="t", run_id="r"
                ),
            )
        ],
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        timed_out = await client.post("/api/agent", json=payload)
        metrics_resp = await client.get("/metrics")

    assert timed_out.status_code == 200
    assert "agent_timeout" in timed_out.text
    assert app.state.run_semaphore._value == 1
    snapshot = metrics_resp.json()
    assert snapshot["counters"]["agent_runs_total"] == 1
    assert snapshot["counters"]["agent_run_errors_total"] == 1
    assert snapshot["gauges"]["active_sse_connections"] == 0
    assert snapshot["durations"]["agent_run_duration_ms"]["count"] == 1


async def test_run_agent_and_artifact_enforce_thread_ownership(db_sessions, tmp_path):
    from app.persistence.models import Project, Run, Thread
    from app.persistence.repositories import ArtifactsRepository
    from app.services.artifact_storage import LocalArtifactStorage

    storage = LocalArtifactStorage(tmp_path)
    async with db_sessions() as session:
        async with session.begin():
            session.add(Project(id="p-other", owner_id="other-owner", name="Other"))
            await session.flush()
            session.add(
                Thread(id="t-other", project_id="p-other", title="Other Thread")
            )
            await session.flush()
            session.add(
                Run(id="run-other-art", thread_id="t-other", status="completed")
            )
    storage.save(storage_key="t-other/art-other/note.txt", content=b"secret")
    artifacts = ArtifactsRepository(db_sessions)
    await artifacts.add(
        artifact_id="art-other",
        thread_id="t-other",
        run_id="run-other-art",
        name="note.txt",
        media_type="text/plain",
        storage_key="t-other/art-other/note.txt",
    )
    await artifacts.mark_ready("art-other", size_bytes=6)

    app = create_app()
    app.state.db_sessions = db_sessions
    app.state.artifact_storage = storage
    app.state.settings = Settings(agent_mode="engine", llm_api_key=None)
    app.state.engine_builder = scripted_builder([[submit_call(answer="ok")]])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        art_resp = await client.get("/api/artifacts/art-other")
        run_resp = await client.post(
            "/api/agent",
            json={
                "threadId": "t-other",
                "runId": "run-other",
                "state": None,
                "messages": [{"id": "m1", "role": "user", "content": "hi"}],
                "tools": [],
                "context": [],
                "forwardedProps": None,
            },
        )
    assert art_resp.status_code == 404
    assert run_resp.status_code == 404
