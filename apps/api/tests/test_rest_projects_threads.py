"""REST coverage for projects/threads (DB-backed)."""

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator

from app.main import create_app
from app.persistence.repositories import MessagesRepository
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.mark.parametrize("run_config", [None, {}, {"model": "test-model"}])
async def test_bootstrap_message_run_config_matches_shared_schema(
    db_sessions, run_config
):
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = await post_project(client)
        thread = (
            await client.post(f"/api/projects/{project['id']}/threads", json={})
        ).json()
        await MessagesRepository(db_sessions).append(
            thread_id=thread["id"],
            role="user",
            message_json={"id": "m-test", "role": "user", "content": []},
            message_id="m-test",
            run_config_json=run_config,
        )
        response = await client.get(f"/api/threads/{thread['id']}/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "packages/contracts/thread-bootstrap.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    entry = payload["messageRepository"]["messages"][0]
    if run_config is None:
        assert "runConfig" not in entry
    else:
        assert entry["runConfig"] == run_config
    assert payload["agentState"] is None
    assert payload["latestRun"] is None
    assert payload["thread"]["lastRunId"] is None
    assert payload["messageRepository"]["headId"] is None
    assert entry["parentId"] is None


async def post_project(client: AsyncClient, name: str = "Demo") -> dict:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


async def test_project_thread_rest_flow(db_sessions):
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = await post_project(client)

        listed = await client.get("/api/projects")
        assert [p["id"] for p in listed.json()] == [project["id"]]

        thread = (
            await client.post(
                f"/api/projects/{project['id']}/threads", json={"title": "First"}
            )
        ).json()
        assert thread["projectId"] == project["id"]

        threads = await client.get(f"/api/projects/{project['id']}/threads")
        assert [t["id"] for t in threads.json()] == [thread["id"]]

        renamed = await client.patch(
            f"/api/threads/{thread['id']}", json={"title": "Renamed"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Renamed"

        deleted = await client.delete(f"/api/threads/{thread['id']}")
        assert deleted.status_code == 204

        threads_after = await client.get(f"/api/projects/{project['id']}/threads")
        assert threads_after.json() == []


async def test_create_project_rejects_empty_name(db_sessions):
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/projects", json={"name": "   "})
    assert response.status_code == 422


async def test_threads_of_unknown_project_404(db_sessions):
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/projects/nope/threads")
        created = await client.post("/api/projects/nope/threads", json={"title": "x"})
    assert response.status_code == 404
    assert created.status_code == 404


async def test_rename_validates_input(db_sessions):
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = await post_project(client)
        thread = (
            await client.post(f"/api/projects/{project['id']}/threads", json={})
        ).json()
        response = await client.patch(
            f"/api/threads/{thread['id']}", json={"title": " "}
        )
    assert response.status_code == 422


async def test_project_rename_and_delete(db_sessions):
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = await post_project(client)
        thread = (
            await client.post(
                f"/api/projects/{project['id']}/threads", json={"title": "Doomed"}
            )
        ).json()

        renamed = await client.patch(
            f"/api/projects/{project['id']}", json={"name": "Renamed project"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Renamed project"

        empty = await client.patch(f"/api/projects/{project['id']}", json={"name": " "})
        assert empty.status_code == 422

        deleted = await client.delete(f"/api/projects/{project['id']}")
        assert deleted.status_code == 204

        listed = await client.get("/api/projects")
        assert [p["id"] for p in listed.json()] == []
        # Threads cascade with the project.
        bootstrap = await client.get(f"/api/threads/{thread['id']}/bootstrap")
        assert bootstrap.status_code == 404


async def test_project_rename_delete_unknown_project_404(db_sessions):
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch("/api/projects/nope", json={"name": "x"})
        deleted = await client.delete("/api/projects/nope")
    assert response.status_code == 404
    assert deleted.status_code == 404


async def test_bootstrap_passes_an_unexpected_message_format_through(db_sessions):
    """A persisted format outside the known values must not 500 the bootstrap.

    The wire type is a plain string and the repository passes stored values
    through untouched; the browser validator is the gate that rejects unknown
    formats before decoding.
    """
    app = create_app()
    app.state.db_sessions = db_sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = await post_project(client)
        thread = (
            await client.post(
                f"/api/projects/{project['id']}/threads", json={"title": "Legacy"}
            )
        ).json()
        await MessagesRepository(db_sessions).append(
            thread_id=thread["id"],
            role="assistant",
            message_json={"id": "m-legacy", "role": "assistant", "content": []},
            message_id="m-legacy",
            format="legacy/v9",
        )
        response = await client.get(f"/api/threads/{thread['id']}/bootstrap")
    assert response.status_code == 200
    entries = response.json()["messageRepository"]["messages"]
    assert [entry["format"] for entry in entries] == ["legacy/v9"]
