"""Persisted public-state snapshot queries."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.branch import nearest_anchor
from app.persistence.models import RunState
from app.persistence.repositories.helpers import new_id


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
        query = select(RunState).where(RunState.thread_id == thread_id)
        if head_message_id is None:
            query = query.where(RunState.head_message_id.is_(None))
        else:
            query = query.where(RunState.head_message_id == head_message_id)
        existing = await session.scalar(query.with_for_update())
        if existing is None:
            existing = RunState(
                id=new_id("state"),
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
