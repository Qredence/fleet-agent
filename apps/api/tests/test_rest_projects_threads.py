"""REST coverage for projects/threads (DB-backed)."""

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.conftest import requires_db

pytestmark = requires_db


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
