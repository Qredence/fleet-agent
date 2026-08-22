"""Artifact download + listing endpoints (controlled access).

Browser URLs are ONLY `/api/artifacts/{id}` — no filesystem paths, no direct
storage keys. Access is scoped: the artifact's thread must belong to the
(local) owner; downloads force attachment disposition + nosniff.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.persistence.repositories import ArtifactsRepository
from app.services.artifact_storage import PathTraversalError

router = APIRouter(prefix="/api", tags=["artifacts"])

_SAFE_MEDIA_TYPES = {"text/markdown", "text/plain", "application/json", "text/csv"}


def artifact_to_out(artifact: Any) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "name": artifact.name,
        "mediaType": artifact.media_type,
        "sizeBytes": artifact.size_bytes,
        "status": artifact.status,
        "downloadUrl": f"/api/artifacts/{artifact.id}"
        if artifact.status == "ready"
        else None,
    }


@router.get("/artifacts/{artifact_id}")
async def download_artifact(artifact_id: str, request: Request) -> FileResponse:
    artifact = await ArtifactsRepository(request.app.state.db_sessions).get(artifact_id)
    if artifact is None or artifact.status != "ready":
        raise HTTPException(status_code=404, detail="Artifact not found.")
    if artifact.media_type not in _SAFE_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported artifact media type.")

    try:
        path = request.app.state.artifact_storage.resolve_path(artifact.storage_key)
    except PathTraversalError:
        raise HTTPException(status_code=404, detail="Artifact not found.") from None

    return FileResponse(
        path,
        media_type=artifact.media_type,
        filename=artifact.name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )
