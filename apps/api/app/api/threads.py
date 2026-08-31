"""Threads REST resources + the /bootstrap payload for restoration."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.projects import LOCAL_OWNER, get_sessions, require_project
from app.contracts.agent_state import AgentWorkspaceState
from app.contracts.error_codes import ERROR_MESSAGES
from app.persistence.models import Message, Project, Run, Thread
from app.persistence.repositories import (
    ArtifactsRepository,
    MessagesRepository,
    ProjectsRepository,
    RunStatesRepository,
    SourcesRepository,
    ThreadsRepository,
)
from app.services.content_safety import scrub_json_strings
from app.services.history_safety import MessageWrite, sanitize_message_content

router = APIRouter(prefix="/api", tags=["threads"])
logger = logging.getLogger(__name__)
_MAX_SOURCE_EXCERPT_CHARS = 300
_SAFE_RUN_STATUSES = frozenset(
    {"queued", "running", "completed", "failed", "cancelled", "interrupted"}
)
_SAFE_TERMINATION_REASONS = frozenset(
    {
        "submit",
        "forced_submit",
        "max_iters",
        "empty_tool_calls",
        "parse_error",
        "context_window_exceeded",
        "failed",
        "timeout",
        "cancelled",
        "server_restart",
        "approval_required",
        "approval_expired",
        "approval_invalid",
    }
)


def _cap_excerpt(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) <= _MAX_SOURCE_EXCERPT_CHARS:
        return value
    return value[: _MAX_SOURCE_EXCERPT_CHARS - 1] + "…"


def _safe_bootstrap_agent_state(
    state: dict[str, Any] | None, *, thread_id: str
) -> dict[str, Any] | None:
    """Validate a persisted snapshot before it crosses the API boundary."""

    if state is None:
        return None
    try:
        # Sanitization removes legacy/internal keys before strict contract
        # validation.  An invalid or cross-thread snapshot is not recoverable
        # for the browser, so omit it rather than returning raw database JSON.
        model = AgentWorkspaceState.model_validate(sanitize_message_content(state))
    except (TypeError, ValueError):
        logger.warning(
            "ignoring invalid persisted agent state for thread %s", thread_id
        )
        return None
    if model.threadId != thread_id:
        logger.warning(
            "ignoring cross-thread persisted agent state for thread %s", thread_id
        )
        return None

    safe = model.model_dump(mode="json")
    run = safe["run"]
    error_code = run.get("errorCode")
    if error_code is not None and error_code not in ERROR_MESSAGES:
        run.pop("errorCode", None)
    termination_reason = run.get("terminationReason")
    if (
        termination_reason is not None
        and termination_reason not in _SAFE_TERMINATION_REASONS
    ):
        run.pop("terminationReason", None)
    for source in safe["sources"]:
        source["excerpt"] = _cap_excerpt(source.get("excerpt"))
    # Legacy rows persisted before emission-time scrubbing get the same
    # treatment on read; new rows are already scrubbed at the source.
    scrubbed = scrub_json_strings(safe)
    return cast("dict[str, Any]", scrubbed)


def _safe_latest_run_payload(run: Run | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status if run.status in _SAFE_RUN_STATUSES else "failed",
        "terminationReason": (
            run.termination_reason
            if run.termination_reason in _SAFE_TERMINATION_REASONS
            else None
        ),
        "errorCode": run.error_code if run.error_code in ERROR_MESSAGES else None,
    }


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
    schemaVersion: int = 1
    thread: ThreadOut
    messageRepository: dict[str, Any]
    # Kept temporarily for older clients; new clients use messageRepository.
    messages: list[dict[str, Any]] = Field(default_factory=list)
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
    async with sessions() as session:
        async with session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )
            thread = await session.get(Thread, thread_id)
            if thread is None:
                raise HTTPException(status_code=404, detail="Thread not found.")
            project = await session.get(Project, thread.project_id)
            if project is None or project.owner_id != LOCAL_OWNER:
                raise HTTPException(status_code=404, detail="Thread not found.")
            messages_result = await session.execute(
                select(Message)
                .where(Message.thread_id == thread_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
            message_rows = list(messages_result.scalars())
            storage = [MessagesRepository.storage_dict(row) for row in message_rows]
            state_row = await RunStatesRepository.nearest_in_session(
                session,
                thread_id=thread_id,
                head_message_id=thread.active_head_message_id,
            )
            latest = (
                await session.get(Run, state_row.run_id)
                if state_row is not None and state_row.run_id is not None
                else None
            )
            if latest is None:
                candidates = list(
                    (
                        await session.execute(
                            select(Run)
                            .where(Run.thread_id == thread_id)
                            .order_by(Run.reserved_at.desc().nullslast(), Run.id.desc())
                        )
                    ).scalars()
                )
                if thread.active_head_message_id is not None:
                    parent_rows = list(
                        (
                            await session.execute(
                                select(
                                    Message.message_id, Message.parent_message_id
                                ).where(Message.thread_id == thread_id)
                            )
                        ).all()
                    )
                    parents = {message_id: parent for message_id, parent in parent_rows}
                    branch_ids: set[str] = set()
                    current_id: str | None = thread.active_head_message_id
                    while current_id is not None and current_id not in branch_ids:
                        branch_ids.add(current_id)
                        current_id = parents.get(current_id)
                    latest = next(
                        (
                            candidate
                            for candidate in candidates
                            if candidate.output_message_id in branch_ids
                            or candidate.input_message_id in branch_ids
                        ),
                        None,
                    )
                latest = latest or (candidates[0] if candidates else None)
            latest_payload = _safe_latest_run_payload(latest)
            repository = {
                "headId": thread.active_head_message_id,
                "messages": storage,
            }
            return BootstrapOut(
                thread=thread_to_out(thread),
                messageRepository=repository,
                messages=[
                    sanitize_message_content(row.message_json) for row in message_rows
                ],
                agentState=(
                    _safe_bootstrap_agent_state(
                        state_row.state_json, thread_id=thread_id
                    )
                    if state_row
                    else None
                ),
                latestRun=latest_payload,
            )


@router.put("/threads/{thread_id}/messages/{message_id}")
async def persist_thread_message(
    thread_id: str,
    message_id: str,
    body: MessageWrite,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> dict[str, str]:
    """Idempotently persist one safe assistant-ui branch node."""

    await require_thread(thread_id, sessions)
    if body.content.get("id") not in (None, message_id):
        raise HTTPException(status_code=422, detail="Message ID does not match path.")
    role = body.content.get("role")
    parent_id = body.parentId
    if parent_id == message_id:
        raise HTTPException(status_code=409, detail="A message cannot parent itself.")
    async with sessions() as session:
        async with session.begin():
            if parent_id is not None:
                parent = await session.scalar(
                    select(Message).where(
                        Message.thread_id == thread_id,
                        Message.message_id == parent_id,
                    )
                )
                if parent is None:
                    raise HTTPException(
                        status_code=409, detail="Unknown message parent."
                    )
                # Do not permit an update to attach a node below its own
                # descendant.  The common self-parent case is rejected
                # above; walking the short branch chain also protects legacy
                # rows whose parent was previously null.
                seen: set[str] = set()
                cursor: str | None = parent_id
                while cursor is not None and cursor not in seen:
                    if cursor == message_id:
                        raise HTTPException(
                            status_code=409,
                            detail="Message parent would create a branch cycle.",
                        )
                    seen.add(cursor)
                    cursor = await session.scalar(
                        select(Message.parent_message_id).where(
                            Message.thread_id == thread_id,
                            Message.message_id == cursor,
                        )
                    )
            try:
                row = await MessagesRepository.upsert_in_session(
                    session,
                    thread_id=thread_id,
                    role=str(role),
                    message_json={**body.content, "id": message_id},
                    message_id=message_id,
                    parent_message_id=parent_id,
                    format=body.format,
                    run_config_json=body.runConfig,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            head_update = update(Thread).where(Thread.id == thread_id)
            if role == "user" and body.format == "aui/v0":
                # A user edit may update the currently selected node, while a
                # new user fork appends below the current head.  Permit either
                # case, but never let a stale branch update win a concurrent
                # head change.
                if parent_id is None:
                    head_update = head_update.where(
                        or_(
                            Thread.active_head_message_id.is_(None),
                            Thread.active_head_message_id == row.message_id,
                        )
                    )
                else:
                    head_update = head_update.where(
                        or_(
                            Thread.active_head_message_id == parent_id,
                            Thread.active_head_message_id == row.message_id,
                        )
                    )
            elif parent_id is None:
                head_update = head_update.where(Thread.active_head_message_id.is_(None))
            else:
                head_update = head_update.where(
                    Thread.active_head_message_id == parent_id
                )
            await session.execute(
                head_update.values(
                    active_head_message_id=row.message_id,
                    updated_at=datetime.now(UTC),
                )
            )
    return {"id": message_id}


class HeadWrite(BaseModel):
    headId: str | None = None


@router.put("/threads/{thread_id}/history/head")
async def persist_thread_head(
    thread_id: str,
    body: HeadWrite,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> dict[str, str | None]:
    await require_thread(thread_id, sessions)
    async with sessions() as session:
        async with session.begin():
            if body.headId is not None:
                exists = await session.scalar(
                    select(Message.id).where(
                        Message.thread_id == thread_id,
                        Message.message_id == body.headId,
                    )
                )
                if exists is None:
                    raise HTTPException(status_code=409, detail="Unknown branch head.")
            await session.execute(
                update(Thread)
                .where(Thread.id == thread_id)
                .values(
                    active_head_message_id=body.headId,
                    updated_at=datetime.now(UTC),
                )
            )
    return {"headId": body.headId}


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
            "excerpt": _cap_excerpt(s.excerpt),
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
