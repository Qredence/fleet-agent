"""The artifact storage contract.

Browser-visible artifact URLs are always `/api/artifacts/{id}` (controlled);
the storage backend is a server-only detail. Dev uses the local filesystem;
production swaps in object storage behind this protocol with signed URLs
(refreshed via the same endpoint contract). The protocol and the untrusted
name rules live here in the kernel; the filesystem implementation lives in
``app.services.artifact_storage``.
"""

import re
from pathlib import Path
from typing import Protocol

_STORAGE_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactStorage(Protocol):
    def save(self, *, storage_key: str, content: bytes) -> int:
        """Persist content at storage_key. Returns byte count written."""
        ...

    def resolve_path(self, storage_key: str) -> Path:
        """Absolute file path for controlled streaming. Never user-derived."""
        ...

    def delete(self, storage_key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> None:
        """Delete everything under a directory prefix (e.g. a thread folder)."""
        ...


class PathTraversalError(ValueError):
    pass


def sanitize_artifact_name(name: str) -> str:
    """Browser-supplied artifact names are untrusted input (PHASE 10).

    Any character outside [A-Za-z0-9._-] becomes '-', runs collapse, and
    leading dots are dropped — traversal can never survive this function.
    """
    clean = _STORAGE_SAFE_NAME.sub("-", name.strip())
    clean = re.sub(r"-{2,}", "-", clean).strip("-._").lstrip(".") or "artifact"
    if len(clean) > 120:
        clean = clean[:120].rstrip("-._")
    return clean
