"""Threads REST resources + the /bootstrap payload for restoration."""

import logging
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    LOCAL_OWNER,
    get_sessions,
    reject_unsupported_user_input,
    require_project,
    require_thread,
)
from app.contracts.agent_state import AgentWorkspaceState
from app.contracts.cards import settled_cards
from app.contracts.constants import ERROR_MESSAGES, TERMINATION_REASONS
from app.contracts.message_feedback import MessageFeedback
from app.contracts.thread_bootstrap import (
    LatestRun,
    MessageRepository,
    MessageStorageEntry,
    ThreadBootstrap,
    ThreadOut,
)
from app.kernel.content_safety import scrub_json_strings, scrub_public_text
from app.kernel.history_safety import MessageWrite, sanitize_message_content
from app.persistence.models import Run
from app.persistence.repositories import (
    ArtifactsRepository,
    MessageConflictError,
    MessagesRepository,
    SourcesRepository,
    ThreadsRepository,
    cap_source_excerpt,
)
from app.persistence.serializers import artifact_to_out, thread_to_out

router = APIRouter(prefix="/api", tags=["threads"])
logger = logging.getLogger(__name__)
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
        source["excerpt"] = cap_source_excerpt(source.get("excerpt"))
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
    thread = data.thread
    message_rows = data.messages
    state_row = data.state_row
    latest = data.latest_run

    storage = [MessagesRepository.storage_dict(row) for row in message_rows]
    latest_payload = _safe_latest_run_payload(latest)
    repository = MessageRepository(
        headId=thread.active_head_message_id,
        messages=[MessageStorageEntry.model_validate(item) for item in storage],
    )
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
    artifact_owners = {artifact.id: artifact.run_id for artifact in data.artifacts}
    message_ids = set(messages_by_id)
    for snapshot, run in data.completed_states:
        if (
            run.output_message_id in message_ids
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
        latestRun=(
            LatestRun.model_validate(latest_payload)
            if latest_payload is not None
            else None
        ),
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
        reject_unsupported_user_input(
            body.content.get("content"), body.content.get("attachments")
        )
    try:
        await MessagesRepository(sessions).persist_branch_node(
            thread_id=thread_id,
            message_id=message_id,
            parent_id=body.parentId,
            role=str(role),
            format=body.format,
            message_json={**body.content, "id": message_id},
            run_config_json=body.runConfig,
        )
    except MessageConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return thread_to_out(thread)


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    request: Request,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> None:
    await require_thread(thread_id, sessions)
    await ThreadsRepository(sessions).delete(thread_id)
    # Retention: a deleted thread's artifact files are removed with it.
    request.app.state.artifact_storage.delete_prefix(f"{thread_id}/")


@router.get("/threads/{thread_id}/sources")
async def list_sources(
    thread_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> list[dict[str, Any]]:
    await require_thread(thread_id, sessions)
    sources = await SourcesRepository(sessions).list_for_thread(thread_id)
    return [
        {
            "id": s.id,
            "title": scrub_public_text(s.title),
            "sourceType": s.source_type,
            "uri": scrub_public_text(s.uri) if s.uri is not None else None,
            "excerpt": (
                cap_source_excerpt(scrub_public_text(s.excerpt))
                if s.excerpt is not None
                else None
            ),
            "toolCallId": s.tool_call_id,
        }
        for s in sources
    ]


@router.get("/threads/{thread_id}/artifacts")
async def list_artifacts(
    thread_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> list[dict[str, Any]]:
    await require_thread(thread_id, sessions)
    artifacts = await ArtifactsRepository(sessions).list_for_thread(thread_id)
    return [artifact_to_out(a) for a in artifacts]


@router.get("/threads/{thread_id}/feedback")
async def list_feedback(
    thread_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> dict[str, MessageFeedback]:
    await require_thread(thread_id, sessions)
    rows = await MessagesRepository(sessions).list_feedback_rows(thread_id)
    result: dict[str, MessageFeedback] = {}
    for message_id, feedback_json in rows:
        if not isinstance(feedback_json, dict):
            continue
        try:
            result[message_id] = MessageFeedback.model_validate(feedback_json)
        except (TypeError, ValidationError):
            logger.warning(
                "ignoring invalid persisted feedback for message %s in thread %s",
                message_id,
                thread_id,
            )
    return result


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
    feedback = await MessagesRepository(sessions).save_feedback(
        thread_id=thread_id,
        message_id=message_id,
        feedback_type=body.type,
        reason=body.reason,
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="Assistant message not found.")
    return feedback


@router.delete("/threads/{thread_id}/messages/{message_id}/feedback", status_code=204)
async def delete_feedback(
    thread_id: str,
    message_id: str,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> None:
    await require_thread(thread_id, sessions)
    deleted = await MessagesRepository(sessions).delete_feedback(
        thread_id=thread_id, message_id=message_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Assistant message not found.")
