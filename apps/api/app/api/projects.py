"""Projects REST resources."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import Project
from app.persistence.repositories import ProjectsRepository

router = APIRouter(prefix="/api", tags=["projects"])

# Single-user until auth lands (PR 9): all requests act as the local owner.
LOCAL_OWNER = "local"


def get_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.db_sessions)


class ProjectOut(BaseModel):
    id: str
    name: str
    createdAt: str
    updatedAt: str


class ProjectCreate(BaseModel):
    name: str


def to_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        createdAt=project.created_at.isoformat(),
        updatedAt=project.updated_at.isoformat(),
    )


@router.get("/projects")
async def list_projects(
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> list[ProjectOut]:
    repo = ProjectsRepository(sessions)
    return [to_out(project) for project in await repo.list(owner_id=LOCAL_OWNER)]


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreate,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> ProjectOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name must not be empty.")
    repo = ProjectsRepository(sessions)
    return to_out(await repo.create(name=name, owner_id=LOCAL_OWNER))
