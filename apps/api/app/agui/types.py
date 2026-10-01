"""Shared AG-UI transport types.

The event mapper, the trace reducer, and the coordinators all speak in JSON
Patch operations and domain events; the aliases live here so the modules
depend on a common vocabulary instead of on each other.
"""

from __future__ import annotations

from typing import Any

from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactStarted,
    FinalFieldsReady,
    InlineDataEvent,
    SourceDiscovered,
    StepCompleted,
    StepFailed,
    StepStarted,
    SynthesisTokenDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

# One RFC 6902 JSON Patch operation, as carried by AG-UI STATE_DELTA events.
JsonPatchOp = dict[str, Any]

# Every domain event the agent layer can emit on the run event bus.
AnyDomainEvent = (
    InlineDataEvent
    | ToolStarted
    | ToolCompleted
    | ToolFailed
    | SourceDiscovered
    | StepStarted
    | StepCompleted
    | StepFailed
    | ArtifactStarted
    | ArtifactReady
    | ArtifactFailed
    | FinalFieldsReady
    | SynthesisTokenDelta
)
