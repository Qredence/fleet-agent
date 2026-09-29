"""Project aggregate queries."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
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


class ProjectsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, *, name: str, owner_id: str = "local") -> Project:
        async with self._sessions() as session:
            project = Project(id=new_id("project"), owner_id=owner_id, name=name)
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
