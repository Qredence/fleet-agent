"""Local-filesystem artifact storage (the dev backend of the kernel protocol)."""

import shutil
from pathlib import Path

from app.kernel.storage import PathTraversalError


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
        directory = self.resolve_path(prefix)
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
