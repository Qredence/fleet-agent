"""Projects REST resources."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import LOCAL_OWNER, get_sessions, require_project
from app.persistence.models import Project
from app.persistence.repositories import ProjectsRepository, ThreadsRepository

router = APIRouter(prefix="/api", tags=["projects"])


class ProjectOut(BaseModel):
    id: str
    name: str
    createdAt: str
    updatedAt: str


class ProjectCreate(BaseModel):
    name: str


class ProjectPatch(BaseModel):
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


@router.patch("/projects/{project_id}")
async def rename_project(
    project_id: str,
    body: ProjectPatch,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> ProjectOut:
    await require_project(project_id, sessions)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name must not be empty.")
    project = await ProjectsRepository(sessions).rename(project_id, name=name)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return to_out(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, request: Request) -> None:
    sessions = request.app.state.db_sessions
    await require_project(project_id, sessions)
    thread_ids = [
        thread.id
        for thread in await ThreadsRepository(sessions).list_for_project(project_id)
    ]
    await ProjectsRepository(sessions).delete(project_id)
    # Retention: artifact files of every deleted thread are removed with it.
    for thread_id in thread_ids:
        request.app.state.artifact_storage.delete_prefix(f"{thread_id}/")
