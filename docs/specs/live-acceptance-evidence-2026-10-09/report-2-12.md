# AG-UI State Sync — Documentation Summary

## Overview
The documentation describes AG-UI as a protocol that streams **typed events over SSE (Server-Sent Events)**. State synchronization is one of four event families in that protocol, alongside lifecycle, text, and tool-call events.

## Event families
| Family | Events |
| --- | --- |
| Lifecycle | `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR` |
| Text | `TEXT_MESSAGE_*` |
| Tool calls | `TOOL_CALL_*` |
| State | `STATE_SNAPSHOT`, `STATE_DELTA` |

## Key facts on state sync

**Snapshot and delta model.** State is communicated with two event types:
- `STATE_SNAPSHOT` — a full state snapshot sent to the client.
- `STATE_DELTA` — an incremental change.

**Ordering requirement.** A snapshot must arrive **before any delta**. The docs state this is a hard requirement: the snapshot is the base against which deltas are applied.

**Delta format.** Deltas are **RFC 6902 JSON Patch** operations, applied to the client's current snapshot.

**Client-side consumption (assistant-ui).**
- `useAgUiState` mirrors the state that the **AG-UI agent owns**, and re-renders as `STATE_SNAPSHOT` and `STATE_DELTA` events arrive.
- `useAuiState` reads **assistant-ui client state** (for example messages and `thread.isRunning`) — this is distinct from agent-owned state.
- `showThinking=false` hides `THINKING_*` / `REASONING_*` events.

## Related boundary (scope note)
The documentation also describes a chain-of-thought boundary: a process panel renders an intentional public trace (`AgentWorkspaceState`) covering steps, public summaries, tool calls, sources, artifacts, decisions, and caveats. Raw `next_thought`, prompts, and provider payloads never leave the backend. This is adjacent to state sync but concerns what is exposed in the public trace rather than the snapshot/delta transport.

## Practical implications
1. Consumers should be prepared to receive a snapshot first and treat deltas as patches on top of it.
2. Because deltas are RFC 6902, client implementations need a JSON Patch implementation rather than bespoke merge logic.
3. Choose the right hook: `useAgUiState` for agent-owned synchronized state; `useAuiState` for assistant-ui client state.

## Caveats on this summary
- The summary is drawn from a single documentation search result; it may not cover all state-sync details the documentation contains.
- No versions, API signatures, or code examples were present in the retrieved evidence.