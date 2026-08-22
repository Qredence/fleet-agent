# AG-UI State Sync

AG-UI streams typed events over Server-Sent Events (SSE). State synchronization is handled through two event types:

- **STATE_SNAPSHOT** – carries the full client-side state snapshot and must arrive before any delta.
- **STATE_DELTA** – contains an RFC 6902 JSON Patch that is applied to the client snapshot to update the state incrementally.

This design keeps the client in sync with the state owned by the AG-UI agent. In assistant-ui, `useAgUiState` mirrors this agent-owned state and re-renders as snapshot and delta events arrive. Separately, `useAuiState` reads assistant-ui client state such as messages and `thread.isRunning`.

For privacy and safety, raw internal reasoning (e.g., `next_thought`, prompts, provider payloads) never leaves the backend. The process panel renders only the intentional public trace (`AgentWorkspaceState`): steps, public summaries, tool calls, sources, artifacts, decisions, and caveats.

In short, AG-UI state sync uses snapshot-plus-patch events over SSE to keep clients updated efficiently and safely.