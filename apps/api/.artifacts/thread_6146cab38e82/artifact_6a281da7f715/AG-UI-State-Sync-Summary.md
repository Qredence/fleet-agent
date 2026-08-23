# AG-UI State Sync

AG-UI streams typed events over Server-Sent Events (SSE). State synchronization is handled through two event types:

- **STATE_SNAPSHOT** – a full snapshot of the agent-owned state that must arrive before any deltas.
- **STATE_DELTA** – an RFC 6902 JSON Patch that is applied to the client-side snapshot to update it incrementally.

This mechanism allows the client to mirror the state owned by the AG-UI agent and re-render as events arrive. In assistant-ui, `useAgUiState` consumes these events to keep the UI in sync, while `useAuiState` reads client-side state such as messages and thread status.

For privacy and safety, raw internal reasoning (e.g., `next_thought`, prompts, provider payloads) is never sent to the client. Only intentional public trace data—steps, summaries, tool calls, sources, artifacts, decisions, and caveats—is exposed through the process panel.