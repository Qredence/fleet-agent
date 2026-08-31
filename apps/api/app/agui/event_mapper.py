"""Domain event → AG-UI event mapping (pure)."""

import re

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    StateDeltaEvent,
    TextMessageContentEvent,
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
    SynthesisTokenDelta,
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
    | SynthesisTokenDelta
)

_TEXT_CHUNK_SIZE = 24
_WHITESPACE_SPLIT = re.compile(r"(\s+)")


def chunk_text(text: str, *, chunk_size: int = _TEXT_CHUNK_SIZE) -> list[str]:
    """Split text into small word-boundary chunks for incremental streaming.

    Whitespace is preserved: concatenating the chunks reproduces the input
    exactly, including newlines and repeated spaces.
    """
    if not text:
        return []
    tokens = [token for token in _WHITESPACE_SPLIT.split(text) if token]
    chunks: list[str] = []
    current = ""
    for token in tokens:
        if len(current) + len(token) > chunk_size and current:
            chunks.append(current)
            current = ""
        current += token
    if current:
        chunks.append(current)
    return chunks


def map_domain_event(
    event: AnyDomainEvent,
    *,
    assistant_message_id: str,
    reducer: TraceReducer,
    emit_answer_text: bool = True,
) -> list[BaseEvent]:
    """
    Convert a domain event into the corresponding AG-UI events and state updates.

    Parameters:
        event (AnyDomainEvent): The domain event to convert.
        assistant_message_id (str): The single assistant message for this run.
        emit_answer_text (bool): Whether FinalFieldsReady may (re)emit the
            answer as message text; false once tokens already streamed it.

    Returns:
        list[BaseEvent]: The AG-UI events representing the domain event.
    """
    if isinstance(event, FinalFieldsReady):
        return map_final_fields_event(
            event,
            assistant_message_id=assistant_message_id,
            reducer=reducer,
            emit_answer_text=emit_answer_text,
        )

    if isinstance(event, SynthesisTokenDelta):
        return map_synthesis_token_event(
            event, assistant_message_id=assistant_message_id, reducer=reducer
        )

    if isinstance(event, InlineDataEvent):
        return [CustomEvent(name=event.name, value=event.value)]

    ops = reducer.apply_event(event)
    if isinstance(event, (ToolStarted, ToolCompleted, ToolFailed)):
        return map_tool_event(
            event, assistant_message_id=assistant_message_id, state_delta_ops=ops
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
    assistant_message_id: str,
    state_delta_ops: list[JsonPatchOp],
) -> list[BaseEvent]:
    """
    Convert a tool lifecycle event into AG-UI events, including any associated state
        updates.

    Parameters:
        event: The tool start, completion, or failure event to convert.
        assistant_message_id: The assistant message containing the tool call.
        state_delta_ops: State operations to include in the resulting events.

    Returns:
        list[BaseEvent]: The AG-UI events representing the tool event and any state
            changes.
    """
    events: list[BaseEvent] = []

    if isinstance(event, ToolStarted):
        events.append(
            ToolCallStartEvent(
                tool_call_id=event.tool_call_id,
                tool_call_name=event.name,
                parent_message_id=assistant_message_id,
            )
        )
        events.append(
            ToolCallArgsEvent(
                tool_call_id=event.tool_call_id, delta=event.arguments_json
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
                message_id=f"msg-tool-{event.tool_call_id}",
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
    assistant_message_id: str,
    reducer: TraceReducer,
    emit_answer_text: bool = True,
) -> list[BaseEvent]:
    """Convert final answer and process summary fields into AG-UI events.

    Parameters:
        event (FinalFieldsReady): Final answer and process summary data.
        assistant_message_id (str): Identifier for the assistant message.
        reducer (TraceReducer): Reducer used to apply the process summary.
        emit_answer_text (bool): False once token streaming already delivered
            the answer text, so the settled fields update state without
            duplicating the message text.

    Returns:
        list[BaseEvent]: Streamed answer and state update events.
    """
    events: list[BaseEvent] = []

    if emit_answer_text and event.answer:
        for chunk in chunk_text(event.answer):
            events.append(
                TextMessageContentEvent(message_id=assistant_message_id, delta=chunk)
            )

    if event.process_summary:
        ops = reducer.live_synthesis_summary(event.process_summary)
        if ops:
            events.append(StateDeltaEvent(delta=ops))
    return events


def map_synthesis_token_event(
    event: SynthesisTokenDelta,
    *,
    assistant_message_id: str,
    reducer: TraceReducer,
) -> list[BaseEvent]:
    """Convert one streamed synthesis token into its AG-UI event.

    Answer tokens append to the assistant message text; summary tokens
    update the synthesis step's live summary state.
    """
    if event.field == "answer":
        if not event.delta:
            return []
        return [
            TextMessageContentEvent(message_id=assistant_message_id, delta=event.delta)
        ]
    ops = reducer.live_synthesis_summary(event.summary_so_far or event.delta)
    if not ops:
        return []
    return [StateDeltaEvent(delta=ops)]
