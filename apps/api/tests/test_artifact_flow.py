"""End-to-end: scripted engine run that discovers sources and emits artifacts,
persisted and served via REST."""

import json
from pathlib import Path

import dspy  # noqa: E402
from ag_ui.core import RunAgentInput
from httpx import ASGITransport, AsyncClient

from app.agent.engine import DspyAgentEngine  # noqa: E402
from app.agent.instrumented import instrument_tool  # noqa: E402
from app.agent.signature import AgentSignature  # noqa: E402
from app.agent.tools.docs import SearchDocsTool
from app.agent.tools.report import WriteReportTool
from app.agui.live_coordinator import LiveDSPyCoordinator
from app.main import create_app
from app.persistence.repositories import (
    ArtifactsRepository,
    ProjectsRepository,
    RunStatesRepository,
    SourcesRepository,
    ThreadsRepository,
)
from app.services.artifact_storage import LocalArtifactStorage
from app.services.run_persistence import RunPersistence
from tests.conftest import requires_db
from tests.helpers.scripted_lm import ScriptedLM, submit_call

pytestmark = requires_db


def rich_builder(storage, steps):
    """
    Create an agent-engine builder configured with artifact storage and scripted steps.
    
    Parameters:
    	storage: Storage used by the report-writing tool.
    	steps: Scripted language-model actions used by the agent.
    
    Returns:
    	A builder function that creates a configured agent engine for a thread.
    """
    def build(bus, *, thread_id: str = "t"):
        docs = SearchDocsTool()
        report = WriteReportTool(
            storage=storage, bus=bus, thread_id=thread_id, max_bytes=10_000
        )
        tools = [instrument_tool(t, bus) for t in [docs, report]]

        def factory():
            return dspy.ReActV2(AgentSignature, tools=tools, max_iters=6)

        return DspyAgentEngine(
            program_factory=factory, lm=ScriptedLM(steps), adapter=dspy.JSONAdapter()
        )

    return build


async def drive(app, thread_id: str, storage, steps, run_id="run-rich"):
    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(
            {
                "threadId": thread_id,
                "runId": run_id,
                "state": None,
                "messages": [
                    {
                        "id": "m1",
                        "role": "user",
                        "content": "explain state sync and save a report",
                    }
                ],
                "tools": [],
                "context": [],
                "forwardedProps": None,
            }
        ),
        engine_builder=rich_builder(storage, steps),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
        persistence=None,
    )
    return [json.loads(c.removeprefix("data: ").strip()) async for c in stream]


async def _false() -> bool:
    return False


STEPS = [
    [{"name": "search_docs", "args": {"query": "state sync snapshot"}}],
    [
        {
            "name": "write_report",
            "args": {
                "title": "state-sync-notes",
                "content": "# Notes\n\nDeltas patch the snapshot.",
            },
        }
    ],
    [submit_call(answer="Saved the summary as a downloadable report.")],
]


async def test_artifact_live_run_end_to_end(db_sessions, tmp_path: Path):
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    project = await ProjectsRepository(db_sessions).create(name="R")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="T"
    )
    persistence = RunPersistence(db_sessions)

    stream = LiveDSPyCoordinator().stream(
        input_data=RunAgentInput.model_validate(
            {
                "threadId": thread.id,
                "runId": "run-rich",
                "state": None,
                "messages": [
                    {
                        "id": "m1",
                        "role": "user",
                        "content": "explain state sync and save a report",
                    }
                ],
                "tools": [],
                "context": [],
                "forwardedProps": None,
            }
        ),
        engine_builder=rich_builder(storage, STEPS),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
        persistence=persistence,
    )
    events = [json.loads(c.removeprefix("data: ").strip()) async for c in stream]

    types = [e["type"] for e in events]
    assert types[-1] == "RUN_FINISHED"

    # Inline CUSTOM artifact event landed in-flight.
    custom = [e for e in events if e["type"] == "CUSTOM" and e["name"] == "artifact"]
    assert len(custom) == 1
    (artifact_value,) = [e["value"] for e in custom]
    assert artifact_value["name"] == "state-sync-notes.md"
    assert artifact_value["downloadUrl"] == f"/api/artifacts/{artifact_value['id']}"

    # Sources persisted with canonical URIs.
    sources = await SourcesRepository(db_sessions).list_for_thread(thread.id)
    assert sources
    assert all(s.id for s in sources)

    # Artifact row ready; storage confined to root.
    artifacts = await ArtifactsRepository(db_sessions).list_for_thread(thread.id)
    (artifact,) = artifacts
    assert artifact.status == "ready"
    assert artifact.size_bytes and artifact.size_bytes > 0
    assert (tmp_path / "artifacts" / artifact.storage_key).exists()

    # State snapshot (panel restore) is schema-valid and carries sources+artifact.
    from app.contracts.agent_state import AgentWorkspaceState

    state = await RunStatesRepository(db_sessions).get(thread.id)
    AgentWorkspaceState.model_validate(state)
    assert len(state["artifacts"]) == 1
    assert state["artifacts"][0]["status"] == "ready"
    assert state["artifacts"][0]["downloadUrl"] == artifact_value["downloadUrl"]
    assert len(state["sources"]) >= 1
    # No filesystem path leaks into any payload.
    assert ".artifacts" not in json.dumps(state) and str(tmp_path) not in json.dumps(
        state
    )

    # REST endpoints: listing + controlled download.
    app = create_app()
    app.state.settings = app.state.settings.model_copy(update={})
    app.state.db_sessions = db_sessions
    app.state.artifact_storage = storage
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        listing = await client.get(f"/api/threads/{thread.id}/artifacts")
        assert listing.status_code == 200
        assert listing.json()[0]["downloadUrl"] == artifact_value["downloadUrl"]

        sources_listing = await client.get(f"/api/threads/{thread.id}/sources")
        assert sources_listing.status_code == 200
        assert len(sources_listing.json()) == len(sources)

        download = await client.get(artifact_value["downloadUrl"])
        assert download.status_code == 200
        assert download.headers["x-content-type-options"] == "nosniff"
        assert "attachment" in download.headers.get("content-disposition", "")
        assert "Deltas patch the snapshot." in download.text

        missing = await client.get("/api/artifacts/artifact_no_such")
        assert missing.status_code == 404


async def test_download_rejects_non_ready_artifact(tmp_path: Path, db_sessions):
    project = await ProjectsRepository(db_sessions).create(name="R")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="T"
    )

    app = create_app()
    app.state.db_sessions = db_sessions
    app.state.artifact_storage = LocalArtifactStorage(tmp_path)
    # A generating row exists but is unservable.
    await ArtifactsRepository(db_sessions).add(
        artifact_id="a1",
        thread_id=thread.id,
        run_id="r",
        name="x.md",
        media_type="text/markdown",
        storage_key=f"{thread.id}/a1/x.md",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/artifacts/a1")
    assert response.status_code == 404
