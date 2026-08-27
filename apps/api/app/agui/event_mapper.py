"""Domain event → AG-UI event mapping (pure)."""

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    StateDeltaEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from app.agent.instrumented import truncate_result
from app.agui.trace_reducer import JsonPatchOp, TraceReducer
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
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

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
)

_TEXT_CHUNK_SIZE = 24


def chunk_text(text: str, *, chunk_size: int = _TEXT_CHUNK_SIZE) -> list[str]:
    """Split text into small word-boundary chunks for incremental streaming."""
    if not text:
        return []
    words = text.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if len(candidate) > chunk_size and current:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def map_domain_event(
    event: AnyDomainEvent,
    *,
    tools_message_id: str,
    reducer: TraceReducer,
    answer_message_id: str | None = None,
) -> list[BaseEvent]:
    """Single dispatch point: applies the state delta and wraps the
    AG-UI events for the domain event's kind.

    Inline data is deliberately not applied to ``AgentWorkspaceState``. It is
    a bounded transcript projection, while the process panel remains the
    authoritative AG-UI state view.
    """
    if isinstance(event, FinalFieldsReady):
        return map_final_fields_event(
            event, answer_message_id=answer_message_id, reducer=reducer
        )

    if isinstance(event, InlineDataEvent):
        return [CustomEvent(name=event.name, value=event.value)]

    ops = reducer.apply_event(event)
    if isinstance(event, (ToolStarted, ToolCompleted, ToolFailed)):
        return map_tool_event(
            event, tools_message_id=tools_message_id, state_delta_ops=ops
        )

    events: list[BaseEvent] = []
    if ops:
        events.append(StateDeltaEvent(delta=ops))
    if isinstance(event, ArtifactReady):
        # Inline artifact card in the thread (message-scoped); the full record
        # lives in the panel via the state delta above.
        events.append(
            CustomEvent(
                name="artifact",
                value={
                    "schemaVersion": 1,
                    "id": event.artifact.id,
                    "name": event.artifact.name,
                    "mediaType": event.artifact.media_type,
                    "downloadUrl": event.download_url,
                },
            )
        )
    return events


def map_tool_event(
    event: ToolStarted | ToolCompleted | ToolFailed,
    *,
    tools_message_id: str,
    state_delta_ops: list[JsonPatchOp],
) -> list[BaseEvent]:
    events: list[BaseEvent] = []

    if isinstance(event, ToolStarted):
        events.append(
            ToolCallStartEvent(
                tool_call_id=event.tool_call_id,
                tool_call_name=event.name,
                parent_message_id=tools_message_id,
            )
        )
        events.append(
            ToolCallArgsEvent(
                tool_call_id=event.tool_call_id, delta=event.input_preview
            )
        )
        events.append(ToolCallEndEvent(tool_call_id=event.tool_call_id))
    else:
        content = (
            truncate_result(event.output_preview)
            if isinstance(event, ToolCompleted)
            else event.error_message
        )
        events.append(
            ToolCallResultEvent(
                message_id=tools_message_id,
                tool_call_id=event.tool_call_id,
                content=content,
                role="tool",
            )
        )

    if state_delta_ops:
        events.append(StateDeltaEvent(delta=state_delta_ops))
    return events


def map_final_fields_event(
    event: FinalFieldsReady,
    *,
    answer_message_id: str | None,
    reducer: TraceReducer,
) -> list[BaseEvent]:
    """Stream the finish tool's answer as one text message, then the summary.

    The answer becomes a complete TextMessage trio (the coordinator suppresses
    its completion-time re-emission when it saw this); the process summary
    lands on the synthesis step via a state delta so the panel shows synthesis
    running with the model's own summary before the run settles.
    """
    events: list[BaseEvent] = []

    if event.answer and answer_message_id:
        events.append(
            TextMessageStartEvent(message_id=answer_message_id, role="assistant")
        )
        for chunk in chunk_text(event.answer):
            events.append(
                TextMessageContentEvent(message_id=answer_message_id, delta=chunk)
            )
        events.append(TextMessageEndEvent(message_id=answer_message_id))

    if event.process_summary:
        ops = reducer.live_synthesis_summary(event.process_summary)
        if ops:
            events.append(StateDeltaEvent(delta=ops))
    return events
