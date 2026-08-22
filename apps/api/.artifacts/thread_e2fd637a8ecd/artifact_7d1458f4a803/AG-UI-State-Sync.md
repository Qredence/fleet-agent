# AG-UI State Sync

AG-UI streams typed events over Server-Sent Events (SSE). State synchronization is handled through two event types:

- **STATE_SNAPSHOT** – provides the full client-side state snapshot.
- **STATE_DELTA** – contains an RFC 6902 JSON Patch that is applied to the snapshot to update the state.

The snapshot must arrive before any delta is applied.

## Client Integration

- `useAgUiState` mirrors the state owned by the AG-UI agent and re-renders as `STATE_SNAPSHOT` and `STATE_DELTA` events arrive.
- `useAuiState` reads assistant-ui client state such as messages and `thread.isRunning`.
- Setting `showThinking=false` hides `THINKING_*` and `REASONING_*` events.

## Chain-of-Thought Boundary

The process panel renders only the intentional public trace (`AgentWorkspaceState`): steps, public summaries, tool calls, sources, artifacts, decisions, and caveats. Raw `next_thought`, prompts, and provider payloads never leave the backend.
