# AG-UI State Synchronization — Documentation Summary

## Overview

AG-UI (Agent User Interaction Protocol) provides efficient state management between agents and frontends through dedicated, typed state events. State sync is one of the protocol's headline features: the project describes "bi-directional state synchronization" and "real-time context enrichment" as core capabilities.

## State Events

AG-UI defines three state-related events:

| Event | Purpose |
| --- | --- |
| `STATE_SNAPSHOT` | Complete state representation at a point in time |
| `STATE_DELTA` | Incremental state change, expressed as JSON Patch (RFC 6902) |
| `MESSAGES_SNAPSHOT` | Complete conversation history |

The snapshot/delta pair is designed to keep client-side state management efficient with minimal data transfer: a full snapshot establishes the baseline, and subsequent updates ship only the changed portions as RFC 6902 JSON Patch operations applied to the client's current snapshot.

**Ordering rule:** the snapshot must arrive before any delta. A delta is applied against the client snapshot, so a delta with no preceding snapshot has nothing valid to patch.

## Transport and Event Stream

AG-UI streams typed events over SSE (Server-Sent Events). Event families include:

- **Lifecycle:** `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`
- **Text:** `TEXT_MESSAGE_*`
- **Tool calls:** `TOOL_CALL_*`
- **State:** `STATE_SNAPSHOT`, `STATE_DELTA`

## Framework Integration

**assistant-ui**
- `useAgUiState` mirrors state that the AG-UI agent owns and re-renders as `STATE_SNAPSHOT` and `STATE_DELTA` events arrive.
- `useAuiState` reads assistant-ui *client* state, such as messages and `thread.isRunning`.
- `showThinking=false` hides `THINKING_*` / `REASONING_*` events.

**LangChain DeepAgents (JavaScript)**
- Shared state (todos, subagents, custom keys) maps to `STATE_SNAPSHOT` and `STATE_DELTA`.
- Conversation history maps to `MESSAGES_SNAPSHOT`.
- Client-side handlers such as `onStateSnapshotEvent` expose incoming state events to application code.

## Illustrative Use

A secondary source describes a typical flow: a tool call returns product data that the frontend renders as cards; when the user adds an item to a cart, the agent sends a small `STATE_DELTA` patch and the cart UI updates instantly without a page reload; the run then closes with `RUN_FINISHED`.

## Summary of Key Facts

1. Two mechanisms cover application state: full snapshots and incremental deltas.
2. Deltas use the standard JSON Patch format (RFC 6902), enabling partial updates.
3. Snapshots must precede deltas for a given client state.
4. Conversation history is carried separately via `MESSAGES_SNAPSHOT`.
5. State events travel in the same SSE stream as lifecycle, text, and tool-call events.
6. State synchronization is bidirectional, supporting agent-driven UI updates and frontend-owned state.