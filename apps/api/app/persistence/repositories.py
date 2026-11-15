"""Typed queries only — no route logic, no run orchestration.

One module with one import surface: callers write
``from app.persistence.repositories import X`` and never reach for a submodule.
Keeping the aggregate repositories together makes the sharing visible — several
of them reuse ``new_id``, ``nearest_anchor`` and each other — while the SQL and
the session plumbing stay in one place.
"""

from __future__ import annotations

import builtins
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.message_feedback import MessageFeedback
from app.kernel.content_safety import scrub_public_text
from app.kernel.history_safety import sanitize_message_content
from app.kernel.identity import canonical_source_key, disambiguated_source_id
from app.persistence.branch import nearest_anchor
from app.persistence.models import (
    Artifact,
    DspyHistory,
    Message,
    Project,
    Run,
    RunState,
    Source,
    Thread,
)

__all__ = [
    "ArtifactsRepository",
    "BootstrapData",
    "DspyHistoriesRepository",
    "MessageConflictError",
    "MessagesRepository",
    "ProjectsRepository",
    "RunAlreadyExistsError",
    "RunStatesRepository",
    "RunsRepository",
    "SourcesRepository",
    "ThreadsRepository",
    "cap_source_excerpt",
    "new_id",
]


def _head_conflict_target(head_message_id: str | None) -> dict[str, Any]:
    """Return PostgreSQL conflict target args matching the unique indexes."""
    if head_message_id is None:
        return {
            "index_elements": ["thread_id"],
            "index_where": text("head_message_id IS NULL"),
        }
    return {"index_elements": ["thread_id", "head_message_id"]}


class MessageConflictError(ValueError):
    """Typed 409 conflict raised on invalid branch message persistence."""


@dataclass(frozen=True, slots=True)
class BootstrapData:
    """Consistent single-transaction snapshot used to render thread bootstrap."""

    thread: Thread
    messages: list[Message]
    state_row: RunState | None
    latest_run: Run | None
    completed_states: list[tuple[RunState, Run]]
    artifacts: list[Artifact]


# --- helpers ------------------------------------------------------------
def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --- artifacts ----------------------------------------------------------
class ArtifactsRepository:
    @staticmethod
    async def _add_in_session(
        session: AsyncSession,
        *,
        artifact_id: str,
        thread_id: str,
        run_id: str,
        name: str,
        media_type: str,
        storage_key: str,
    ) -> None:
        await session.execute(
            pg_insert(Artifact)
            .values(
                id=artifact_id,
                thread_id=thread_id,
                run_id=run_id,
                name=name,
                media_type=media_type,
                storage_key=storage_key,
                status="generating",
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.flush()

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(
        self,
        *,
        artifact_id: str,
        thread_id: str,
        run_id: str,
        name: str,
        media_type: str,
        storage_key: str,
    ) -> None:
        async with self._sessions() as session:
            await self._add_in_session(
                session,
                artifact_id=artifact_id,
                thread_id=thread_id,
                run_id=run_id,
                name=name,
                media_type=media_type,
                storage_key=storage_key,
            )
            await session.commit()

    async def mark_ready(self, artifact_id: str, *, size_bytes: int) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(Artifact)
                .where(Artifact.id == artifact_id)
                .values(status="ready", size_bytes=size_bytes)
            )
            await session.commit()

    async def mark_failed(self, artifact_id: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(Artifact)
                .where(Artifact.id == artifact_id)
                .values(status="failed")
            )
            await session.commit()

    async def get(self, artifact_id: str) -> Artifact | None:
        async with self._sessions() as session:
            return await session.get(Artifact, artifact_id)

    async def list_for_thread(self, thread_id: str) -> list[Artifact]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Artifact)
                .where(Artifact.thread_id == thread_id)
                .order_by(Artifact.created_at.asc())
            )
            return list(rows.scalars())


# --- histories ----------------------------------------------------------
class DspyHistoriesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    async def upsert_in_session(
        session: AsyncSession,
        *,
        thread_id: str,
        schema_version: int,
        dspy_version: str,
        history_json: dict[str, Any],
        head_message_id: str | None = None,
    ) -> DspyHistory:
        now = datetime.now(UTC)
        stmt = (
            pg_insert(DspyHistory)
            .values(
                id=new_id("history"),
                thread_id=thread_id,
                head_message_id=head_message_id,
                schema_version=schema_version,
                dspy_version=dspy_version,
                history_json=history_json,
                updated_at=now,
            )
            .on_conflict_do_update(
                **_head_conflict_target(head_message_id),
                set_={
                    "schema_version": schema_version,
                    "dspy_version": dspy_version,
                    "history_json": history_json,
                    "updated_at": now,
                },
            )
            .returning(DspyHistory)
        )
        row = await session.scalar(
            select(DspyHistory)
            .from_statement(stmt)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("DspyHistory upsert failed to return a row.")
        await session.flush()
        return cast(DspyHistory, row)

    async def get(
        self, thread_id: str, head_message_id: str | None = None
    ) -> DspyHistory | None:
        async with self._sessions() as session:
            query = select(DspyHistory).where(DspyHistory.thread_id == thread_id)
            if head_message_id is not None:
                query = query.where(DspyHistory.head_message_id == head_message_id)
            query = query.order_by(DspyHistory.updated_at.desc()).limit(1)
            return cast(DspyHistory | None, await session.scalar(query))

    async def list_for_thread(self, thread_id: str) -> list[DspyHistory]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(DspyHistory)
                .where(DspyHistory.thread_id == thread_id)
                .order_by(DspyHistory.updated_at.desc())
            )
            return list(rows.scalars())


# --- messages -----------------------------------------------------------
class MessagesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(
        self,
        *,
        thread_id: str,
        role: str,
        message_json: dict[str, Any],
        message_id: str | None = None,
        parent_message_id: str | None = None,
        format: str = "ag-ui/v1",
        run_config_json: dict[str, Any] | None = None,
    ) -> Message:
        async with self._sessions() as session:
            row = await self.upsert_in_session(
                session,
                thread_id=thread_id,
                role=role,
                message_json=message_json,
                message_id=message_id,
                parent_message_id=parent_message_id,
                format=format,
                run_config_json=run_config_json,
            )
            await session.commit()
            return row

    @staticmethod
    async def upsert_in_session(
        session: AsyncSession,
        *,
        thread_id: str,
        role: str,
        message_json: dict[str, Any],
        message_id: str | None = None,
        parent_message_id: str | None = None,
        format: str = "ag-ui/v1",
        run_config_json: dict[str, Any] | None = None,
    ) -> Message:
        resolved_id = message_id or str(message_json.get("id") or new_id("message"))
        if parent_message_id == resolved_id:
            raise ValueError("A message cannot parent itself.")
        safe_message_json = sanitize_message_content(message_json)
        safe_run_config_json = (
            sanitize_message_content(run_config_json)
            if run_config_json is not None
            else None
        )
        result = await session.execute(
            select(Message)
            .where(
                Message.thread_id == thread_id,
                Message.message_id == resolved_id,
            )
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = Message(
                id=new_id("message_row"),
                thread_id=thread_id,
                message_id=resolved_id,
                parent_message_id=parent_message_id,
                role=role,
                format=format,
                message_json=safe_message_json,
                run_config_json=safe_run_config_json,
            )
            session.add(row)
            await session.flush()
            return row

        if row.role != role:
            raise ValueError("Message role does not match the existing branch node.")
        if row.parent_message_id not in (None, parent_message_id):
            raise ValueError("Message parent does not match the existing branch node.")
        # A server fallback must never overwrite an exact assistant-ui row.
        if row.format != "aui/v0" or format == "aui/v0":
            row.format = format
            row.message_json = safe_message_json
            if safe_run_config_json is not None or format != "aui/v0":
                row.run_config_json = safe_run_config_json
        if row.parent_message_id is None:
            row.parent_message_id = parent_message_id
        row.updated_at = datetime.now(UTC)
        await session.flush()
        return row

    @staticmethod
    def storage_dict(row: Message) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": row.message_id,
            "parentId": row.parent_message_id,
            "format": row.format,
            "content": sanitize_message_content(row.message_json),
        }
        if row.run_config_json is not None:
            item["runConfig"] = sanitize_message_content(row.run_config_json)
        return item

    async def list_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Message.message_json)
                .where(Message.thread_id == thread_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
            return [sanitize_message_content(item) for item in rows.scalars()]

    async def persist_branch_node(
        self,
        *,
        thread_id: str,
        message_id: str,
        parent_id: str | None,
        role: str,
        format: str,
        message_json: dict[str, Any],
        run_config_json: dict[str, Any] | None,
    ) -> None:
        """Persist a branch message node idempotently and advance active head."""
        if parent_id == message_id:
            raise MessageConflictError("A message cannot parent itself.")
        async with self._sessions() as session:
            async with session.begin():
                if parent_id is not None:
                    parent_rows = (
                        await session.execute(
                            select(Message.message_id, Message.parent_message_id).where(
                                Message.thread_id == thread_id
                            )
                        )
                    ).all()
                    parents = {mid: pid for mid, pid in parent_rows}
                    if parent_id not in parents:
                        raise MessageConflictError("Unknown message parent.")
                    seen: set[str] = set()
                    cursor: str | None = parent_id
                    while cursor is not None and cursor not in seen:
                        if cursor == message_id:
                            raise MessageConflictError(
                                "Message parent would create a branch cycle."
                            )
                        seen.add(cursor)
                        cursor = parents.get(cursor)
                if role == "assistant" and message_id.startswith("msg-"):
                    owning_run = await session.get(
                        Run, message_id.removeprefix("msg-"), with_for_update=True
                    )
                    if owning_run is not None and (
                        owning_run.thread_id != thread_id
                        or owning_run.status != "completed"
                        or owning_run.output_message_id != message_id
                    ):
                        raise MessageConflictError(
                            "The run has not been durably saved."
                        )
                    if owning_run is not None:
                        return
                try:
                    row = await self.upsert_in_session(
                        session,
                        thread_id=thread_id,
                        role=role,
                        message_json=message_json,
                        message_id=message_id,
                        parent_message_id=parent_id,
                        format=format,
                        run_config_json=run_config_json,
                    )
                except ValueError as exc:
                    raise MessageConflictError(str(exc)) from exc
                head_update = update(Thread).where(Thread.id == thread_id)
                if role == "user" and format == "aui/v0":
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
                    head_update = head_update.where(
                        Thread.active_head_message_id.is_(None)
                    )
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

    async def list_feedback_rows(self, thread_id: str) -> list[tuple[str, Any]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Message.message_id, Message.feedback_json).where(
                    Message.thread_id == thread_id,
                    Message.feedback_json.is_not(None),
                )
            )
            return [(row[0], row[1]) for row in rows.all()]

    async def save_feedback(
        self,
        *,
        thread_id: str,
        message_id: str,
        feedback_type: str,
        reason: str | None,
    ) -> MessageFeedback | None:
        async with self._sessions() as session:
            async with session.begin():
                message = await session.scalar(
                    select(Message)
                    .where(
                        Message.thread_id == thread_id,
                        Message.message_id == message_id,
                    )
                    .with_for_update()
                )
                if message is None or message.role != "assistant":
                    return None
                run = await session.scalar(
                    select(Run).where(
                        Run.thread_id == thread_id, Run.output_message_id == message_id
                    )
                )
                snapshot = (
                    await session.scalar(
                        select(RunState).where(RunState.run_id == run.id)
                    )
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
                    type=cast(Any, feedback_type),
                    reason=scrub_public_text(reason) if reason else None,
                    runId=run.id if run else None,
                    branchParentId=message.parent_message_id,
                    programVersion=str(version)[:128],
                )
                message.feedback_json = feedback.model_dump(
                    mode="json", exclude_none=True
                )
                return feedback

    async def delete_feedback(self, *, thread_id: str, message_id: str) -> bool:
        async with self._sessions() as session:
            async with session.begin():
                message = await session.scalar(
                    select(Message)
                    .where(
                        Message.thread_id == thread_id,
                        Message.message_id == message_id,
                    )
                    .with_for_update()
                )
                if message is None or message.role != "assistant":
                    return False
                message.feedback_json = None
                return True


# --- projects -----------------------------------------------------------
class ProjectsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, *, name: str, owner_id: str = "local") -> Project:
        async with self._sessions() as session:
            project = Project(id=new_id("project"), owner_id=owner_id, name=name)
            session.add(project)
            await session.commit()
            return project

    async def list(self, *, owner_id: str = "local") -> builtins.list[Project]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Project)
                .where(Project.owner_id == owner_id)
                .order_by(Project.created_at.desc())
            )
            return list(rows.scalars())

    async def get(self, project_id: str) -> Project | None:
        async with self._sessions() as session:
            return await session.get(Project, project_id)

    async def rename(self, project_id: str, *, name: str) -> Project | None:
        async with self._sessions() as session:
            project = await session.get(Project, project_id)
            if project is None:
                return None
            project.name = name
            project.updated_at = datetime.now(UTC)
            await session.commit()
            return project

    async def delete(self, project_id: str) -> bool:
        async with self._sessions() as session:
            result = await session.execute(
                delete(Project).where(Project.id == project_id)
            )
            await session.commit()
            return bool(getattr(result, "rowcount", 0))


# --- runs ---------------------------------------------------------------
class RunAlreadyExistsError(RuntimeError):
    """Typed duplicate-run conflict for reservation callers."""


class RunsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    async def reserve_in_session(
        session: AsyncSession,
        *,
        run_id: str,
        thread_id: str,
        input_message_id: str | None,
        continuation_message_id: str | None,
        reserved_at: datetime | None = None,
    ) -> Run:
        existing = await session.get(Run, run_id, with_for_update=True)
        if existing is not None:
            raise RunAlreadyExistsError()
        now = reserved_at or datetime.now(UTC)
        row = Run(
            id=run_id,
            thread_id=thread_id,
            status="queued",
            reserved_at=now,
            started_at=None,
            input_message_id=input_message_id,
            continuation_message_id=continuation_message_id,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def mark_running_in_session(session: AsyncSession, *, run_id: str) -> bool:
        result = await session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == "queued")
            .values(status="running", started_at=datetime.now(UTC))
        )
        return bool(getattr(result, "rowcount", 0))

    @staticmethod
    async def settle_in_session(
        session: AsyncSession,
        *,
        run_id: str,
        status: str,
        termination_reason: str | None,
        token_usage: dict[str, Any] | None,
        error_code: str | None,
        output_message_id: str | None = None,
    ) -> bool:
        result = await session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status.in_(["queued", "running"]))
            .values(
                status=status,
                termination_reason=termination_reason,
                finished_at=datetime.now(UTC),
                token_usage=token_usage,
                error_code=error_code,
                output_message_id=output_message_id,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def get(self, run_id: str) -> Run | None:
        async with self._sessions() as session:
            return await session.get(Run, run_id)

    async def mark_orphaned_interrupted(self) -> int:
        """Fail runs a restart orphaned.

        No in-memory run state survives a restart, so anything still marked
        live is stale by definition: one statement settles them all.
        """
        async with self._sessions() as session:
            orphaned_ids = list(
                (
                    await session.execute(
                        select(Run.id).where(
                            Run.status.in_(["running", "queued", "interrupted"]),
                        )
                    )
                ).scalars()
            )
            if not orphaned_ids:
                return 0
            result = await session.execute(
                update(Run)
                .where(
                    Run.status.in_(["running", "queued", "interrupted"]),
                )
                .values(
                    status="failed",
                    termination_reason="server_restart",
                    finished_at=datetime.now(UTC),
                    error_code="internal_error",
                )
            )
            states = list(
                (
                    await session.execute(
                        select(RunState).where(RunState.run_id.in_(orphaned_ids))
                    )
                ).scalars()
            )
            for state in states:
                snapshot = dict(state.state_json)
                run_state = dict(snapshot.get("run") or {})
                run_state.update(
                    {
                        "status": "failed",
                        "terminationReason": "server_restart",
                        "saveStatus": "saved",
                        "errorCode": "internal_error",
                    }
                )
                snapshot["run"] = run_state
                state.state_json = snapshot
                state.updated_at = datetime.now(UTC)
            await session.commit()
            rowcount: int = getattr(result, "rowcount", 0) or 0
            return rowcount


# --- states -------------------------------------------------------------
class RunStatesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    async def upsert_in_session(
        session: AsyncSession,
        *,
        thread_id: str,
        state_json: dict[str, Any],
        run_id: str | None = None,
        head_message_id: str | None = None,
    ) -> RunState:
        now = datetime.now(UTC)
        set_values: dict[str, Any] = {
            "state_json": state_json,
            "updated_at": now,
        }
        if run_id:
            set_values["run_id"] = run_id
        stmt = (
            pg_insert(RunState)
            .values(
                id=new_id("state"),
                thread_id=thread_id,
                run_id=run_id,
                head_message_id=head_message_id,
                state_json=state_json,
                updated_at=now,
            )
            .on_conflict_do_update(
                **_head_conflict_target(head_message_id),
                set_=set_values,
            )
            .returning(RunState)
        )
        row = await session.scalar(
            select(RunState)
            .from_statement(stmt)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("RunState upsert failed to return a row.")
        await session.flush()
        return cast(RunState, row)

    @staticmethod
    async def nearest_in_session(
        session: AsyncSession, *, thread_id: str, head_message_id: str | None
    ) -> RunState | None:
        """Return the nearest run state on the branch ending at ``head_message_id``."""
        return await nearest_anchor(
            session,
            thread_id=thread_id,
            head_message_id=head_message_id,
            model=RunState,
        )

    async def get(
        self, thread_id: str, head_message_id: str | None = None
    ) -> dict[str, Any] | None:
        async with self._sessions() as session:
            query = select(RunState).where(RunState.thread_id == thread_id)
            if head_message_id is not None:
                query = query.where(RunState.head_message_id == head_message_id)
            query = query.order_by(RunState.updated_at.desc()).limit(1)
            row = await session.scalar(query)
            return row.state_json if row else None


# --- sources ------------------------------------------------------------
_MAX_SOURCE_EXCERPT_CHARS = 300


def cap_source_excerpt(excerpt: str | None) -> str | None:
    """Cap one source excerpt at the public 300-character bound."""
    if excerpt is None:
        return None
    excerpt = excerpt.strip()
    if len(excerpt) <= _MAX_SOURCE_EXCERPT_CHARS:
        return excerpt
    return excerpt[: _MAX_SOURCE_EXCERPT_CHARS - 1] + "…"


class SourcesRepository:
    @staticmethod
    async def _add_in_session(
        session: AsyncSession,
        *,
        source_id: str,
        thread_id: str,
        run_id: str,
        tool_call_id: str | None,
        title: str,
        source_type: str,
        uri: str | None,
        excerpt: str | None,
    ) -> Source:
        # Sources are persisted and later served by several endpoints, so scrub
        # and cap excerpts here rather than relying only on the live reducer preview.
        title = scrub_public_text(title)
        uri = scrub_public_text(uri) if uri is not None else None
        excerpt = (
            cap_source_excerpt(scrub_public_text(excerpt))
            if excerpt is not None
            else None
        )
        identity_key = canonical_source_key({"id": source_id, "uri": uri})
        collision = await session.scalar(
            select(Source.row_id).where(
                Source.thread_id == thread_id,
                Source.id == source_id,
                Source.identity_key != identity_key,
            )
        )
        resolved_source_id = (
            disambiguated_source_id(source_id, identity_key)
            if collision is not None
            else source_id
        )
        await session.execute(
            pg_insert(Source)
            .values(
                row_id=new_id("source_row"),
                id=resolved_source_id,
                thread_id=thread_id,
                identity_key=identity_key,
                run_id=run_id,
                tool_call_id=tool_call_id,
                title=title,
                source_type=source_type,
                uri=uri,
                excerpt=excerpt,
            )
            .on_conflict_do_nothing(index_elements=["thread_id", "identity_key"])
        )
        source = await session.scalar(
            select(Source)
            .where(
                Source.thread_id == thread_id,
                Source.identity_key == identity_key,
            )
            .with_for_update()
        )
        if source is None:
            raise RuntimeError("Source identity could not be reserved.")
        await session.flush()
        return source

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(
        self,
        *,
        source_id: str,
        thread_id: str,
        run_id: str,
        tool_call_id: str | None,
        title: str,
        source_type: str,
        uri: str | None,
        excerpt: str | None,
    ) -> None:
        async with self._sessions() as session:
            await self._add_in_session(
                session,
                source_id=source_id,
                thread_id=thread_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                title=title,
                source_type=source_type,
                uri=uri,
                excerpt=excerpt,
            )
            await session.commit()

    async def list_for_thread(self, thread_id: str) -> list[Source]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Source)
                .where(Source.thread_id == thread_id)
                .order_by(Source.created_at.asc())
            )
            return list(rows.scalars())


# --- threads ------------------------------------------------------------
class ThreadsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, *, project_id: str, title: str) -> Thread:
        async with self._sessions() as session:
            thread = Thread(id=new_id("thread"), project_id=project_id, title=title)
            session.add(thread)
            await session.commit()
            return thread

    async def list_for_project(self, project_id: str) -> list[Thread]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Thread)
                .where(Thread.project_id == project_id)
                .order_by(Thread.updated_at.desc())
            )
            return list(rows.scalars())

    async def get(self, thread_id: str) -> Thread | None:
        async with self._sessions() as session:
            return await session.get(Thread, thread_id)

    async def rename(self, thread_id: str, *, title: str) -> Thread | None:
        async with self._sessions() as session:
            thread = await session.get(Thread, thread_id)
            if thread is None:
                return None
            thread.title = title
            thread.updated_at = datetime.now(UTC)
            await session.commit()
            return thread

    async def delete(self, thread_id: str) -> bool:
        async with self._sessions() as session:
            result = await session.execute(delete(Thread).where(Thread.id == thread_id))
            await session.commit()
            return bool(getattr(result, "rowcount", 0))

    async def set_active_head(self, thread_id: str, head_id: str | None) -> None:
        async with self._sessions() as session:
            async with session.begin():
                if head_id is not None and head_id.startswith("msg-"):
                    run = await session.get(Run, head_id.removeprefix("msg-"))
                    if run is not None and (
                        run.thread_id != thread_id
                        or run.status != "completed"
                        or run.output_message_id != head_id
                    ):
                        raise ValueError("The run has not been durably saved.")
                if head_id is not None:
                    exists = await session.scalar(
                        select(Message.id).where(
                            Message.thread_id == thread_id,
                            Message.message_id == head_id,
                        )
                    )
                    if exists is None:
                        raise ValueError("Unknown branch head.")
                await session.execute(
                    update(Thread)
                    .where(Thread.id == thread_id)
                    .values(
                        active_head_message_id=head_id,
                        updated_at=datetime.now(UTC),
                    )
                )

    async def get_bootstrap_data(
        self, thread_id: str, *, owner_id: str
    ) -> BootstrapData | None:
        async with self._sessions() as session:
            async with session.begin():
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                )
                thread = await session.get(Thread, thread_id)
                if thread is None:
                    return None
                project = await session.get(Project, thread.project_id)
                if project is None or project.owner_id != owner_id:
                    return None
                messages_result = await session.execute(
                    select(Message)
                    .where(Message.thread_id == thread_id)
                    .order_by(Message.created_at.asc(), Message.id.asc())
                )
                message_rows = list(messages_result.scalars())
                state_row = await RunStatesRepository.nearest_in_session(
                    session,
                    thread_id=thread_id,
                    head_message_id=thread.active_head_message_id,
                )
                candidates = list(
                    (
                        await session.execute(
                            select(Run)
                            .where(Run.thread_id == thread_id)
                            .order_by(Run.reserved_at.desc().nullslast(), Run.id.desc())
                        )
                    ).scalars()
                )
                state_run = next(
                    (
                        candidate
                        for candidate in candidates
                        if state_row is not None and candidate.id == state_row.run_id
                    ),
                    None,
                )
                latest: Run | None
                if thread.active_head_message_id is None:
                    latest = state_run or (candidates[0] if candidates else None)
                else:
                    parents = {
                        row.message_id: row.parent_message_id for row in message_rows
                    }
                    branch_ids: set[str] = set()
                    current_id: str | None = thread.active_head_message_id
                    while current_id is not None and current_id not in branch_ids:
                        branch_ids.add(current_id)
                        current_id = parents.get(current_id)
                    branch_latest = next(
                        (
                            candidate
                            for candidate in candidates
                            if (
                                candidate.output_message_id in branch_ids
                                if candidate.output_message_id is not None
                                else candidate.input_message_id in branch_ids
                            )
                        ),
                        None,
                    )
                    exact_state = state_row is not None and (
                        state_row.head_message_id == thread.active_head_message_id
                        or (
                            state_row.run_id is not None
                            and thread.active_head_message_id
                            == f"msg-tools-{state_row.run_id}"
                        )
                    )
                    branch_latest_is_at_head = branch_latest is not None and (
                        branch_latest.output_message_id == thread.active_head_message_id
                        or (
                            branch_latest.output_message_id is None
                            and branch_latest.input_message_id
                            == thread.active_head_message_id
                        )
                    )
                    if branch_latest_is_at_head or not exact_state:
                        latest = (
                            branch_latest
                            or state_run
                            or (candidates[0] if candidates else None)
                        )
                    else:
                        latest = (
                            state_run
                            or branch_latest
                            or (candidates[0] if candidates else None)
                        )

                completed_states: list[tuple[RunState, Run]] = [
                    (row[0], row[1])
                    for row in (
                        await session.execute(
                            select(RunState, Run)
                            .join(Run, RunState.run_id == Run.id)
                            .where(
                                RunState.thread_id == thread_id,
                                Run.status == "completed",
                            )
                        )
                    ).all()
                ]
                artifacts = list(
                    (
                        await session.scalars(
                            select(Artifact).where(Artifact.thread_id == thread_id)
                        )
                    ).all()
                )
                return BootstrapData(
                    thread=thread,
                    messages=message_rows,
                    state_row=state_row,
                    latest_run=latest,
                    completed_states=completed_states,
                    artifacts=artifacts,
                )
