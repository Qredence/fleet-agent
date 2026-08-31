"""Durable, DB-backed approval checkpoints for engine mode.

The in-process registry dies with the server; this implementation stores the
hidden continuation in ``approval_checkpoints`` with a wall-clock TTL so a
paused run stays resumable across restarts. All methods are called from the
DSPy worker thread and bridge onto the application's event loop via
``run_coroutine_threadsafe``; database failures propagate so the coordinator
settles the run as failed instead of pausing it unresumably.

Semantics deliberately mirror ``ApprovalRegistry``: one-time consume before
any model or tool runs, unknown and consumed ids share ``approval_invalid``
(no registry oracle), expired rows yield ``approval_expired``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import dspy
from ag_ui.core import Interrupt, ResumeEntry
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.approval import (
    APPROVAL_TTL_SECONDS,
    CHECKPOINT_SCHEMA_VERSION,
    ApprovalCheckpoint,
    ApprovalDecisionError,
    ResolvedApproval,
    build_approval_interrupt,
    checkpoint_from_json,
    checkpoint_to_json,
    validated_resume_entry,
)
from app.persistence.models import ApprovalCheckpointRow

logger = logging.getLogger(__name__)

_DB_TIMEOUT_S = 10.0
# Retention window for expired/consumed rows before housekeeping deletes them.
_EXPIRY_GRACE = timedelta(minutes=30)


class DurableApprovalRegistry:
    """Approval checkpoint registry backed by ``approval_checkpoints``."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        loop: asyncio.AbstractEventLoop,
        ttl_seconds: int = APPROVAL_TTL_SECONDS,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("approval TTL must be positive")
        self._sessions = sessions
        self._loop = loop
        self._ttl_seconds = ttl_seconds

    def create(
        self,
        *,
        checkpoint: ApprovalCheckpoint,
        thread_id: str,
        run_id: str,
        provider_binding: str,
        action_preview: str,
    ) -> Interrupt:
        """Persist a hidden checkpoint and return its safe public interrupt."""
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
        interrupt_id = f"approval_{uuid.uuid4().hex}"
        record = ApprovalCheckpointRow(
            interrupt_id=interrupt_id,
            thread_id=thread_id,
            run_id=run_id,
            provider_binding=provider_binding,
            profile_name=checkpoint.profile_name,
            tool_name=checkpoint.tool_name,
            tool_call_id=checkpoint.tool_call_id,
            assistant_message_id=checkpoint.assistant_message_id,
            status="pending",
            expires_at=expires_at,
            checkpoint_json=checkpoint_to_json(checkpoint),
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            dspy_version=dspy.__version__,
        )
        self._await(self._acreate(record))
        return build_approval_interrupt(
            checkpoint=checkpoint,
            interrupt_id=interrupt_id,
            expires_at=expires_at.isoformat().replace("+00:00", "Z"),
            action_preview=action_preview,
        )

    def resolve(
        self,
        entries: list[ResumeEntry] | None,
        *,
        thread_id: str,
        provider_binding: str,
    ) -> ResolvedApproval | None:
        """Validate and consume exactly one native AG-UI resume entry."""
        if entries is None:
            return None
        interrupt_id, approved = validated_resume_entry(entries)
        resolved = self._await(
            self._aresolve(
                interrupt_id=interrupt_id,
                thread_id=thread_id,
                provider_binding=provider_binding,
                approved=approved,
            )
        )
        return cast("ResolvedApproval | None", resolved)

    def clear(self) -> None:
        """Delete every checkpoint row; intended for tests and teardown."""
        self._await(self._aclear())

    # -- worker-thread bridge onto the application event loop --------------

    def _await(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run a DB coroutine on the bound loop; call from the DSPy worker.

        The engine executes programs via ``asyncio.to_thread``, so this is
        always called off the loop; calling it ON the loop would need to
        block the only thread that can run the coroutine, so that misuse
        fails fast instead of deadlocking.
        """
        if self._loop.is_closed():
            raise RuntimeError("approval registry event loop is closed")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run_coroutine_threadsafe(coro, self._loop).result(
                timeout=_DB_TIMEOUT_S
            )
        raise RuntimeError(
            "DurableApprovalRegistry must be used from the DSPy worker thread, "
            "not from the event loop thread"
        )

    # -- database operations -------------------------------------------------

    async def _acreate(self, record: ApprovalCheckpointRow) -> None:
        async with self._sessions() as session:
            async with session.begin():
                # One live pause per run: an earlier pending checkpoint from
                # the same run is unreachable once this one replaces it.
                await session.execute(
                    delete(ApprovalCheckpointRow).where(
                        ApprovalCheckpointRow.run_id == record.run_id,
                        ApprovalCheckpointRow.status == "pending",
                        ApprovalCheckpointRow.interrupt_id != record.interrupt_id,
                    )
                )
                session.add(record)

    async def _aresolve(
        self,
        *,
        interrupt_id: str,
        thread_id: str,
        provider_binding: str,
        approved: bool,
    ) -> ResolvedApproval:
        now = datetime.now(UTC)
        outcome = "ok"
        # The payload must be captured inside the transaction: the commit
        # expires the ORM row, and reading it after the session closes would
        # raise DetachedInstanceError on every successful consume.
        payload: dict[str, Any] | None = None
        async with self._sessions() as session:
            async with session.begin():
                row = await session.get(ApprovalCheckpointRow, interrupt_id)
                if row is None or row.status == "consumed":
                    # Unknown and consumed ids intentionally share the same
                    # public code so the registry does not become an oracle.
                    outcome = "invalid"
                elif row.status == "expired" or row.expires_at <= now:
                    outcome = "expired"
                    if row.status != "expired":
                        await session.execute(
                            update(ApprovalCheckpointRow)
                            .where(ApprovalCheckpointRow.interrupt_id == interrupt_id)
                            .values(status="expired", updated_at=now)
                        )
                elif (
                    row.thread_id != thread_id
                    or row.provider_binding != provider_binding
                ):
                    outcome = "invalid"
                else:
                    # Consume before invoking any model or tool. A replay
                    # cannot execute the original call a second time, even if
                    # the continuation later fails for an unrelated reason.
                    consumed = await session.execute(
                        update(ApprovalCheckpointRow)
                        .where(
                            ApprovalCheckpointRow.interrupt_id == interrupt_id,
                            ApprovalCheckpointRow.status == "pending",
                        )
                        .values(status="consumed", updated_at=now)
                    )
                    if getattr(consumed, "rowcount", 0) != 1:
                        outcome = "invalid"
                    else:
                        payload = dict(row.checkpoint_json)

        if outcome == "invalid":
            raise ApprovalDecisionError("approval_invalid")
        if outcome == "expired":
            raise ApprovalDecisionError("approval_expired")
        assert payload is not None  # narrowed by outcome above
        try:
            checkpoint = checkpoint_from_json(payload)
        except Exception:
            logger.error(
                "approval checkpoint failed to deserialize (interrupt %s)",
                interrupt_id,
            )
            raise ApprovalDecisionError("approval_invalid") from None
        return ResolvedApproval(
            checkpoint=checkpoint,
            approved=approved,
            interrupt_id=interrupt_id,
        )

    async def _aclear(self) -> None:
        async with self._sessions() as session:
            async with session.begin():
                await session.execute(delete(ApprovalCheckpointRow))


async def resumable_run_ids(
    sessions: async_sessionmaker[AsyncSession],
) -> set[str]:
    """Runs with a pending, unexpired checkpoint (restart reconciliation)."""
    now = datetime.now(UTC)
    async with sessions() as session:
        rows = await session.execute(
            select(ApprovalCheckpointRow.run_id).where(
                ApprovalCheckpointRow.status == "pending",
                ApprovalCheckpointRow.expires_at > now,
            )
        )
        return {str(run_id) for run_id in rows.scalars()}


async def sweep_expired_checkpoints(
    sessions: async_sessionmaker[AsyncSession],
) -> int:
    """Housekeeping: delete rows whose retention window has passed."""
    cutoff = datetime.now(UTC) - _EXPIRY_GRACE
    async with sessions() as session:
        async with session.begin():
            result = await session.execute(
                delete(ApprovalCheckpointRow).where(
                    ApprovalCheckpointRow.expires_at < cutoff
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)
