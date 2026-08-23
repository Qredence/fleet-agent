"""Typed queries only — no route logic, no run orchestration."""

import uuid
from datetime import UTC, datetime
from typing import Any

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
    Thread,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


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

    async def delete(self, thread_id: str) -> bool:
        async with self._sessions() as session:
            thread = await session.get(Thread, thread_id)
            if thread is None:
                return False
            for model in (Message, Run, RunState, DspyHistory):
                await session.execute(delete(model).where(model.thread_id == thread_id))
            await session.delete(thread)
            await session.commit()
            return True


class MessagesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(
        self, *, thread_id: str, role: str, message_json: dict[str, Any]
    ) -> None:
        async with self._sessions() as session:
            # Row id is server-generated: client message ids (in message_json)
            # are only unique within a conversation, not globally.
            session.add(
                Message(
                    id=_new_id("message_row"),
                    thread_id=thread_id,
                    role=role,
                    message_json=message_json,
                )
            )
            await session.commit()

    async def list_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Message.message_json)
                .where(Message.thread_id == thread_id)
                .order_by(Message.created_at.asc())
            )
            return list(rows.scalars())


class RunsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def started(self, *, run_id: str, thread_id: str) -> None:
        async with self._sessions() as session:
            session.add(
                Run(
                    id=run_id,
                    thread_id=thread_id,
                    status="running",
                    started_at=datetime.now(UTC),
                )
            )
            await session.commit()

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
                .where(Run.id == run_id)
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
                .order_by(Run.started_at.desc())
                .limit(1)
            )
            return rows.scalars().first()

    async def mark_orphaned_interrupted(self) -> int:
        """Server-restart reconciliation: runs still marked running/queued are
        interrupted. Returns how many were marked."""
        async with self._sessions() as session:
            result = await session.execute(
                update(Run)
                .where(Run.status.in_(["running", "queued"]))
                .values(
                    status="failed",
                    termination_reason="server_restart",
                    finished_at=datetime.now(UTC),
                    error_code="internal_error",
                )
            )
            await session.commit()
            rowcount: int = getattr(result, "rowcount", 0) or 0
            return rowcount


class RunStatesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def upsert(self, *, thread_id: str, state_json: dict[str, Any]) -> None:
        async with self._sessions() as session:
            existing = await session.get(RunState, thread_id)
            if existing is None:
                session.add(RunState(thread_id=thread_id, state_json=state_json))
            else:
                existing.state_json = state_json
                existing.updated_at = datetime.now(UTC)
            await session.commit()

    async def get(self, thread_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            row = await session.get(RunState, thread_id)
            return row.state_json if row else None


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
    ) -> None:
        async with self._sessions() as session:
            existing = await session.get(DspyHistory, thread_id)
            if existing is None:
                session.add(
                    DspyHistory(
                        thread_id=thread_id,
                        schema_version=schema_version,
                        dspy_version=dspy_version,
                        history_json=history_json,
                    )
                )
            else:
                existing.schema_version = schema_version
                existing.dspy_version = dspy_version
                existing.history_json = history_json
                existing.updated_at = datetime.now(UTC)
            await session.commit()

    async def get(self, thread_id: str) -> DspyHistory | None:
        async with self._sessions() as session:
            return await session.get(DspyHistory, thread_id)


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
            # Idempotent: the same source discovered across runs lands once.
            await session.execute(
                pg_insert(Source)
                .values(
                    id=source_id,
                    thread_id=thread_id,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    title=title,
                    source_type=source_type,
                    uri=uri,
                    excerpt=excerpt,
                )
                .on_conflict_do_nothing(index_elements=["id"])
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
            session.add(
                Artifact(
                    id=artifact_id,
                    thread_id=thread_id,
                    run_id=run_id,
                    name=name,
                    media_type=media_type,
                    storage_key=storage_key,
                    status="generating",
                )
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

    async def delete_for_thread(self, thread_id: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                delete(Artifact).where(Artifact.thread_id == thread_id)
            )
            await session.commit()
