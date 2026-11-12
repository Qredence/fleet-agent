# AG-UI State Sync — Documentation Summary

## Overview
AG-UI synchronizes agent-owned state to the client by streaming typed events over Server-Sent Events (SSE). State is delivered as an initial **snapshot** followed by incremental **deltas**, which the client applies to its local copy.

## Event protocol
AG-UI streams typed events over SSE, organized into four families:

| Category | Events |
| --- | --- |
| Lifecycle | `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR` |
| Text | `TEXT_MESSAGE_*` |
| Tool calls | `TOOL_CALL_*` |
| State | `STATE_SNAPSHOT`, `STATE_DELTA` |

## State sync semantics
- **Snapshot first:** `STATE_SNAPSHOT` carries the full state and *must arrive before any delta*.
- **Deltas after:** `STATE_DELTA` events are **RFC 6902 JSON Patch** operations applied to the client's current snapshot. Ordering matters — a delta is only valid once a snapshot is in place.

## Client integration (assistant-ui)
- `useAgUiState` mirrors the state owned by the AG-UI agent and re-renders as `STATE_SNAPSHOT` and `STATE_DELTA` events arrive.
- `useAuiState` reads assistant-ui *client* state — for example, `messages` and `thread.isRunning`.
- `showThinking=false` hides `THINKING_*` / `REASONING_*` events from the UI.

## Testing and transport contract
- Canonical NDJSON fixtures — successful, tool-error recovery, and forced-submit — replay deterministically through `POST /api/agent`.
- These fixtures are the regression contract for both the transport layer and the panel.

## Visibility boundary
The process panel renders only the intentional public trace (`AgentWorkspaceState`): steps, public summaries, tool calls, sources, artifacts, decisions, and caveats. Raw `next_thought`, prompts, and provider payloads never leave the backend.

## Key takeaways
1. Snapshot-before-delta is the core ordering invariant; clients should not apply a delta without a prior snapshot.
2. Deltas are standard JSON Patch (RFC 6902), so any compliant patch implementation can apply them.
3. Server state (`useAgUiState`) and client state (`useAuiState`) are distinct sources read through separate hooks.
4. Fixture streams are the authoritative regression contract for state-sync behavior.