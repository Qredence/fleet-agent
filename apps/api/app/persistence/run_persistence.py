"""Transactional persistence for live DSPy runs.

The coordinator is a stream producer, so transactions are deliberately short:
one for reservation/start and one for each terminal transition. DSPy history
is always selected by branch ancestry and is never returned to the browser.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import dspy
from ag_ui.core import RunAgentInput
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.engine import AgentRunResult
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactStarted,
    SourceDiscovered,
)
from app.kernel.run_input import extract_message_text
from app.persistence.branch import nearest_anchor
from app.persistence.models import DspyHistory, Message, Run, Thread
from app.persistence.repositories import (
    ArtifactsRepository,
    DspyHistoriesRepository,
    MessagesRepository,
    RunAlreadyExistsError,
    RunsRepository,
    RunStatesRepository,
    SourcesRepository,
)

# The subset of domain events this layer persists (the full union lives in
# app.agui.types; tool/step events are reduced into state instead).
PersistedDomainEvent = (
    ArtifactStarted | ArtifactReady | ArtifactFailed | SourceDiscovered
)

logger = logging.getLogger(__name__)
HISTORY_SCHEMA_VERSION = 1
_UNSET = object()


class ReservationErrorCode(StrEnum):
    """Stable, typed reasons a run reservation can be rejected."""

    THREAD_NOT_FOUND = "thread_not_found"
    RUN_ALREADY_EXISTS = "run_already_exists"
    INPUT_MESSAGE_INVALID = "input_message_invalid"
    MESSAGE_PARENT_INVALID = "message_parent_invalid"
    MESSAGE_NOT_FOUND = "message_not_found"
    MESSAGE_WRONG_THREAD = "message_wrong_thread"
    RESERVATION_CONFLICT = "reservation_conflict"


class RunReservationError(RuntimeError):
    """A run cannot be reserved without changing persistent state.

    The code is deliberately separate from the exception text.  Routes map it
    to fixed public status/detail pairs and never serialize driver messages.
    """

    def __init__(self, code: ReservationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class RunPersistence:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def reserve_run(
        self,
        *,
        input_data: RunAgentInput,
        user_message: dict[str, Any] | None = None,
    ) -> Run:
        """Reserve a run and its input branch node atomically."""

        messages = [
            message.model_dump(by_alias=True, mode="json", exclude_none=True)
            for message in input_data.messages
        ]
        selected = user_message or _last_user_message_json(input_data)
        input_message_id, continuation_message_id = _branch_anchor(messages)
        if selected is not None:
            input_message_id = str(
                input_message_id or selected.get("id") or f"message-{input_data.run_id}"
            )
            selected = {**selected, "id": input_message_id}
        async with self._sessions() as session:
            async with session.begin():
                thread = await session.get(
                    Thread, input_data.thread_id, with_for_update=True
                )
                if thread is None:
                    raise RunReservationError(ReservationErrorCode.THREAD_NOT_FOUND)
                existing_input = await _validate_message_reference(
                    session,
                    thread_id=input_data.thread_id,
                    message_id=input_message_id,
                    label="input message",
                    allow_missing=True,
                )
                if existing_input is not None and existing_input.role != "user":
                    raise RunReservationError(
                        ReservationErrorCode.INPUT_MESSAGE_INVALID
                    )
                if existing_input is not None and continuation_message_id is None:
                    # assistant-ui reload/regenerate sends the existing user
                    # message as the path head. If its current assistant child
                    # is still selected, resume from that sibling's history
                    # while creating the next assistant as a new sibling.
                    active_message = None
                    if thread.active_head_message_id not in (
                        None,
                        input_message_id,
                    ):
                        active_message = await session.scalar(
                            select(Message).where(
                                Message.thread_id == input_data.thread_id,
                                Message.message_id == thread.active_head_message_id,
                            )
                        )
                        if (
                            active_message is not None
                            and active_message.role == "assistant"
                            and active_message.parent_message_id == input_message_id
                        ):
                            continuation_message_id = active_message.message_id
                    if continuation_message_id is None:
                        continuation_message_id = existing_input.parent_message_id
                elif (
                    continuation_message_id is None
                    and thread.active_head_message_id not in (None, input_message_id)
                ):
                    continuation_message_id = thread.active_head_message_id
                if continuation_message_id == input_message_id:
                    raise RunReservationError(
                        ReservationErrorCode.MESSAGE_PARENT_INVALID
                    )
                await _validate_message_reference(
                    session,
                    thread_id=input_data.thread_id,
                    message_id=continuation_message_id,
                    label="continuation message",
                    allow_missing=False,
                )
                # A regeneration resumes DSPy from the selected assistant
                # sibling, but the user node itself remains attached to its
                # original predecessor.  Reusing the continuation head as
                # the user node's parent would create a cycle
                # (user -> assistant -> user) on an existing branch.
                input_parent_message_id = (
                    existing_input.parent_message_id
                    if existing_input is not None
                    else continuation_message_id
                )
                try:
                    run = await RunsRepository.reserve_in_session(
                        session,
                        run_id=input_data.run_id,
                        thread_id=input_data.thread_id,
                        input_message_id=input_message_id,
                        continuation_message_id=continuation_message_id,
                    )
                    if selected and input_message_id:
                        await MessagesRepository.upsert_in_session(
                            session,
                            thread_id=input_data.thread_id,
                            role="user",
                            message_json=selected,
                            message_id=input_message_id,
                            parent_message_id=input_parent_message_id,
                            format="ag-ui/v1",
                        )
                except RunAlreadyExistsError as exc:
                    raise RunReservationError(
                        ReservationErrorCode.RUN_ALREADY_EXISTS
                    ) from exc
                except (IntegrityError, ValueError) as exc:
                    # Keep database/driver details in server logs only.  The
                    # route receives a typed code and emits a fixed message.
                    logger.exception(
                        "run reservation transaction failed (thread %s, run %s)",
                        input_data.thread_id,
                        input_data.run_id,
                    )
                    raise RunReservationError(
                        ReservationErrorCode.RESERVATION_CONFLICT
                    ) from exc
                await session.execute(
                    update(Thread)
                    .where(Thread.id == input_data.thread_id)
                    .values(
                        last_run_id=input_data.run_id,
                        active_head_message_id=input_message_id,
                        updated_at=datetime.now(UTC),
                    )
                )
                return run

    async def mark_running(
        self, *, run_id: str, state_json: dict[str, Any] | None = None
    ) -> None:
        async with self._sessions() as session:
            async with session.begin():
                run = await session.get(Run, run_id, with_for_update=True)
                if run is None:
                    raise RunReservationError(ReservationErrorCode.RESERVATION_CONFLICT)
                await RunsRepository.mark_running_in_session(session, run_id=run_id)
                if state_json is not None:
                    await RunStatesRepository.upsert_in_session(
                        session,
                        thread_id=run.thread_id,
                        run_id=run.id,
                        head_message_id=run.input_message_id,
                        state_json=state_json,
                    )

    async def get_run(self, run_id: str) -> Run | None:
        async with self._sessions() as session:
            return await session.get(Run, run_id)

    async def get_latest_state(
        self,
        thread_id: str,
        head_message_id: str | None | object = _UNSET,
    ) -> dict[str, Any] | None:
        if head_message_id is _UNSET:
            return await RunStatesRepository(self._sessions).get(thread_id)
        async with self._sessions() as session:
            state = await RunStatesRepository.nearest_in_session(
                session,
                thread_id=thread_id,
                head_message_id=head_message_id
                if isinstance(head_message_id, str)
                else None,
            )
            return state.state_json if state else None

    async def get_continuation_history(
        self,
        thread_id: str,
        head_message_id: str | None | object = _UNSET,
    ) -> dspy.History | None:
        repository = DspyHistoriesRepository(self._sessions)
        record = None
        if head_message_id is None:
            return None
        if head_message_id is _UNSET or not isinstance(head_message_id, str):
            record = await repository.get(thread_id)
        else:
            async with self._sessions() as session:
                record = await _nearest_history(session, thread_id, head_message_id)
        history = _history_from_record(record)
        if history is not None and getattr(history, "messages", None):
            return history

        async with self._sessions() as session:
            head_id = head_message_id if isinstance(head_message_id, str) else None
            return await self._history_from_messages_in_session(
                session,
                thread_id=thread_id,
                head_message_id=head_id,
            )

    @staticmethod
    async def _history_from_messages_in_session(
        session: AsyncSession,
        *,
        thread_id: str,
        head_message_id: str | None = None,
    ) -> dspy.History | None:
        """Reconstruct prior conversation turns from Message branch nodes."""
        rows = list(
            (
                await session.execute(
                    select(Message)
                    .where(Message.thread_id == thread_id)
                    .order_by(Message.created_at.asc(), Message.id.asc())
                )
            ).scalars()
        )
        if not rows:
            return None

        branch_rows: list[Message]
        if head_message_id is not None:
            by_id = {m.message_id: m for m in rows}
            curr: str | None = head_message_id
            seen: set[str] = set()
            reversed_branch: list[Message] = []
            while curr is not None and curr in by_id and curr not in seen:
                seen.add(curr)
                node = by_id[curr]
                reversed_branch.append(node)
                curr = node.parent_message_id
            if not reversed_branch:
                return None
            branch_rows = list(reversed(reversed_branch))
        else:
            branch_rows = rows

        turns: list[dict[str, Any]] = []
        pending_user: str | None = None
        for m in branch_rows:
            if not isinstance(m.message_json, dict):
                continue
            text = extract_message_text(m.message_json.get("content"))
            if m.role == "user":
                pending_user = text
            elif m.role == "assistant" and pending_user:
                if text:
                    turns.append({"user_request": pending_user, "answer": text})
                pending_user = None

        if not turns:
            return None
        return dspy.History(messages=turns)

    async def run_completed(
        self,
        *,
        thread_id: str,
        run_id: str,
        result: AgentRunResult,
        state_json: dict[str, Any],
        assistant_message_id: str,
    ) -> bool:
        async with self._sessions() as session:
            async with session.begin():
                run = await session.get(Run, run_id, with_for_update=True)
                if run is None or run.thread_id != thread_id:
                    return False
                if run.status not in {"queued", "running"}:
                    return False
                await MessagesRepository.upsert_in_session(
                    session,
                    thread_id=thread_id,
                    role="assistant",
                    message_json={
                        "id": assistant_message_id,
                        "role": "assistant",
                        "content": result.answer or "",
                    },
                    message_id=assistant_message_id,
                    parent_message_id=run.input_message_id,
                    format="ag-ui/v1",
                )
                changed = await RunsRepository.settle_in_session(
                    session,
                    run_id=run_id,
                    status="completed",
                    termination_reason=result.termination_reason,
                    token_usage=result.usage or None,
                    error_code=None,
                    output_message_id=assistant_message_id,
                )
                if not changed:
                    return False
                # Terminal settlement records the final snapshot so a follow-up
                # turn continues from what actually settled, not from a stale
                # intermediate state.
                await RunStatesRepository.upsert_in_session(
                    session,
                    thread_id=thread_id,
                    run_id=run_id,
                    head_message_id=assistant_message_id,
                    state_json=state_json,
                )
                await self._persist_history_in_session(
                    session,
                    thread_id=thread_id,
                    head_message_id=assistant_message_id,
                    result=result,
                )
                await session.execute(
                    update(Thread)
                    .where(
                        Thread.id == thread_id,
                        Thread.active_head_message_id == run.input_message_id,
                    )
                    .values(
                        active_head_message_id=assistant_message_id,
                        updated_at=datetime.now(UTC),
                    )
                )
                return True

    async def run_failed(
        self,
        *,
        thread_id: str,
        run_id: str,
        result: AgentRunResult,
        state_json: dict[str, Any],
    ) -> bool:
        return await self._settle_non_completed(
            thread_id=thread_id,
            run_id=run_id,
            status="failed",
            termination_reason=result.termination_reason,
            token_usage=result.usage or None,
            error_code=result.error_code or "agent_no_output",
            state_json=state_json,
            result=result,
        )

    async def run_cancelled(
        self, *, thread_id: str, run_id: str, state_json: dict[str, Any]
    ) -> bool:
        return await self._settle_non_completed(
            thread_id=thread_id,
            run_id=run_id,
            status="cancelled",
            termination_reason="cancelled",
            token_usage=None,
            error_code="run_cancelled",
            state_json=state_json,
            result=None,
        )

    async def _settle_non_completed(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: str,
        termination_reason: str | None,
        token_usage: dict[str, Any] | None,
        error_code: str | None,
        state_json: dict[str, Any],
        result: AgentRunResult | None,
    ) -> bool:
        async with self._sessions() as session:
            async with session.begin():
                run = await session.get(Run, run_id, with_for_update=True)
                if run is None or run.thread_id != thread_id:
                    return False
                changed = await RunsRepository.settle_in_session(
                    session,
                    run_id=run_id,
                    status=status,
                    termination_reason=termination_reason,
                    token_usage=token_usage,
                    error_code=error_code,
                )
                if not changed:
                    return False
                # Terminal settlement records the final snapshot so a follow-up
                # turn continues from what actually settled, not from a stale
                # intermediate state.
                await RunStatesRepository.upsert_in_session(
                    session,
                    thread_id=thread_id,
                    run_id=run_id,
                    head_message_id=run.input_message_id,
                    state_json=state_json,
                )
                if result is not None:
                    await self._persist_history_in_session(
                        session,
                        thread_id=thread_id,
                        head_message_id=run.input_message_id,
                        result=result,
                    )
                return True

    @staticmethod
    async def _persist_history_in_session(
        session: AsyncSession,
        *,
        thread_id: str,
        head_message_id: str | None,
        result: AgentRunResult,
    ) -> None:
        if result.history is None:
            return
        history = _normalize_history_tool_call_ids(result.history)
        history_json = history.model_dump(mode="json")
        for turn_idx, msg in enumerate(history_json.get("messages", [])):
            tc_dict = msg.get("tool_calls")
            if isinstance(tc_dict, dict) and "tool_calls" in tc_dict:
                tcr_dict = tc_dict.get("tool_call_results")
                tcr_list = (
                    tcr_dict.get("tool_call_results", [])
                    if isinstance(tcr_dict, dict)
                    else []
                )
                for idx, call_dict in enumerate(tc_dict["tool_calls"]):
                    if isinstance(call_dict, dict) and not call_dict.get("id"):
                        if idx < len(tcr_list) and isinstance(tcr_list[idx], dict):
                            call_dict["id"] = (
                                tcr_list[idx].get("call_id") or f"call_{turn_idx}_{idx}"
                            )
                        else:
                            call_dict["id"] = f"call_{turn_idx}_{idx}"

        await DspyHistoriesRepository.upsert_in_session(
            session,
            thread_id=thread_id,
            head_message_id=head_message_id,
            schema_version=HISTORY_SCHEMA_VERSION,
            dspy_version=dspy.__version__,
            history_json=history_json,
        )

    async def record_domain_event(
        self, event: PersistedDomainEvent, *, thread_id: str, run_id: str
    ) -> None:
        """Persist sources/artifacts as they are discovered mid-run."""

        if isinstance(event, SourceDiscovered):
            await SourcesRepository(self._sessions).add(
                source_id=event.source.id,
                thread_id=thread_id,
                run_id=run_id,
                tool_call_id=event.tool_call_id,
                title=event.source.title,
                source_type=event.source.source_type,
                uri=event.source.uri,
                excerpt=event.source.excerpt,
            )
        elif isinstance(event, ArtifactStarted):
            await ArtifactsRepository(self._sessions).add(
                artifact_id=event.artifact.id,
                thread_id=thread_id,
                run_id=run_id,
                name=event.artifact.name,
                media_type=event.artifact.media_type,
                storage_key=event.artifact.storage_key,
            )
        elif isinstance(event, ArtifactReady):
            await ArtifactsRepository(self._sessions).mark_ready(
                event.artifact.id, size_bytes=event.artifact.size_bytes or 0
            )
        elif isinstance(event, ArtifactFailed):
            await ArtifactsRepository(self._sessions).mark_failed(event.artifact_id)


def _last_user_message_json(input_data: RunAgentInput) -> dict[str, Any] | None:
    for message in reversed(input_data.messages):
        if message.role == "user":
            return message.model_dump(by_alias=True, mode="json", exclude_none=True)
    return None


def _branch_anchor(
    messages: Sequence[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """Locate the last user message and its branchable parent.

    The AG-UI payload interleaves frontend-only tool-result messages
    (role "tool") between the assistant text and the next user turn. Only
    user/assistant messages exist in the persisted branch, so the parent
    anchor must skip everything else — anchoring on a tool message id
    would fail reservation with MESSAGE_NOT_FOUND.
    """
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") != "user":
            continue
        message_id = messages[index].get("id")
        parent_id: str | None = None
        for predecessor in range(index - 1, -1, -1):
            if messages[predecessor].get("role") in ("user", "assistant"):
                raw_parent = messages[predecessor].get("id")
                parent_id = str(raw_parent) if raw_parent else None
                break
        return (
            str(message_id) if message_id else None,
            parent_id,
        )
    return None, None


async def _validate_message_reference(
    session: AsyncSession,
    *,
    thread_id: str,
    message_id: str | None,
    label: str = "",
    allow_missing: bool,
) -> Message | None:
    if message_id is None:
        return None
    row = await session.scalar(
        select(Message).where(
            Message.thread_id == thread_id,
            Message.message_id == message_id,
        )
    )
    if row is not None:
        return row
    other_threads = list(
        (
            await session.execute(
                select(Message.thread_id).where(Message.message_id == message_id)
            )
        ).scalars()
    )
    if other_threads:
        raise RunReservationError(ReservationErrorCode.MESSAGE_WRONG_THREAD)
    if not allow_missing:
        raise RunReservationError(ReservationErrorCode.MESSAGE_NOT_FOUND)
    return None


async def _nearest_history(
    session: AsyncSession, thread_id: str, head_message_id: str
) -> DspyHistory | None:
    """Return the nearest DSPy history on the branch ending at ``head_message_id``."""
    return await nearest_anchor(
        session,
        thread_id=thread_id,
        head_message_id=head_message_id,
        model=DspyHistory,
    )


def _normalize_history_tool_call_ids(history: dspy.History) -> dspy.History:
    """Ensure tool_calls and tool_call_results have matching IDs across turns."""
    for turn_idx, msg in enumerate(history.messages):
        tc = msg.get("tool_calls")
        if tc is not None:
            if isinstance(tc, dict):
                tc = dspy.adapters.types.tool.ToolCalls.model_validate(tc)
                msg["tool_calls"] = tc
            tcr = getattr(tc, "tool_call_results", None)
            if isinstance(tcr, dict):
                tcr = dspy.adapters.types.tool.ToolCallResults.model_validate(tcr)
                tc.tool_call_results = tcr

            tcr_list = tcr.tool_call_results if tcr else []
            for idx, call in enumerate(tc.tool_calls):
                if call.id is None and idx < len(tcr_list):
                    call.id = tcr_list[idx].call_id
                elif call.id is None:
                    call.id = f"call_{turn_idx}_{idx}"
    return history


def _history_from_record(record: DspyHistory | None) -> dspy.History | None:
    if record is None or record.schema_version != HISTORY_SCHEMA_VERSION:
        return None
    history = dspy.History.model_validate(record.history_json)
    return _normalize_history_tool_call_ids(history)
