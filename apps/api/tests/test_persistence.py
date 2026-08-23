"""Persistence: repositories, write path, bootstrap restoration, isolation."""

import json

import dspy
from ag_ui.core import RunAgentInput
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.agui.live_coordinator import LiveDSPyCoordinator
from app.persistence.models import Message, Run, Thread
from app.persistence.repositories import (
    MessagesRepository,
    ProjectsRepository,
    RunsRepository,
    RunStatesRepository,
    ThreadsRepository,
)
from app.services.run_persistence import HISTORY_SCHEMA_VERSION, RunPersistence
from tests.conftest import requires_db
from tests.helpers.scripted_lm import submit_call

pytestmark = requires_db

from app.main import create_app  # noqa: E402
from tests.test_live_coordinator import scripted_builder  # noqa: E402


def run_input(thread_id: str, run_id: str, text: str = "hi") -> dict:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": None,
        "messages": [{"id": "m-user-" + run_id, "role": "user", "content": text}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }


async def drive_live_run(
    app, persistence, steps, thread_id, run_id, text="hello", max_iters=4
):
    coordinator = LiveDSPyCoordinator()
    stream = coordinator.stream(
        input_data=RunAgentInput.model_validate(run_input(thread_id, run_id, text)),
        engine_builder=scripted_builder(steps, max_iters=max_iters),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
        persistence=persistence,
    )
    return [json.loads(c.removeprefix("data: ").strip()) async for c in stream]


async def _false() -> bool:
    return False


async def seed_project_and_thread(db_sessions) -> tuple[str, str]:
    project = await ProjectsRepository(db_sessions).create(name="Demo")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="First thread"
    )
    return project.id, thread.id


async def test_projects_repository_round_trip(db_sessions):
    project = await ProjectsRepository(db_sessions).create(name="Apollo")
    assert project.id.startswith("project_")

    listed = await ProjectsRepository(db_sessions).list()
    assert [p.id for p in listed] == [project.id]

    fetched = await ProjectsRepository(db_sessions).get(project.id)
    assert fetched and fetched.name == "Apollo"


async def test_full_run_write_path_and_bootstrap(db_sessions):
    _, thread_id = await seed_project_and_thread(db_sessions)
    persistence = RunPersistence(db_sessions)

    events = await drive_live_run(
        None,
        persistence,
        [
            [{"name": "search_docs", "args": {"query": "protocol"}}],
            [submit_call(answer="State sync uses JSON Patch.")],
        ],
        thread_id,
        "run-1",
    )
    assert events[-1]["type"] == "RUN_FINISHED"

    messages = await MessagesRepository(db_sessions).list_for_thread(thread_id)
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant"]
    assert messages[1]["content"] == "State sync uses JSON Patch."

    run = await RunsRepository(db_sessions).get("run-1")
    assert run and run.status == "completed"
    assert run.termination_reason == "submit"
    assert run.token_usage["total_tokens"] == 30

    from app.contracts.agent_state import AgentWorkspaceState

    state = await RunStatesRepository(db_sessions).get(thread_id)
    AgentWorkspaceState.model_validate(state)
    assert state["run"]["status"] == "completed"

    history = await persistence.get_continuation_history(thread_id)
    assert history is not None and len(history.messages) >= 2


async def test_second_turn_uses_persisted_history(db_sessions):
    _, thread_id = await seed_project_and_thread(db_sessions)
    persistence = RunPersistence(db_sessions)

    await drive_live_run(
        None, persistence, [[submit_call(answer="First.")]], thread_id, "run-1"
    )
    first_history = await persistence.get_continuation_history(thread_id)
    first_depth = len(first_history.messages)

    events = await drive_live_run(
        None,
        persistence,
        [[submit_call(answer="Second.")]],
        thread_id,
        "run-2",
        "again",
    )
    assert events[-1]["type"] == "RUN_FINISHED"

    from app.persistence.repositories import DspyHistoriesRepository

    record = await DspyHistoriesRepository(db_sessions).get(thread_id)
    assert record.schema_version == HISTORY_SCHEMA_VERSION
    assert record.dspy_version == dspy.__version__
    history = dspy.History.model_validate(record.history_json)
    assert len(history.messages) > first_depth

    # The stored raw structured history contains execution internals
    # (tool calls + results) — the reason it stays server-side.
    assert "tool_calls" in json.dumps(record.history_json)

    # Resolving continuation history through the assistant-ui tool card ID works
    tool_card_history = await persistence.get_continuation_history(
        thread_id, head_message_id="msg-tools-run-1"
    )
    assert tool_card_history is not None
    assert len(tool_card_history.messages) >= first_depth


async def test_regeneration_keeps_user_parent_and_uses_sibling_history(db_sessions):
    _, thread_id = await seed_project_and_thread(db_sessions)
    persistence = RunPersistence(db_sessions)

    first_input = run_input(thread_id, "run-regenerate-1")
    first_input["messages"][0]["id"] = "user-root"
    await persistence.reserve_run(input_data=RunAgentInput.model_validate(first_input))
    async with db_sessions() as session:
        async with session.begin():
            session.add(
                Message(
                    id="assistant-row-1",
                    thread_id=thread_id,
                    message_id="assistant-first",
                    parent_message_id="user-root",
                    role="assistant",
                    format="ag-ui/v1",
                    message_json={
                        "id": "assistant-first",
                        "role": "assistant",
                        "content": "first answer",
                    },
                )
            )
            await session.execute(
                update(Run)
                .where(Run.id == "run-regenerate-1")
                .values(status="completed", output_message_id="assistant-first")
            )
            await session.execute(
                update(Thread)
                .where(Thread.id == thread_id)
                .values(active_head_message_id="assistant-first")
            )

    second_input = run_input(thread_id, "run-regenerate-2")
    second_input["messages"][0]["id"] = "user-root"
    await persistence.reserve_run(input_data=RunAgentInput.model_validate(second_input))

    async with db_sessions() as session:
        user = await session.scalar(
            select(Message).where(
                Message.thread_id == thread_id,
                Message.message_id == "user-root",
            )
        )
        run = await session.get(Run, "run-regenerate-2")
    assert user is not None and user.parent_message_id is None
    assert run is not None and run.continuation_message_id == "assistant-first"


async def test_failed_run_keeps_user_message_only(db_sessions):
    _, thread_id = await seed_project_and_thread(db_sessions)
    persistence = RunPersistence(db_sessions)

    events = await drive_live_run(
        None,
        persistence,
        [
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
        ],
        thread_id,
        "run-fail",
        max_iters=1,
    )
    assert events[-1]["type"] == "RUN_ERROR"

    messages = await MessagesRepository(db_sessions).list_for_thread(thread_id)
    assert [m["role"] for m in messages] == ["user"]

    run = await RunsRepository(db_sessions).get("run-fail")
    assert run and run.status == "failed"
    assert run.error_code == "agent_no_output"

    state = await RunStatesRepository(db_sessions).get(thread_id)
    assert state["run"]["status"] == "failed"


async def test_thread_isolation(db_sessions):
    _, thread_a = await seed_project_and_thread(db_sessions)
    _, thread_b = await seed_project_and_thread(db_sessions)

    persistence = RunPersistence(db_sessions)
    await drive_live_run(
        None, persistence, [[submit_call(answer="Only in A.")]], thread_a, "run-a1"
    )
    await drive_live_run(
        None, persistence, [[submit_call(answer="Only in B.")]], thread_b, "run-b1"
    )

    messages_a = await MessagesRepository(db_sessions).list_for_thread(thread_a)
    messages_b = await MessagesRepository(db_sessions).list_for_thread(thread_b)
    assert all("Only in A." in json.dumps(m) or m["role"] == "user" for m in messages_a)
    assert all("Only in B." in json.dumps(m) or m["role"] == "user" for m in messages_b)

    state_a = await RunStatesRepository(db_sessions).get(thread_a)
    state_b = await RunStatesRepository(db_sessions).get(thread_b)
    assert state_a["run"]["id"] == "run-a1"
    assert state_b["run"]["id"] == "run-b1"


async def test_bootstrap_endpoint_restores_exact_thread(db_sessions, db_settings):
    project_id, thread_id = await seed_project_and_thread(db_sessions)
    persistence = RunPersistence(db_sessions)
    await drive_live_run(
        None,
        persistence,
        [[submit_call(answer="Bootstrap me.")]],
        thread_id,
        "run-boot",
    )

    app = create_app()
    app.state.settings = db_settings
    app.state.db_engine = None  # unused by these endpoints
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/threads/{thread_id}/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["thread"]["id"] == thread_id
    assert payload["thread"]["projectId"] == project_id
    assert [m["role"] for m in payload["messages"]] == ["user", "assistant"]
    assert payload["messages"][1]["content"] == "Bootstrap me."
    assert payload["agentState"]["schemaVersion"] == 1
    assert payload["latestRun"]["status"] == "completed"
    # The DSPy history (and therefore next_thought) is never served.
    assert "next_thought" not in json.dumps(payload)
    assert "history" not in json.dumps(payload["agentState"])


async def test_bootstrap_404_for_unknown_thread(db_sessions):
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/threads/nope/bootstrap")
    assert response.status_code == 404


async def test_delete_thread_cascades(db_sessions):
    _, thread_id = await seed_project_and_thread(db_sessions)
    persistence = RunPersistence(db_sessions)
    await drive_live_run(None, persistence, [[submit_call()]], thread_id, "run-del")

    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/api/threads/{thread_id}")
    assert response.status_code == 204

    assert await MessagesRepository(db_sessions).list_for_thread(thread_id) == []
    assert await RunStatesRepository(db_sessions).get(thread_id) is None
    assert await RunsRepository(db_sessions).get("run-del") is None
    assert await persistence.get_continuation_history(thread_id) is None


async def test_same_source_twice_is_idempotent(db_sessions):
    from app.persistence.repositories import (
        ProjectsRepository,
        SourcesRepository,
        ThreadsRepository,
    )

    project = await ProjectsRepository(db_sessions).create(name="S")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="T"
    )
    repo = SourcesRepository(db_sessions)
    for run in ("run-1", "run-2"):
        await repo.add(
            source_id="doc-agui-events",
            thread_id=thread.id,
            run_id=run,
            tool_call_id="tool_x",
            title="AG-UI events",
            source_type="web",
            uri="https://docs.ag-ui.com/sdk/python/core/events",
            excerpt="state deltas",
        )
    listed = await repo.list_for_thread(thread.id)
    assert len(listed) == 1


async def test_stale_user_branch_does_not_move_active_head(db_sessions):
    _, thread_id = await seed_project_and_thread(db_sessions)
    async with db_sessions() as session:
        async with session.begin():
            await MessagesRepository.upsert_in_session(
                session,
                thread_id=thread_id,
                role="user",
                message_json={"id": "user-root", "role": "user", "content": "root"},
                message_id="user-root",
                parent_message_id=None,
                format="ag-ui/v1",
            )
            await MessagesRepository.upsert_in_session(
                session,
                thread_id=thread_id,
                role="assistant",
                message_json={
                    "id": "assistant-current",
                    "role": "assistant",
                    "content": "current",
                },
                message_id="assistant-current",
                parent_message_id="user-root",
                format="ag-ui/v1",
            )
            await session.execute(
                update(Thread)
                .where(Thread.id == thread_id)
                .values(active_head_message_id="assistant-current")
            )

    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        stale = await client.put(
            f"/api/threads/{thread_id}/messages/user-stale",
            json={
                "parentId": "user-root",
                "format": "aui/v0",
                "content": {
                    "id": "user-stale",
                    "role": "user",
                    "content": "stale fork",
                },
            },
        )
        assert stale.status_code == 200

    current = await ThreadsRepository(db_sessions).get(thread_id)
    assert current is not None
    assert current.active_head_message_id == "assistant-current"
