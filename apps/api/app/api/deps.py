"""Shared FastAPI dependencies for route modules."""

from typing import cast

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import Project
from app.persistence.repositories import ProjectsRepository

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
