"""Typed queries only — no route logic, no run orchestration."""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import (
    Artifact,
    DspyHistory,
    Message,
    Project,
    Run,
    RunState,
    Source,
    SourceOccurrence,
    Thread,
)
from app.services.history_safety import sanitize_message_content
from app.services.source_identity import (
    canonical_source_key,
    disambiguated_source_id,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_MAX_SOURCE_EXCERPT_CHARS = 300


def _cap_source_excerpt(excerpt: str | None) -> str | None:
    if excerpt is None:
        return None
    excerpt = excerpt.strip()
    if len(excerpt) <= _MAX_SOURCE_EXCERPT_CHARS:
        return excerpt
    return excerpt[: _MAX_SOURCE_EXCERPT_CHARS - 1] + "…"


_NO_EXPECTED_HEAD = object()


class RunAlreadyExistsError(RuntimeError):
    """Typed duplicate-run conflict for reservation callers."""


class ProjectsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, *, name: str, owner_id: str = "local") -> Project:
        async with self._sessions() as session:
            project = Project(id=_new_id("project"), owner_id=owner_id, name=name)
            session.add(project)
            await session.commit()
            return project

    async def list(self, *, owner_id: str = "local") -> list[Project]:
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
            project = await session.get(Project, project_id)
            if project is None:
                return False
            threads = list(
                (
                    await session.execute(
                        select(Thread).where(Thread.project_id == project_id)
                    )
                ).scalars()
            )
            thread_ids = [thread.id for thread in threads]
            await session.execute(
                delete(SourceOccurrence).where(
                    SourceOccurrence.source_row_id.in_(
                        select(Source.row_id).where(Source.thread_id.in_(thread_ids))
                    )
                )
            )
            for model in (Message, Run, RunState, DspyHistory, Source, Artifact):
                await session.execute(
                    delete(model).where(model.thread_id.in_(thread_ids))
                )
            await session.execute(delete(Thread).where(Thread.project_id == project_id))
            await session.delete(project)
            await session.commit()
            return True


class ThreadsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, *, project_id: str, title: str) -> Thread:
        async with self._sessions() as session:
            thread = Thread(id=_new_id("thread"), project_id=project_id, title=title)
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

    async def touch_last_run(self, thread_id: str, run_id: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(Thread)
                .where(Thread.id == thread_id)
                .values(last_run_id=run_id, updated_at=datetime.now(UTC))
            )
            await session.commit()

    async def set_active_head(
        self,
        thread_id: str,
        head_message_id: str | None,
        *,
        expected_head_message_id: str | None | object = _NO_EXPECTED_HEAD,
    ) -> bool:
        async with self._sessions() as session:
            updated = await self.set_active_head_in_session(
                session,
                thread_id,
                head_message_id,
                expected_head_message_id=expected_head_message_id,
            )
            await session.commit()
            return updated

    @staticmethod
    async def set_active_head_in_session(
        session: AsyncSession,
        thread_id: str,
        head_message_id: str | None,
        *,
        expected_head_message_id: str | None | object = _NO_EXPECTED_HEAD,
    ) -> bool:
        query = update(Thread).where(Thread.id == thread_id)
        if expected_head_message_id is not _NO_EXPECTED_HEAD:
            query = query.where(
                Thread.active_head_message_id == expected_head_message_id
            )
        result = await session.execute(
            query.values(
                active_head_message_id=head_message_id,
                updated_at=datetime.now(UTC),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def delete(self, thread_id: str) -> bool:
        async with self._sessions() as session:
            thread = await session.get(Thread, thread_id)
            if thread is None:
                return False
            await session.execute(
                delete(SourceOccurrence).where(
                    SourceOccurrence.source_row_id.in_(
                        select(Source.row_id).where(Source.thread_id == thread_id)
                    )
                )
            )
            for model in (Message, Run, RunState, DspyHistory, Source, Artifact):
                await session.execute(delete(model).where(model.thread_id == thread_id))
            await session.delete(thread)
            await session.commit()
            return True


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
        resolved_id = message_id or str(message_json.get("id") or _new_id("message"))
        if parent_message_id == resolved_id:
            raise ValueError("A message cannot parent itself.")
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
                id=_new_id("message_row"),
                thread_id=thread_id,
                message_id=resolved_id,
                parent_message_id=parent_message_id,
                role=role,
                format=format,
                message_json=message_json,
                run_config_json=run_config_json,
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
            row.message_json = message_json
            if run_config_json is not None or format != "aui/v0":
                row.run_config_json = run_config_json
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

    async def list_storage(self, thread_id: str) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Message)
                .where(Message.thread_id == thread_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
            return [self.storage_dict(row) for row in rows.scalars()]

    async def get_by_message_id(
        self, thread_id: str, message_id: str
    ) -> Message | None:
        async with self._sessions() as session:
            return cast(
                Message | None,
                await session.scalar(
                    select(Message).where(
                        Message.thread_id == thread_id,
                        Message.message_id == message_id,
                    )
                ),
            )

    async def list_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Message.message_json)
                .where(Message.thread_id == thread_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
            return list(rows.scalars())


class RunsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def started(self, *, run_id: str, thread_id: str) -> None:
        async with self._sessions() as session:
            existing = await session.get(Run, run_id, with_for_update=True)
            if existing is None:
                await self.reserve_in_session(
                    session,
                    run_id=run_id,
                    thread_id=thread_id,
                    input_message_id=None,
                    continuation_message_id=None,
                )
            await self.mark_running_in_session(session, run_id=run_id)
            await session.commit()

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

    async def finished(
        self,
        *,
        run_id: str,
        status: str,
        termination_reason: str | None,
        token_usage: dict[str, Any] | None,
        error_code: str | None,
    ) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_id, Run.status.in_(["queued", "running"]))
                .values(
                    status=status,
                    termination_reason=termination_reason,
                    finished_at=datetime.now(UTC),
                    token_usage=token_usage,
                    error_code=error_code,
                )
            )
            await session.commit()

    async def get(self, run_id: str) -> Run | None:
        async with self._sessions() as session:
            return await session.get(Run, run_id)

    async def latest_for_thread(self, thread_id: str) -> Run | None:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Run)
                .where(Run.thread_id == thread_id)
                .order_by(Run.reserved_at.desc().nullslast(), Run.id.desc())
                .limit(1)
            )
            return rows.scalars().first()

    async def mark_orphaned_interrupted(self) -> int:
        """Fail live and paused runs whose in-memory state was lost."""
        async with self._sessions() as session:
            orphaned = list(
                (
                    await session.execute(
                        select(Run).where(
                            Run.status.in_(["running", "queued", "interrupted"])
                        )
                    )
                ).scalars()
            )
            if not orphaned:
                return 0
            result = await session.execute(
                update(Run)
                .where(Run.status.in_(["running", "queued", "interrupted"]))
                .values(
                    status="failed",
                    termination_reason="server_restart",
                    finished_at=datetime.now(UTC),
                    error_code="internal_error",
                )
            )
            orphaned_ids = [run.id for run in orphaned]
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
                        "errorCode": "internal_error",
                    }
                )
                snapshot["run"] = run_state
                state.state_json = snapshot
                state.updated_at = datetime.now(UTC)
            await session.commit()
            rowcount: int = getattr(result, "rowcount", 0) or 0
            return rowcount


class RunStatesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def upsert(
        self,
        *,
        thread_id: str,
        state_json: dict[str, Any],
        run_id: str | None = None,
        head_message_id: str | None = None,
    ) -> None:
        async with self._sessions() as session:
            await self.upsert_in_session(
                session,
                thread_id=thread_id,
                state_json=state_json,
                run_id=run_id,
                head_message_id=head_message_id,
            )
            await session.commit()

    @staticmethod
    async def upsert_in_session(
        session: AsyncSession,
        *,
        thread_id: str,
        state_json: dict[str, Any],
        run_id: str | None = None,
        head_message_id: str | None = None,
    ) -> RunState:
        query = select(RunState).where(RunState.thread_id == thread_id)
        if head_message_id is None:
            query = query.where(RunState.head_message_id.is_(None))
        else:
            query = query.where(RunState.head_message_id == head_message_id)
        existing = await session.scalar(query.with_for_update())
        if existing is None:
            existing = RunState(
                id=_new_id("state"),
                thread_id=thread_id,
                run_id=run_id,
                head_message_id=head_message_id,
                state_json=state_json,
            )
            session.add(existing)
        else:
            existing.run_id = run_id or existing.run_id
            existing.state_json = state_json
            existing.updated_at = datetime.now(UTC)
        await session.flush()
        return existing

    @staticmethod
    async def nearest_in_session(
        session: AsyncSession, *, thread_id: str, head_message_id: str | None
    ) -> RunState | None:
        rows = await session.execute(
            select(RunState).where(RunState.thread_id == thread_id)
        )
        states = {row.head_message_id: row for row in rows.scalars()}
        message_rows = await session.execute(
            select(Message.message_id, Message.parent_message_id).where(
                Message.thread_id == thread_id
            )
        )
        parents = {message_id: parent for message_id, parent in message_rows}
        run_rows = await session.execute(
            select(Run.id, Run.input_message_id, Run.output_message_id).where(
                Run.thread_id == thread_id
            )
        )
        for r_id, r_in, r_out in run_rows.all():
            st = states.get(r_out) or states.get(f"msg-{r_id}")
            if st is not None:
                states[f"msg-tools-{r_id}"] = st
                if r_in and r_in not in states:
                    states[r_in] = st

        current = head_message_id
        seen: set[str] = set()
        while current is not None and current not in seen:
            if current in states:
                return states[current]
            if current.startswith("msg-tools-"):
                alt = current.replace("msg-tools-", "msg-", 1)
                if alt in states:
                    return states[alt]
            seen.add(current)
            current = parents.get(current)
        return states.get(None)

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

    async def get_record(
        self, thread_id: str, head_message_id: str | None = None
    ) -> RunState | None:
        async with self._sessions() as session:
            query = select(RunState).where(RunState.thread_id == thread_id)
            if head_message_id is not None:
                query = query.where(RunState.head_message_id == head_message_id)
            query = query.order_by(RunState.updated_at.desc()).limit(1)
            return cast(RunState | None, await session.scalar(query))


class DspyHistoriesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def upsert(
        self,
        *,
        thread_id: str,
        schema_version: int,
        dspy_version: str,
        history_json: dict[str, Any],
        head_message_id: str | None = None,
    ) -> None:
        async with self._sessions() as session:
            await self.upsert_in_session(
                session,
                thread_id=thread_id,
                schema_version=schema_version,
                dspy_version=dspy_version,
                history_json=history_json,
                head_message_id=head_message_id,
            )
            await session.commit()

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
        query = select(DspyHistory).where(DspyHistory.thread_id == thread_id)
        if head_message_id is None:
            query = query.where(DspyHistory.head_message_id.is_(None))
        else:
            query = query.where(DspyHistory.head_message_id == head_message_id)
        existing = await session.scalar(query.with_for_update())
        if existing is None:
            existing = DspyHistory(
                id=_new_id("history"),
                thread_id=thread_id,
                head_message_id=head_message_id,
                schema_version=schema_version,
                dspy_version=dspy_version,
                history_json=history_json,
            )
            session.add(existing)
        else:
            existing.schema_version = schema_version
            existing.dspy_version = dspy_version
            existing.history_json = history_json
            existing.updated_at = datetime.now(UTC)
        await session.flush()
        return existing

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


class SourcesRepository:
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
            await self.add_in_session(
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

    @staticmethod
    async def add_in_session(
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
        # Sources are persisted and later served by several endpoints, so cap
        # excerpts here rather than relying only on the live reducer preview.
        excerpt = _cap_source_excerpt(excerpt)
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
                row_id=_new_id("source_row"),
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
        session.add(
            SourceOccurrence(
                id=_new_id("source_occurrence"),
                source_row_id=source.row_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                title=title,
                source_type=source_type,
                uri=uri,
                excerpt=excerpt,
            )
        )
        await session.flush()
        return source

    async def list_for_thread(self, thread_id: str) -> list[Source]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Source)
                .where(Source.thread_id == thread_id)
                .order_by(Source.created_at.asc())
            )
            return list(rows.scalars())


class ArtifactsRepository:
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
            await self.add_in_session(
                session,
                artifact_id=artifact_id,
                thread_id=thread_id,
                run_id=run_id,
                name=name,
                media_type=media_type,
                storage_key=storage_key,
            )
            await session.commit()

    @staticmethod
    async def add_in_session(
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

    async def delete_for_thread(self, thread_id: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                delete(Artifact).where(Artifact.thread_id == thread_id)
            )
            await session.commit()
