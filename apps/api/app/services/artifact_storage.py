"""Artifact storage abstraction.

Browser-visible artifact URLs are always `/api/artifacts/{id}` (controlled);
the storage backend is a server-only detail. Dev uses the local filesystem;
production swaps in object storage behind this protocol with signed URLs
(refreshed via the same endpoint contract).
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


class LocalArtifactStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, *, storage_key: str, content: bytes) -> int:
        path = self.resolve_path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return len(content)

    def resolve_path(self, storage_key: str) -> Path:
        candidate = (self._root / storage_key).resolve()
        if self._root not in candidate.parents and candidate != self._root:
            raise PathTraversalError(f"storage key escapes root: {storage_key!r}")
        return candidate

    def delete(self, storage_key: str) -> None:
        try:
            self.resolve_path(storage_key).unlink()
        except FileNotFoundError:
            pass

    def delete_prefix(self, prefix: str) -> None:
        import shutil

        directory = self.resolve_path(prefix)
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
