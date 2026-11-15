"""Artifact download + listing endpoints (controlled access).

Browser URLs are ONLY `/api/artifacts/{id}` — no filesystem paths, no direct
storage keys. Access is scoped: the artifact's thread must belong to the
(local) owner; downloads force attachment disposition + nosniff.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_sessions, require_thread
from app.kernel.storage import PathTraversalError
from app.persistence.repositories import ArtifactsRepository

router = APIRouter(prefix="/api", tags=["artifacts"])

_SAFE_MEDIA_TYPES = {"text/markdown", "text/plain", "application/json", "text/csv"}


@router.get("/artifacts/{artifact_id}")
async def download_artifact(
    artifact_id: str,
    request: Request,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> FileResponse:
    artifact = await ArtifactsRepository(sessions).get(artifact_id)
    if artifact is None or artifact.status != "ready":
        raise HTTPException(status_code=404, detail="Artifact not found.")
    await require_thread(artifact.thread_id, sessions)
    if artifact.media_type not in _SAFE_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported artifact media type.")

    try:
        path = request.app.state.artifact_storage.resolve_path(artifact.storage_key)
    except PathTraversalError:
        raise HTTPException(status_code=404, detail="Artifact not found.") from None

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")

    return FileResponse(
        path,
        media_type=artifact.media_type,
        filename=artifact.name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )
