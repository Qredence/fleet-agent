"""Durable approval checkpoints: restart survival, TTL, replay, settlement.

These tests pin the same semantics the in-memory registry already guarantees
(one-time consume before execution, fail-closed validation, no registry
oracle) against the DB-backed implementation, plus the restart
reconciliation paths that keep resumable runs interrupted.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import dspy
from ag_ui.core import Interrupt, ResumeEntry
from sqlalchemy import select, update

from app.agent.engine import AgentRunContext, DspyAgentEngine
from app.agent.program import FleetAgent
from app.agent.provider import ProviderOverride
from app.agent.tool_registry import ToolMetadata
from app.agent.tooling import create_dspy_tool
from app.persistence.models import ApprovalCheckpointRow, Run
from app.persistence.repositories import (
    ApprovalCheckpointsRepository,
    ProjectsRepository,
    RunsRepository,
    ThreadsRepository,
)
from app.services.durable_approvals import (
    DurableApprovalRegistry,
    resumable_run_ids,
    sweep_expired_checkpoints,
)
from tests.conftest import requires_db
from tests.helpers.scripted_lm import ScriptedLM, submit_call

pytestmark = requires_db


def _resume_entry(interrupt: Interrupt, approved: bool) -> ResumeEntry:
    return ResumeEntry.model_validate(
        {
            "interruptId": interrupt.id,
            "status": "resolved",
            "payload": {"approved": approved},
        }
    )


def _write_tool(calls: list[tuple[str, str]]) -> dspy.Tool:
    def write(path: str, content: str) -> str:
        """Write content to a test workspace."""
        calls.append((path, content))
        return "write completed"

    return create_dspy_tool(write, name="write")


_WRITE_POLICY: dict[str, ToolMetadata | bool] = {
    "write": ToolMetadata(
        name="write",
        capability="workspace_write",
        read_only=False,
        idempotent=False,
        parallelizable=False,
        requires_approval=True,
    )
}


def _make_engine(
    steps: list[Any],
    *,
    registry: DurableApprovalRegistry,
    tool: dspy.Tool,
    provider_override: ProviderOverride | None = None,
) -> DspyAgentEngine:
    def program_factory() -> FleetAgent:
        return FleetAgent(
            tools=[tool],
            max_iters=4,
            approval_policy=_WRITE_POLICY,
        )

    return DspyAgentEngine(
        program_factory=program_factory,
        lm=ScriptedLM(steps),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
        approval_registry=registry,
        provider_override=provider_override,
    )


def _context(
    *,
    thread_id: str = "thread-durable",
    run_id: str = "run-durable",
    assistant_message_id: str = "assistant-durable",
) -> AgentRunContext:
    return AgentRunContext(
        thread_id=thread_id,
        run_id=run_id,
        assistant_message_id=assistant_message_id,
    )


async def _seed_thread(db_sessions) -> str:
    project = await ProjectsRepository(db_sessions).create(name="Durable approvals")
    thread = await ThreadsRepository(db_sessions).create(
        project_id=project.id, title="Approval checkpoints"
    )
    return thread.id


async def _insert_run(db_sessions, *, run_id: str, thread_id: str, status: str) -> Run:
    async with db_sessions() as session:
        run = Run(
            id=run_id,
            thread_id=thread_id,
            status=status,
            reserved_at=datetime.now(UTC),
        )
        session.add(run)
        await session.commit()
        return run


def _durable_registry(
    db_sessions, ttl_seconds: int | None = None
) -> DurableApprovalRegistry:
    kwargs: dict[str, Any] = {}
    if ttl_seconds is not None:
        kwargs["ttl_seconds"] = ttl_seconds
    return DurableApprovalRegistry(
        sessions=db_sessions, loop=asyncio.get_running_loop(), **kwargs
    )


async def _row(db_sessions, interrupt_id: str) -> ApprovalCheckpointRow | None:
    async with db_sessions() as session:
        return await session.get(ApprovalCheckpointRow, interrupt_id)


async def test_pause_survives_restart_and_resumes_exactly_once(db_sessions) -> None:
    """A checkpoint parked by one process resolves in a fresh one."""
    thread_id = await _seed_thread(db_sessions)
    run_id = "run-durable-pause"
    await _insert_run(db_sessions, run_id=run_id, thread_id=thread_id, status="running")
    calls: list[tuple[str, str]] = []
    provider = ProviderOverride(api_key="sk-or-durable", model="vendor/model")

    first_registry = _durable_registry(db_sessions)
    first_engine = _make_engine(
        [[{"name": "write", "args": {"path": "notes.txt", "content": "secret"}}]],
        registry=first_registry,
        tool=_write_tool(calls),
        provider_override=provider,
    )
    paused = await first_engine.run(
        user_request="save this",
        history=None,
        context=_context(run_id=run_id, thread_id=thread_id),
    )
    assert paused.status == "interrupted"
    assert paused.termination_reason == "approval_required"
    assert calls == []
    interrupt = paused.interrupts[0]
    assert await _row(db_sessions, interrupt.id) is not None

    # Simulated restart: a brand-new process object with no shared memory.
    second_registry = _durable_registry(db_sessions)
    second_engine = _make_engine(
        [[submit_call(answer="saved")]],
        registry=second_registry,
        tool=_write_tool(calls),
        provider_override=provider,
    )
    resumed = await second_engine.run(
        user_request="save this",
        history=None,
        context=_context(run_id=run_id, thread_id=thread_id),
        resume=[_resume_entry(interrupt, True)],
    )
    assert resumed.status == "completed"
    assert resumed.answer == "saved"
    assert calls == [("notes.txt", "secret")]

    row = await _row(db_sessions, interrupt.id)
    assert row is not None and row.status == "consumed"

    # Replaying the same decision can never execute the tool a second time.
    third_registry = _durable_registry(db_sessions)
    third_engine = _make_engine(
        [[submit_call(answer="never")]],
        registry=third_registry,
        tool=_write_tool(calls),
        provider_override=provider,
    )
    replay = await third_engine.run(
        user_request="save this",
        history=None,
        context=_context(run_id="run-durable-replay", thread_id=thread_id),
        resume=[_resume_entry(interrupt, True)],
    )
    assert replay.status == "failed"
    assert replay.error_code == "approval_invalid"
    assert calls == [("notes.txt", "secret")]


async def test_wrong_thread_and_provider_fail_closed_without_consuming(
    db_sessions,
) -> None:
    """Invalid resumes must not burn the checkpoint they target."""
    thread_id = await _seed_thread(db_sessions)
    run_id = "run-durable-bindings"
    await _insert_run(db_sessions, run_id=run_id, thread_id=thread_id, status="running")
    provider = ProviderOverride(api_key="sk-or-binding", model="vendor/model")
    calls: list[tuple[str, str]] = []

    registry = _durable_registry(db_sessions)
    engine = _make_engine(
        [[{"name": "write", "args": {"path": "a.txt", "content": "x"}}]],
        registry=registry,
        tool=_write_tool(calls),
        provider_override=provider,
    )
    paused = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id=run_id, thread_id=thread_id),
    )
    interrupt = paused.interrupts[0]
    entry = _resume_entry(interrupt, True)

    wrong_thread = await engine.run(
        user_request="save",
        history=None,
        context=_context(thread_id="other-thread", run_id="run-wrong-thread"),
        resume=[entry],
    )
    assert wrong_thread.error_code == "approval_invalid"

    wrong_provider_engine = _make_engine(
        [[submit_call()]],
        registry=registry,
        tool=_write_tool(calls),
        provider_override=ProviderOverride(api_key="sk-or-other", model="vendor/other"),
    )
    wrong_provider = await wrong_provider_engine.run(
        user_request="save",
        history=None,
        context=_context(run_id="run-wrong-provider", thread_id=thread_id),
        resume=[entry],
    )
    assert wrong_provider.error_code == "approval_invalid"
    assert calls == []

    # The checkpoint was never consumed by the failed attempts, so the
    # correctly bound resume still completes.
    valid_engine = _make_engine(
        [[submit_call(answer="approved")]],
        registry=registry,
        tool=_write_tool(calls),
        provider_override=provider,
    )
    valid = await valid_engine.run(
        user_request="save",
        history=None,
        context=_context(run_id=run_id, thread_id=thread_id),
        resume=[entry],
    )
    assert valid.status == "completed"
    assert calls == [("a.txt", "x")]


async def test_expired_checkpoint_fails_closed_and_is_swept(db_sessions) -> None:
    thread_id = await _seed_thread(db_sessions)
    run_id = "run-durable-expiry"
    await _insert_run(db_sessions, run_id=run_id, thread_id=thread_id, status="running")
    calls: list[tuple[str, str]] = []
    provider = ProviderOverride(api_key="sk-or-expiry", model="vendor/model")

    registry = _durable_registry(db_sessions)
    engine = _make_engine(
        [[{"name": "write", "args": {"path": "b.txt", "content": "y"}}]],
        registry=registry,
        tool=_write_tool(calls),
        provider_override=provider,
    )
    paused = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id=run_id, thread_id=thread_id),
    )
    interrupt = paused.interrupts[0]

    # Age the row past its wall-clock TTL without waiting in real time.
    async with db_sessions() as session:
        await session.execute(
            update(ApprovalCheckpointRow)
            .where(ApprovalCheckpointRow.interrupt_id == interrupt.id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()

    expired = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id=run_id, thread_id=thread_id),
        resume=[_resume_entry(interrupt, True)],
    )
    assert expired.status == "failed"
    assert expired.error_code == "approval_expired"
    assert calls == []

    row = await _row(db_sessions, interrupt.id)
    assert row is not None and row.status == "expired"
    # Expired rows are not resumable after the restart reconciliation pass.
    assert run_id not in await resumable_run_ids(db_sessions)

    # Housekeeping reaps rows once the retention window has passed.
    async with db_sessions() as session:
        await session.execute(
            update(ApprovalCheckpointRow)
            .where(ApprovalCheckpointRow.interrupt_id == interrupt.id)
            .values(expires_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await session.commit()
    swept = await sweep_expired_checkpoints(db_sessions)
    assert swept >= 1
    assert await _row(db_sessions, interrupt.id) is None


async def test_second_pause_for_same_run_replaces_first_checkpoint(db_sessions) -> None:
    """One live pause per run: the newer interrupt wins, the older is dead."""
    thread_id = await _seed_thread(db_sessions)
    run_id = "run-durable-evict"
    await _insert_run(db_sessions, run_id=run_id, thread_id=thread_id, status="running")
    calls: list[tuple[str, str]] = []
    provider = ProviderOverride(api_key="sk-or-evict", model="vendor/model")

    registry = _durable_registry(db_sessions)
    engine = _make_engine(
        [
            [{"name": "write", "args": {"path": "one.txt", "content": "1"}}],
            [{"name": "write", "args": {"path": "two.txt", "content": "2"}}],
            [submit_call(answer="done")],
        ],
        registry=registry,
        tool=_write_tool(calls),
        provider_override=provider,
    )
    first = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id=run_id, thread_id=thread_id),
    )
    # Resume with a denial: the batch is skipped and the loop continues to a
    # second gated call, parking a newer checkpoint for the same run.
    second = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id=run_id, thread_id=thread_id),
        resume=[_resume_entry(first.interrupts[0], False)],
    )
    assert second.status == "interrupted"
    assert calls == []

    async with db_sessions() as session:
        rows = list(
            (
                await session.execute(
                    select(ApprovalCheckpointRow).where(
                        ApprovalCheckpointRow.run_id == run_id
                    )
                )
            ).scalars()
        )
    # The denied resume consumed the first checkpoint; exactly one live pause
    # remains for the run, and it is the newest interrupt.
    pending = [row for row in rows if row.status == "pending"]
    assert sorted(row.status for row in rows) == ["consumed", "pending"]
    assert len(pending) == 1
    assert pending[0].interrupt_id == second.interrupts[0].id

    # The evicted checkpoint is gone; only the newest pause can resume.
    stale = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id="run-durable-stale", thread_id=thread_id),
        resume=[_resume_entry(first.interrupts[0], True)],
    )
    assert stale.error_code == "approval_invalid"
    assert calls == []


async def test_terminal_settlement_and_orphan_reconciliation(db_sessions) -> None:
    """Settled runs lose their continuation; paused runs survive a restart."""
    thread_id = await _seed_thread(db_sessions)
    paused_run = "run-durable-keep"
    lost_run = "run-durable-lose"
    await _insert_run(
        db_sessions, run_id=paused_run, thread_id=thread_id, status="interrupted"
    )
    await _insert_run(
        db_sessions, run_id=lost_run, thread_id=thread_id, status="interrupted"
    )
    calls: list[tuple[str, str]] = []
    provider = ProviderOverride(api_key="sk-or-orphan", model="vendor/model")

    registry = _durable_registry(db_sessions)
    engine = _make_engine(
        [[{"name": "write", "args": {"path": "c.txt", "content": "z"}}]],
        registry=registry,
        tool=_write_tool(calls),
        provider_override=provider,
    )
    paused = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id=paused_run, thread_id=thread_id),
    )
    assert paused.status == "interrupted"

    # Restart reconciliation keeps only runs with a live durable checkpoint.
    keep = await resumable_run_ids(db_sessions)
    assert keep == {paused_run}
    orphaned = await RunsRepository(db_sessions).mark_orphaned_interrupted(
        keep_run_ids=keep
    )
    assert orphaned == 1
    async with db_sessions() as session:
        statuses = {
            run.id: run.status
            for run in (
                await session.execute(
                    select(Run).where(Run.id.in_([paused_run, lost_run]))
                )
            ).scalars()
        }
    assert statuses == {paused_run: "interrupted", lost_run: "failed"}

    # Terminal settlement of the paused run deletes its dead continuation.
    await ApprovalCheckpointsRepository.delete_pending_for_run(
        db_sessions, run_id=paused_run
    )
    assert await resumable_run_ids(db_sessions) == set()
    replay = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id=paused_run, thread_id=thread_id),
        resume=[_resume_entry(paused.interrupts[0], True)],
    )
    assert replay.error_code == "approval_invalid"
    assert calls == []
