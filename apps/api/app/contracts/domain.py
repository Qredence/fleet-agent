"""Domain events produced inside a run (worker-thread tools, engine).

They are converted to public AG-UI events by the trace reducer + event
mapper; domain events never travel on the wire directly.
"""

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class DomainEvent:
    """Base type for run-scoped domain events."""


@dataclass(frozen=True)
class ToolStarted(DomainEvent):
    tool_call_id: str
    name: str
    """Redacted, size-limited argument preview (never raw args)."""
    input_preview: str


@dataclass(frozen=True)
class ToolCompleted(DomainEvent):
    tool_call_id: str
    name: str
    """Bounded result preview for the state; thread result is truncated too."""
    output_preview: str
    duration_ms: int


@dataclass(frozen=True)
class ToolFailed(DomainEvent):
    tool_call_id: str
    name: str
    """Public-safe error message; internal details stay server-side."""
    error_message: str
    duration_ms: int


class SourceResult(BaseModel):
    """Standard contract for retrieval-tool sources (plan.md Phase 10)."""

    id: str
    title: str
    source_type: str
    uri: str | None = None
    excerpt: str | None = None
    metadata: dict[str, object] = {}


@dataclass(frozen=True)
class SourceDiscovered(DomainEvent):
    tool_call_id: str
    source: SourceResult


class ArtifactResult(BaseModel):
    """Standard contract for generated artifacts (plan.md Phase 10)."""

    id: str
    name: str
    media_type: str
    storage_key: str
    size_bytes: int | None = None


@dataclass(frozen=True)
class ArtifactStarted(DomainEvent):
    artifact: ArtifactResult


@dataclass(frozen=True)
class ArtifactReady(DomainEvent):
    artifact: ArtifactResult
    """Controlled relative URL — never a server filesystem path."""
    download_url: str


@dataclass(frozen=True)
class ArtifactFailed(DomainEvent):
    artifact_id: str
    name: str
    media_type: str
