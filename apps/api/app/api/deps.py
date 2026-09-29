"""Shared FastAPI dependencies for route modules."""

from typing import cast

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import Project, Thread
from app.persistence.repositories import ProjectsRepository, ThreadsRepository

# Single-user until auth lands: all requests act as the local owner.
LOCAL_OWNER = "local"


def get_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.db_sessions)


async def require_project(
    project_id: str, sessions: async_sessionmaker[AsyncSession]
) -> Project:
    project = await ProjectsRepository(sessions).get(project_id)
    if project is None or project.owner_id != LOCAL_OWNER:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


async def require_thread(
    thread_id: str, sessions: async_sessionmaker[AsyncSession]
) -> Thread:
    thread = await ThreadsRepository(sessions).get(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")
    project = await ProjectsRepository(sessions).get(thread.project_id)
    if project is None or project.owner_id != LOCAL_OWNER:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return thread
