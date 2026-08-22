# AG-UI State Sync

AG-UI streams typed events over Server-Sent Events (SSE). State synchronization is handled through two event types:

- **STATE_SNAPSHOT** – carries the full agent-owned state and must arrive before any delta.
- **STATE_DELTA** – an RFC 6902 JSON Patch that is applied to the client's current snapshot.

## Client Integration

- `useAgUiState` mirrors the state owned by the AG-UI agent and re-renders as `STATE_SNAPSHOT` and `STATE_DELTA` events arrive.
- `useAuiState` reads assistant-ui client state such as messages and `thread.isRunning`.
- Setting `showThinking=false` hides `THINKING_*` / `REASONING_*` events.

## Chain-of-Thought Boundary

The process panel renders only the intentional public trace (`AgentWorkspaceState`): steps, public summaries, tool calls, sources, artifacts, decisions, and caveats. Raw `next_thought`, prompts, and provider payloads never leave the backend.

## Summary

AG-UI state sync uses snapshot-plus-patch semantics over SSE, with client hooks that keep UI state in sync while preserving a clear boundary around internal reasoning.