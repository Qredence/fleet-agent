"""write_report tool: generates a markdown artifact through the full
ArtifactStarted -> ArtifactReady / ArtifactFailed lifecycle.

Bounded by design: sanitized file name, capped content, storage confined to
the per-run directory. Failures raise so the wrapper marks the tool call
failed and ReActV2 can recover.
"""

import uuid

from app.agui.event_bus import RunEventBus
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactResult,
    ArtifactStarted,
)
from app.services.artifact_storage import ArtifactStorage, sanitize_artifact_name

_DOWNLOAD_PREFIX = "/api/artifacts"


class WriteReportTool:
    def __init__(
        self,
        *,
        storage: ArtifactStorage,
        bus: RunEventBus,
        thread_id: str,
        max_bytes: int,
        step_id: str | None = None,
    ) -> None:
        self.__name__ = "write_report"
        self.__doc__ = WriteReportTool.__call__.__doc__
        self._storage = storage
        self._bus = bus
        self._thread_id = thread_id
        self._max_bytes = max_bytes
        self._step_id = step_id

    def __call__(self, title: str, content: str) -> str:
        """Write a short markdown report and return it as a downloadable artifact."""
        artifact_id = f"artifact_{uuid.uuid4().hex[:12]}"
        name = sanitize_artifact_name(title)
        if not name.endswith(".md"):
            name = f"{name}.md"

        artifact = ArtifactResult(
            id=artifact_id,
            name=name,
            media_type="text/markdown",
            storage_key=f"{self._thread_id}/{artifact_id}/{name}",
        )
        self._bus.publish_from_worker(
            ArtifactStarted(artifact=artifact, step_id=self._step_id)
        )

        truncated = len(content.encode()) > self._max_bytes
        payload = content.encode()[: self._max_bytes]
        try:
            size = self._storage.save(storage_key=artifact.storage_key, content=payload)
        except Exception:
            self._bus.publish_from_worker(
                ArtifactFailed(
                    artifact_id=artifact_id, name=name, media_type="text/markdown"
                )
            )
            raise

        ready = artifact.model_copy(update={"size_bytes": size})
        self._bus.publish_from_worker(
            ArtifactReady(
                artifact=ready,
                download_url=f"{_DOWNLOAD_PREFIX}/{artifact_id}",
                step_id=self._step_id,
            )
        )
        note = " (content truncated to the size limit)" if truncated else ""
        return f"Report '{title}' saved as {name} ({size} bytes{note})."
