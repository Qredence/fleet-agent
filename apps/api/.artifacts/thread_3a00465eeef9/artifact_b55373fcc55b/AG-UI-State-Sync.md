# AG-UI State Sync

AG-UI streams typed events over SSE, including lifecycle, text, tool call, and state events. State synchronization is handled through two event types:

- **STATE_SNAPSHOT** – the full state owned by the AG-UI agent.
- **STATE_DELTA** – an RFC 6902 JSON Patch that is applied to the client snapshot.

The snapshot must arrive before any delta is applied.

In assistant-ui, `useAgUiState` mirrors the state owned by the AG-UI agent and re-renders as STATE_SNAPSHOT and STATE_DELTA events arrive. `useAuiState` reads assistant-ui client state such as messages and `thread.isRunning`. Setting `showThinking=false` hides THINKING_*/REASONING_* events.

A chain-of-thought boundary is maintained: the process panel renders only the intentional public trace (AgentWorkspaceState) containing steps, public summaries, tool calls, sources, artifacts, decisions, and caveats. Raw `next_thought`, prompts, and provider payloads never leave the backend.