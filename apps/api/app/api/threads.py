"""Threads REST resources + the /bootstrap payload for restoration."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import LOCAL_OWNER, get_sessions, require_project, require_thread
from app.contracts.agent_state import AgentWorkspaceState
from app.contracts.cards import settled_cards
from app.contracts.error_codes import ERROR_MESSAGES
from app.contracts.message_feedback import MessageFeedback
from app.contracts.termination_reasons import TERMINATION_REASONS
from app.contracts.thread_bootstrap import ThreadBootstrap, ThreadOut
from app.kernel.content_safety import scrub_json_strings, scrub_public_text
from app.kernel.history_safety import MessageWrite, sanitize_message_content
from app.kernel.run_input import validate_user_attachments, validate_user_content
from app.persistence.models import Artifact, Message, Run, RunState, Thread
from app.persistence.repositories import (
    ArtifactsRepository,
    MessagesRepository,
    SourcesRepository,
    ThreadsRepository,
)
from app.persistence.serializers import artifact_to_out, thread_to_out

router = APIRouter(prefix="/api", tags=["threads"])
logger = logging.getLogger(__name__)
_MAX_SOURCE_EXCERPT_CHARS = 300
# `interrupted` is accepted defensively, not because anything produces it: the
# startup sweep rewrites any surviving interrupted run and its persisted snapshot
# to `failed`/`server_restart`. The value only matters in the window before that
# sweep runs, which is a boot whose database was unreachable.
_SAFE_RUN_STATUSES = frozenset(
    {"queued", "running", "completed", "failed", "cancelled", "interrupted"}
)
# The canonical public reasons live in packages/contracts/termination-reasons.json;
# anything else persisted in the database is stripped before it reaches a client.
_SAFE_TERMINATION_REASONS = frozenset(TERMINATION_REASONS)


def _cap_excerpt(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) <= _MAX_SOURCE_EXCERPT_CHARS:
        return value
    return value[: _MAX_SOURCE_EXCERPT_CHARS - 1] + "…"


def _safe_bootstrap_agent_state(
    state: dict[str, Any] | None, *, thread_id: str, terminal_saved: bool = False
) -> dict[str, Any] | None:
    """Validate a persisted snapshot before it crosses the API boundary."""

    if state is None:
        return None
    if state.get("schemaVersion") == 1:
        state = {
            **state,
            "schemaVersion": 2,
            "run": {
                **state.get("run", {}),
                "saveStatus": "saved" if terminal_saved else "unknown",
            },
        }
    elif state.get("schemaVersion") == 2:
        run = dict(state.get("run", {}))
        if terminal_saved:
            run["saveStatus"] = "saved"
        elif run.get("saveStatus") == "saved":
            run["saveStatus"] = "unknown"
        state = {**state, "run": run}
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


class ThreadCreate(BaseModel):
    title: str = "New conversation"


class ThreadPatch(BaseModel):
    title: str


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


@router.get("/threads/{thread_id}/bootstrap", response_model_exclude_unset=True)
async def thread_bootstrap(
    thread_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> ThreadBootstrap:
    """Everything the client needs to restore a thread after reload/switch."""
    data = await ThreadsRepository(sessions).get_bootstrap_data(
        thread_id, owner_id=LOCAL_OWNER
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Thread not found.")
    thread, message_rows, state_row, latest = data
    storage = [MessagesRepository.storage_dict(row) for row in message_rows]
    latest_payload = _safe_latest_run_payload(latest)
    repository = {
        "headId": thread.active_head_message_id,
        "messages": storage,
    }
    messages_by_id = {row.message_id: row for row in message_rows}
    saved_head = (
        (
            latest.output_message_id
            if latest.status == "completed"
            else latest.input_message_id
        )
        if latest
        else None
    )
    saved_message = messages_by_id.get(saved_head) if saved_head else None
    message_identity_matches = bool(
        latest
        and saved_message
        and (
            (
                latest.status == "completed"
                and saved_message.role == "assistant"
                and saved_message.parent_message_id == latest.input_message_id
            )
            or (
                latest.status in {"failed", "cancelled"}
                and saved_message.role == "user"
            )
        )
    )
    cards = {}
    async with sessions() as session:
        states = (
            await session.execute(
                select(RunState, Run)
                .join(Run, RunState.run_id == Run.id)
                .where(RunState.thread_id == thread_id, Run.status == "completed")
            )
        ).all()
        artifact_rows = (
            await session.scalars(
                select(Artifact).where(Artifact.thread_id == thread_id)
            )
        ).all()
        artifact_owners = {artifact.id: artifact.run_id for artifact in artifact_rows}
        for snapshot, run in states:
            if (
                run.output_message_id in {row.message_id for row in message_rows}
                and run.output_message_id == snapshot.head_message_id
            ):
                safe_state = _safe_bootstrap_agent_state(
                    snapshot.state_json, thread_id=thread_id, terminal_saved=True
                )
                if safe_state and safe_state["run"]["id"] == run.id:
                    safe_state["artifacts"] = [
                        artifact
                        for artifact in safe_state.get("artifacts", [])
                        if artifact_owners.get(artifact.get("id")) == run.id
                    ]
                    cards[run.output_message_id] = settled_cards(
                        safe_state, run_id=run.id, message_id=run.output_message_id
                    )
    return ThreadBootstrap(
        schemaVersion=2,
        cards=cards,
        thread=thread_to_out(thread),
        messageRepository=repository,
        messages=[sanitize_message_content(row.message_json) for row in message_rows],
        agentState=(
            _safe_bootstrap_agent_state(
                state_row.state_json,
                thread_id=thread_id,
                terminal_saved=bool(
                    latest
                    and message_identity_matches
                    and latest.id == state_row.run_id
                    and latest.id == state_row.state_json.get("run", {}).get("id")
                    and latest.status in {"completed", "failed", "cancelled"}
                    and (
                        (
                            latest.output_message_id
                            if latest.status == "completed"
                            else latest.input_message_id
                        )
                        == state_row.head_message_id
                    )
                ),
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
    if role == "user":
        try:
            validate_user_content(body.content.get("content"))
            validate_user_attachments(body.content.get("attachments"))
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unsupported_input_type",
                    "message": ERROR_MESSAGES["unsupported_input_type"],
                },
            ) from None
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
            if role == "assistant" and message_id.startswith("msg-"):
                owning_run = await session.get(
                    Run, message_id.removeprefix("msg-"), with_for_update=True
                )
                if owning_run is not None and (
                    owning_run.thread_id != thread_id
                    or owning_run.status != "completed"
                    or owning_run.output_message_id != message_id
                ):
                    raise HTTPException(
                        status_code=409, detail="The run has not been durably saved."
                    )
                if owning_run is not None:
                    # Terminal persistence owns runtime answers and branch identity.
                    return {"id": message_id}
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
    try:
        await ThreadsRepository(sessions).set_active_head(thread_id, body.headId)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    sessions = request.app.state.db_sessions
    await require_thread(thread_id, sessions)
    artifacts = await ArtifactsRepository(sessions).list_for_thread(thread_id)
    return [artifact_to_out(a) for a in artifacts]


@router.get("/threads/{thread_id}/feedback")
async def list_feedback(
    thread_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> dict[str, MessageFeedback]:
    await require_thread(thread_id, sessions)
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(Message).where(
                    Message.thread_id == thread_id, Message.feedback_json.is_not(None)
                )
            )
        ).all()
        return {
            row.message_id: MessageFeedback.model_validate(row.feedback_json)
            for row in rows
            if isinstance(row.feedback_json, dict)
        }


@router.put("/threads/{thread_id}/messages/{message_id}/feedback")
async def save_feedback(
    thread_id: str,
    message_id: str,
    body: MessageFeedback,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> MessageFeedback:
    await require_thread(thread_id, sessions)
    if body.messageId != message_id:
        raise HTTPException(status_code=422, detail="Message ID does not match path.")
    async with sessions() as session:
        async with session.begin():
            message = await session.scalar(
                select(Message)
                .where(Message.thread_id == thread_id, Message.message_id == message_id)
                .with_for_update()
            )
            if message is None or message.role != "assistant":
                raise HTTPException(
                    status_code=404, detail="Assistant message not found."
                )
            run = await session.scalar(
                select(Run).where(
                    Run.thread_id == thread_id, Run.output_message_id == message_id
                )
            )
            snapshot = (
                await session.scalar(select(RunState).where(RunState.run_id == run.id))
                if run
                else None
            )
            version = (
                snapshot.state_json.get("run", {}).get("programVersion", "unknown")
                if snapshot
                else "unknown"
            )
            feedback = MessageFeedback(
                messageId=message_id,
                type=body.type,
                reason=scrub_public_text(body.reason) if body.reason else None,
                runId=run.id if run else None,
                branchParentId=message.parent_message_id,
                programVersion=str(version)[:128],
            )
            message.feedback_json = feedback.model_dump(mode="json", exclude_none=True)
        return feedback


@router.delete("/threads/{thread_id}/messages/{message_id}/feedback", status_code=204)
async def delete_feedback(
    thread_id: str,
    message_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> None:
    await require_thread(thread_id, sessions)
    async with sessions() as session:
        async with session.begin():
            message = await session.scalar(
                select(Message)
                .where(Message.thread_id == thread_id, Message.message_id == message_id)
                .with_for_update()
            )
            if message is None or message.role != "assistant":
                raise HTTPException(
                    status_code=404, detail="Assistant message not found."
                )
            message.feedback_json = None
