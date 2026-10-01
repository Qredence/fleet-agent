"""Thread aggregate queries, including the bootstrap snapshot read."""

from datetime import UTC, datetime

from sqlalchemy import delete, select, text, update
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
from app.persistence.repositories.helpers import new_id
from app.persistence.repositories.states import RunStatesRepository


class ThreadsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, *, project_id: str, title: str) -> Thread:
        async with self._sessions() as session:
            thread = Thread(id=new_id("thread"), project_id=project_id, title=title)
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

    async def delete(self, thread_id: str) -> bool:
        async with self._sessions() as session:
            thread = await session.get(Thread, thread_id)
            if thread is None:
                return False
            for model in (Message, Run, RunState, DspyHistory, Source, Artifact):
                await session.execute(delete(model).where(model.thread_id == thread_id))
            await session.delete(thread)
            await session.commit()
            return True

    async def set_active_head(self, thread_id: str, head_id: str | None) -> None:
        async with self._sessions() as session:
            async with session.begin():
                if head_id is not None:
                    exists = await session.scalar(
                        select(Message.id).where(
                            Message.thread_id == thread_id,
                            Message.message_id == head_id,
                        )
                    )
                    if exists is None:
                        raise ValueError("Unknown branch head.")
                await session.execute(
                    update(Thread)
                    .where(Thread.id == thread_id)
                    .values(
                        active_head_message_id=head_id,
                        updated_at=datetime.now(UTC),
                    )
                )

    async def get_bootstrap_data(
        self, thread_id: str, *, owner_id: str
    ) -> tuple[Thread, list[Message], RunState | None, Run | None] | None:
        async with self._sessions() as session:
            async with session.begin():
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                )
                thread = await session.get(Thread, thread_id)
                if thread is None:
                    return None
                project = await session.get(Project, thread.project_id)
                if project is None or project.owner_id != owner_id:
                    return None
                messages_result = await session.execute(
                    select(Message)
                    .where(Message.thread_id == thread_id)
                    .order_by(Message.created_at.asc(), Message.id.asc())
                )
                message_rows = list(messages_result.scalars())
                state_row = await RunStatesRepository.nearest_in_session(
                    session,
                    thread_id=thread_id,
                    head_message_id=thread.active_head_message_id,
                )
                latest: Run | None = (
                    await session.get(Run, state_row.run_id)
                    if state_row is not None and state_row.run_id is not None
                    else None
                )
                if latest is None:
                    candidates = list(
                        (
                            await session.execute(
                                select(Run)
                                .where(Run.thread_id == thread_id)
                                .order_by(
                                    Run.reserved_at.desc().nullslast(), Run.id.desc()
                                )
                            )
                        ).scalars()
                    )
                    if thread.active_head_message_id is not None:
                        parent_rows = list(
                            (
                                await session.execute(
                                    select(
                                        Message.message_id, Message.parent_message_id
                                    ).where(Message.thread_id == thread_id)
                                )
                            ).all()
                        )
                        parents = {
                            message_id: parent for message_id, parent in parent_rows
                        }
                        branch_ids: set[str] = set()
                        current_id: str | None = thread.active_head_message_id
                        while current_id is not None and current_id not in branch_ids:
                            branch_ids.add(current_id)
                            current_id = parents.get(current_id)
                        latest = next(
                            (
                                candidate
                                for candidate in candidates
                                if candidate.output_message_id in branch_ids
                                or candidate.input_message_id in branch_ids
                            ),
                            None,
                        )
                    latest = latest or (candidates[0] if candidates else None)
                return thread, message_rows, state_row, latest
