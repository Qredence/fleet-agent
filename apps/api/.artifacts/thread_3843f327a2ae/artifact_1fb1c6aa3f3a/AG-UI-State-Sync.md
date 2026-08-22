# AG-UI State Sync

AG-UI uses Server-Sent Events (SSE) to stream typed events, including state synchronization events.

## State Events

- `STATE_SNAPSHOT`: Provides the full state snapshot to the client.
- `STATE_DELTA`: Provides incremental updates as RFC 6902 JSON Patch operations.

## Synchronization Flow

1. The client must receive a `STATE_SNAPSHOT` before any `STATE_DELTA`.
2. Deltas are applied to the client's snapshot to keep it in sync.

## Client Integration

- `useAgUiState` mirrors the agent-owned state and re-renders as snapshot/delta events arrive.
- `useAuiState` reads assistant-ui client state (e.g., messages, thread status).
- `showThinking=false` hides `THINKING_*`/`REASONING_*` events.

## Privacy Boundary

The process panel renders only the intentional public trace (steps, summaries, tool calls, sources, artifacts, decisions, caveats). Raw `next_thought`, prompts, and provider payloads never leave the backend.