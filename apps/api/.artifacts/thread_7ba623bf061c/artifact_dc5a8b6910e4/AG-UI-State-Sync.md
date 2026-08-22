# AG-UI State Sync

AG-UI streams typed events over SSE, including state events:

- **STATE_SNAPSHOT** – the full client-side state snapshot.
- **STATE_DELTA** – an RFC 6902 JSON Patch applied to the snapshot.

The snapshot must arrive before any delta. As deltas arrive, the client applies them and re-renders.

## Client Integration

- `useAgUiState` mirrors the state owned by the AG-UI agent and re-renders on snapshot/delta events.
- `useAuiState` reads assistant-ui client state (e.g., messages, `thread.isRunning`).

## Privacy Boundary

Raw internal reasoning (e.g., `next_thought`, prompts, provider payloads) never leaves the backend. Only the intentional public trace is exposed via the process panel.