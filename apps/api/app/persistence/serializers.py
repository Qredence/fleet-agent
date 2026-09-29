"""Row → public wire projections for persistence models.

The API layer owns HTTP concerns; these serializers own the shape of what
a database row becomes on the wire, so routes stay thin and the projections
live beside the models they read.
"""

from __future__ import annotations

from typing import Any

from app.contracts.thread_bootstrap import ThreadOut
from app.persistence.models import Artifact, Thread


def artifact_to_out(artifact: Artifact) -> dict[str, Any]:
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


def thread_to_out(thread: Thread) -> ThreadOut:
    return ThreadOut(
        id=thread.id,
        projectId=thread.project_id,
        title=thread.title,
        status=thread.status,
        lastRunId=thread.last_run_id,
        createdAt=thread.created_at.isoformat(),
        updatedAt=thread.updated_at.isoformat(),
    )
