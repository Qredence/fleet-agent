"""RunPersistence — the write path for live runs (plan.md Phase 9).

Called only from the LiveDSPyCoordinator (engine mode): at run start, at
completion, and at failure. Contract rules that matter here:

- `dspy.History` is stored server-side ONLY, serialized with model_dump and
  pinned to the application serialization version + dspy package version.
- The latest AgentWorkspaceState snapshot per thread enables panel restore.
- Failed runs keep the user message but produce no assistant message.
"""

from typing import Any

import dspy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.engine import AgentRunResult
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactStarted,
    SourceDiscovered,
)
from app.persistence.repositories import (
    ArtifactsRepository,
    DspyHistoriesRepository,
    MessagesRepository,
    RunsRepository,
    RunStatesRepository,
    SourcesRepository,
    ThreadsRepository,
)

AnyDomainEvent = ArtifactStarted | ArtifactReady | ArtifactFailed | SourceDiscovered

HISTORY_SCHEMA_VERSION = 1


class RunPersistence:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def run_started(
        self, *, thread_id: str, run_id: str, user_message: dict[str, Any]
    ) -> None:
        await ThreadsRepository(self._sessions).touch_last_run(thread_id, run_id)
        await RunsRepository(self._sessions).started(run_id=run_id, thread_id=thread_id)
        await MessagesRepository(self._sessions).append(
            thread_id=thread_id, role="user", message_json=user_message
        )

    async def get_latest_state(self, thread_id: str) -> dict[str, Any] | None:
        return await RunStatesRepository(self._sessions).get(thread_id)

    async def get_continuation_history(self, thread_id: str) -> dspy.History | None:
        record = await DspyHistoriesRepository(self._sessions).get(thread_id)
        if record is None or record.schema_version != HISTORY_SCHEMA_VERSION:
            return None
        return dspy.History.model_validate(record.history_json)

    async def run_completed(
        self,
        *,
        thread_id: str,
        run_id: str,
        result: AgentRunResult,
        state_json: dict[str, Any],
        assistant_message_id: str,
    ) -> None:
        await RunsRepository(self._sessions).finished(
            run_id=run_id,
            status="completed",
            termination_reason=result.termination_reason,
            token_usage=result.usage or None,
            error_code=None,
        )
        if result.answer is not None:
            await MessagesRepository(self._sessions).append(
                thread_id=thread_id,
                role="assistant",
                message_json={
                    "id": assistant_message_id,
                    "role": "assistant",
                    "content": result.answer,
                },
            )
        await RunStatesRepository(self._sessions).upsert(
            thread_id=thread_id, state_json=state_json
        )
        await self._persist_history(thread_id, result)

    async def run_failed(
        self,
        *,
        thread_id: str,
        run_id: str,
        result: AgentRunResult,
        state_json: dict[str, Any],
    ) -> None:
        await RunsRepository(self._sessions).finished(
            run_id=run_id,
            status="failed",
            termination_reason=result.termination_reason,
            token_usage=result.usage or None,
            error_code=result.error_code,
        )
        await RunStatesRepository(self._sessions).upsert(
            thread_id=thread_id, state_json=state_json
        )
        # Continuation history is persisted on failures too when present —
        # the next turn resumes from the safest known base.
        await self._persist_history(thread_id, result)

    async def run_cancelled(
        self, *, thread_id: str, run_id: str, state_json: dict[str, Any]
    ) -> None:
        await RunsRepository(self._sessions).finished(
            run_id=run_id,
            status="cancelled",
            termination_reason="cancelled",
            token_usage=None,
            error_code="run_cancelled",
        )
        await RunStatesRepository(self._sessions).upsert(
            thread_id=thread_id, state_json=state_json
        )

    async def _persist_history(self, thread_id: str, result: AgentRunResult) -> None:
        if result.history is None:
            return
        await DspyHistoriesRepository(self._sessions).upsert(
            thread_id=thread_id,
            schema_version=HISTORY_SCHEMA_VERSION,
            dspy_version=dspy.__version__,
            history_json=result.history.model_dump(mode="json"),
        )

    async def record_domain_event(
        self, event: AnyDomainEvent, *, thread_id: str, run_id: str
    ) -> None:
        """Persist sources/artifacts as they are discovered mid-run, so REST
        listing works even before the run completes."""
        if isinstance(event, SourceDiscovered):
            await SourcesRepository(self._sessions).add(
                source_id=event.source.id,
                thread_id=thread_id,
                run_id=run_id,
                tool_call_id=event.tool_call_id,
                title=event.source.title,
                source_type=event.source.source_type,
                uri=event.source.uri,
                excerpt=event.source.excerpt,
            )
        elif isinstance(event, ArtifactStarted):
            await ArtifactsRepository(self._sessions).add(
                artifact_id=event.artifact.id,
                thread_id=thread_id,
                run_id=run_id,
                name=event.artifact.name,
                media_type=event.artifact.media_type,
                storage_key=event.artifact.storage_key,
            )
        elif isinstance(event, ArtifactReady):
            await ArtifactsRepository(self._sessions).mark_ready(
                event.artifact.id, size_bytes=event.artifact.size_bytes or 0
            )
        elif isinstance(event, ArtifactFailed):
            await ArtifactsRepository(self._sessions).mark_failed(event.artifact_id)
