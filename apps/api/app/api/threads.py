"""Threads REST resources + the /bootstrap payload for restoration."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.projects import LOCAL_OWNER, get_sessions
from app.persistence.models import Project, Thread
from app.persistence.repositories import (
    ArtifactsRepository,
    MessagesRepository,
    ProjectsRepository,
    RunsRepository,
    RunStatesRepository,
    SourcesRepository,
    ThreadsRepository,
)

router = APIRouter(prefix="/api", tags=["threads"])


class ThreadOut(BaseModel):
    id: str
    projectId: str
    title: str
    status: str
    lastRunId: str | None
    createdAt: str
    updatedAt: str


class ThreadCreate(BaseModel):
    title: str = "New conversation"


class ThreadPatch(BaseModel):
    title: str


class BootstrapOut(BaseModel):
    thread: ThreadOut
    messages: list[dict[str, Any]]
    agentState: dict[str, Any] | None
    latestRun: dict[str, Any] | None


def thread_to_out(thread: Thread) -> ThreadOut:
    return ThreadOut(
        id=thread.id,
        projectId=thread.project_id,
        title=thread.title,
        status=thread.status,
        lastRunId=thread.last_run_id,
        createdAt=thread.created_at.isoformat(),
        updatedAt=thread.updated_at.isoformat(),
    )


async def require_project(
    project_id: str, sessions: async_sessionmaker[AsyncSession]
) -> Project:
    project = await ProjectsRepository(sessions).get(project_id)
    if project is None or project.owner_id != LOCAL_OWNER:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


async def require_thread(
    thread_id: str, sessions: async_sessionmaker[AsyncSession]
) -> Thread:
    thread = await ThreadsRepository(sessions).get(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")
    project = await ProjectsRepository(sessions).get(thread.project_id)
    if project is None or project.owner_id != LOCAL_OWNER:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return thread


@router.get("/projects/{project_id}/threads")
async def list_threads(
    project_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> list[ThreadOut]:
    await require_project(project_id, sessions)
    threads = await ThreadsRepository(sessions).list_for_project(project_id)
    return [thread_to_out(thread) for thread in threads]


@router.post("/projects/{project_id}/threads", status_code=201)
async def create_thread(
    project_id: str,
    body: ThreadCreate,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> ThreadOut:
    await require_project(project_id, sessions)
    title = body.title.strip() or "New conversation"
    thread = await ThreadsRepository(sessions).create(
        project_id=project_id, title=title
    )
    return thread_to_out(thread)


@router.get("/threads/{thread_id}/bootstrap")
async def thread_bootstrap(
    thread_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> BootstrapOut:
    """Everything the client needs to restore a thread after reload/switch."""
    thread = await require_thread(thread_id, sessions)
    messages = await MessagesRepository(sessions).list_for_thread(thread_id)
    agent_state = await RunStatesRepository(sessions).get(thread_id)
    latest = await RunsRepository(sessions).latest_for_thread(thread_id)
    return BootstrapOut(
        thread=thread_to_out(thread),
        messages=messages,
        agentState=agent_state,
        latestRun=(
            {
                "id": latest.id,
                "status": latest.status,
                "terminationReason": latest.termination_reason,
                "errorCode": latest.error_code,
            }
            if latest
            else None
        ),
    )


@router.patch("/threads/{thread_id}")
async def rename_thread(
    thread_id: str,
    body: ThreadPatch,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> ThreadOut:
    await require_thread(thread_id, sessions)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Thread title must not be empty.")
    thread = await ThreadsRepository(sessions).rename(thread_id, title=title)
    return thread_to_out(thread)  # type: ignore[arg-type]


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, request: Request) -> None:
    sessions = request.app.state.db_sessions
    await require_thread(thread_id, sessions)
    await ThreadsRepository(sessions).delete(thread_id)
    # Retention: a deleted thread's artifact files are removed with it.
    request.app.state.artifact_storage.delete_prefix(f"{thread_id}/")


@router.get("/threads/{thread_id}/sources")
async def list_sources(thread_id: str, request: Request) -> list[dict[str, Any]]:
    sessions = request.app.state.db_sessions
    await require_thread(thread_id, sessions)
    sources = await SourcesRepository(sessions).list_for_thread(thread_id)
    return [
        {
            "id": s.id,
            "title": s.title,
            "sourceType": s.source_type,
            "uri": s.uri,
            "excerpt": s.excerpt,
            "toolCallId": s.tool_call_id,
        }
        for s in sources
    ]


@router.get("/threads/{thread_id}/artifacts")
async def list_artifacts(thread_id: str, request: Request) -> list[dict[str, Any]]:
    from app.api.artifacts import artifact_to_out

    sessions = request.app.state.db_sessions
    await require_thread(thread_id, sessions)
    artifacts = await ArtifactsRepository(sessions).list_for_thread(thread_id)
    return [artifact_to_out(a) for a in artifacts]
