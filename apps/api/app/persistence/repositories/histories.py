"""DSPy conversation-history queries."""

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import DspyHistory
from app.persistence.repositories.helpers import new_id


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
        query = select(DspyHistory).where(DspyHistory.thread_id == thread_id)
        if head_message_id is None:
            query = query.where(DspyHistory.head_message_id.is_(None))
        else:
            query = query.where(DspyHistory.head_message_id == head_message_id)
        existing = await session.scalar(query.with_for_update())
        if existing is None:
            existing = DspyHistory(
                id=new_id("history"),
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
