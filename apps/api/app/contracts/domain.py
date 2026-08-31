"""Domain events produced inside a run (worker-thread tools, engine).

They are converted to public AG-UI events by the trace reducer + event
mapper; domain events never travel on the wire directly.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class DomainEvent:
    """Base type for run-scoped domain events."""


InlineEventName = Literal[
    "agent-progress",
    "web-search",
    "sources",
    "research-report",
]


@dataclass(frozen=True)
class InlineDataEvent(DomainEvent):
    """A bounded assistant-ui data part that is not public process state."""

    name: InlineEventName
    value: dict[str, object]


@dataclass(frozen=True)
class ToolStarted(DomainEvent):
    tool_call_id: str
    name: str
    """Complete, redacted JSON used by the AG-UI tool-arguments channel."""
    arguments_json: str
    """Redacted, size-limited argument preview (never raw args)."""
    input_preview: str
    step_id: str | None = None


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
    step_id: str | None = None


@dataclass(frozen=True)
class StepStarted(DomainEvent):
    """A user-safe process step, optionally nested under a staged phase."""

    step_id: str
    phase: str
    title: str
    parent_id: str | None = None


@dataclass(frozen=True)
class StepCompleted(DomainEvent):
    step_id: str
    public_summary: str | None = None


@dataclass(frozen=True)
class StepFailed(DomainEvent):
    step_id: str
    public_summary: str


@dataclass(frozen=True)
class FinalFieldsReady(DomainEvent):
    """The finish tool just delivered the public answer/summary.

    Emitted the moment ReActV2's submit tool executes, so the browser sees
    the answer before the run settles. Carries only AgentSignature output
    fields — never raw reasoning or provider payloads.
    """

    answer: str | None = None
    process_summary: str | None = None


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
    step_id: str | None = None


@dataclass(frozen=True)
class ArtifactReady(DomainEvent):
    artifact: ArtifactResult
    """Controlled relative URL — never a server filesystem path."""
    download_url: str
    step_id: str | None = None


@dataclass(frozen=True)
class ArtifactFailed(DomainEvent):
    artifact_id: str
    name: str
    media_type: str
