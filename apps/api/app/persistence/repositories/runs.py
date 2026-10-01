"""Run lifecycle queries (reserve, settle, orphan sweep)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import Run, RunState


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
            orphaned = list(
                (
                    await session.execute(
                        select(Run).where(
                            Run.status.in_(["running", "queued", "interrupted"]),
                        )
                    )
                ).scalars()
            )
            if not orphaned:
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
