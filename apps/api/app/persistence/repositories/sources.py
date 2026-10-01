"""Source-record queries with canonical-identity deduplication."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.kernel.identity import canonical_source_key, disambiguated_source_id
from app.persistence.models import Source
from app.persistence.repositories.helpers import new_id

_MAX_SOURCE_EXCERPT_CHARS = 300


def _cap_source_excerpt(excerpt: str | None) -> str | None:
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
