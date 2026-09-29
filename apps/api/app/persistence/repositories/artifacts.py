"""Artifact-record queries (status lifecycle)."""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import Artifact


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
