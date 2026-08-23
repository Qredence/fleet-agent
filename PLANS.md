# Fleet-Agent Persistence, Branching, and Restoration Hardening

## Summary

This plan makes run creation and terminal transitions transactional, persists every terminal outcome, scopes DSPy history and process state to assistant-ui branches, fixes source/cumulative-state identities, and restores the complete safe UI repository without late-bootstrap races.

The implementation preserves existing database data and retains the chain-of-thought boundary: DSPy histories, `next_thought`, provider prompts, reasoning parts, stack traces, and unredacted tool data remain server-side.

## Implementation sequence

### 1. Introduce the data-preserving branch-aware schema

Add one Alembic migration before changing runtime behavior.

- Extend `threads` with `active_head_message_id`.
- Evolve `messages` into a branchable repository with an internal row ID, a thread-scoped `message_id`, `parent_message_id`, a versioned `format` (`ag-ui/v1` or `aui/v0`), JSON content, optional `run_config_json`, `updated_at`, and a unique `(thread_id, message_id)` constraint.
- Extend `runs` with `reserved_at`, nullable `started_at`, `input_message_id`, `continuation_message_id`, and nullable `output_message_id`.
- Key DSPy histories by `(thread_id, head_message_id)` while retaining DSPy and serialization version columns.
- Store process snapshots per run/head instead of one mutable snapshot per thread.
- Give sources an internal surrogate row ID, separate public `source_id` and canonical `identity_key`, thread-scoped canonical uniqueness, and source-occurrence rows preserving run/tool-call discoveries.

Migration backfills must convert existing messages to `ag-ui/v1`, reconstruct their linear parent chain, deterministically rename duplicate/missing message IDs, set each thread’s active head, attach existing histories/snapshots to the reconstructed head/latest run, preserve unresolved history server-side, and preserve all prior source/artifact/run/message data. Downgrade is supported only when legacy-required fields can be restored; it aborts explicitly before destructive steps for branch data or runs that still have a nullable `started_at`.

### 2. Make run reservation and lifecycle transitions atomic

Refactor lifecycle persistence around short-lived transaction-bound `AsyncSession`s. Repository methods used by lifecycle transitions must not commit independently.

- `reserve_run`: validate the thread inside the transaction, insert `queued`, derive the input and continuation message IDs, insert a non-destructive `ag-ui/v1` user fallback when needed, update `last_run_id` and the active head, and commit as one unit.
- `mark_running`: transition only `queued → running`, set `started_at`, persist the initial branch snapshot, and commit before `RUN_STARTED`/`STATE_SNAPSHOT`.
- `settle_completed`: transition only non-terminal runs, persist the assistant fallback/output identity, final snapshot, usage, termination reason, and branch-keyed DSPy history atomically, and advance the head only with a compare-and-set against the input head.
- `settle_failed`/`settle_cancelled`: persist terminal status, safe error, termination reason, final snapshot, and available history atomically; use the input message as the terminal head when no assistant exists; make settlement idempotent.
- Acquire the semaphore before authoritative reservation, release it immediately on reservation failure, and hold it until the accepted stream exits. Saturated requests create no rows. No transaction spans DSPy execution or SSE streaming.

### 3. Persist every unexpected terminal failure

Use one terminal-settlement path for normal failures, timeouts, disconnects, cancellation, reducer/mapper errors, and unexpected engine exceptions.

- Convert unexpected exceptions to a safe `internal_error` result, log details only server-side, complete the public reducer state, and persist before `RUN_ERROR`.
- Persist `agent_timeout` and `run_cancelled` explicitly.
- On task cancellation, perform a bounded shielded cancellation settlement before re-raising.
- Retry terminal persistence once in a fresh session for retryable transaction failures.
- Guard terminal event emission so each accepted run emits at most one terminal event and records duration/error metrics once.
- Retain startup reconciliation for orphaned `queued`/`running` rows.

### 4. Correct source and cumulative-state identity

Use one canonical-source helper in the reducer and persistence layer: normalized URI (scheme/host/path/query, no fragment/trailing slash), or a document/source ID fallback. Scope public IDs and uniqueness to the thread, reuse the first public ID for repeated canonical discoveries, and retain every discovery occurrence without duplicating canonical state.

Make state branch-specific. Load prior state from the selected continuation head or nearest ancestor, never the globally latest thread run. Carry only sources, artifacts, and accepted decisions along that branch; rebuild source/artifact indexes from inherited arrays; use `decision-{run_id}-{index}` IDs; and prevent repeated IDs from being appended or relinked. Keep steps, tool calls, caveats, duration, token usage, and model/tool metrics current-run only. The generated `AgentWorkspaceState` shape remains unchanged.

### 5. Align assistant-ui branches with DSPy history

Add idempotent history APIs:

- `PUT /api/threads/{thread_id}/messages/{message_id}` with `{ parentId, format: "aui/v0", content, runConfig? }` for assistant-ui `append`/`update`.
- `PUT /api/threads/{thread_id}/history/head` with `{ headId }` for selected branch-head persistence.

The message endpoint upserts by `(thread_id, message_id)`, may enrich an `ag-ui/v1` fallback, and cannot mutate run, DSPy, source, artifact, or agent-state records.

Replace the no-op `ThreadHistoryAdapter` with a serialized, idempotent adapter that loads an `ExportedMessageRepository`, decodes `aui/v0` directly, converts `ag-ui/v1` through `fromAgUiMessages(..., { showThinking: false })`, persists append/update, syncs head changes, and invalidates bootstrap cache after writes.

DSPy continuation is keyed to branch ancestry: normal turns use the preceding assistant head; edits fork from the edited message’s predecessor; regenerations create sibling assistant branches; completed histories use the new assistant head; failed histories use the input user head; and missing direct histories walk ancestors before using the migrated legacy fallback. DSPy history is never returned to the browser. History writes reject reasoning/raw internal fields and retain only safe user-visible parts, redacted tool data, validated artifact/data parts, statuses, timing, and run configuration.

### 6. Make restoration complete and race-safe

Change bootstrap to return one versioned snapshot containing `schemaVersion`, thread metadata, a branch repository (`headId` plus `{id,parentId,format,content,runConfig}` entries), the matching branch process state, and the latest applicable run.

- Read all bootstrap data in one repeatable-read transaction.
- Resolve state from the selected head or nearest ancestor.
- Return every retained branch while selecting the persisted head.
- Return exact safe text, tool calls/results, artifact data parts, statuses, and metadata; never return DSPy history, reasoning, provider content, exceptions, or filesystem paths.
- Fetch bootstrap once before mounting the keyed runtime. Gate the composer behind loading/error UI.
- Pass bootstrap into `AgentRuntimeProvider`; make the first adapter load resolve from it and return `agentState` through the adapter `state` field.
- Remove late `RestoreAgentState` effects and preserve remount-per-thread isolation. Never nest a cached bootstrap query inside its own query function.

## Public interfaces and compatibility

- `/api/agent` remains AG-UI over SSE with no browser-visible DSPy fields.
- Bootstrap changes from a flat message list to a versioned branch repository.
- Two idempotent history persistence endpoints are added.
- Message IDs are unique per thread while internal row IDs remain globally unique.
- Existing linear threads migrate as one branch and continue from their current DSPy history.
- Keep exact `@assistant-ui/*`, `@ag-ui/*`, and `dspy==3.3.*` pins.

## Test plan

Backend coverage must include duplicate-run races, semaphore saturation, transaction rollback, every terminal outcome, exactly-once terminal events, startup reconciliation, cross-thread source identity, canonical-source dedupe, branch-specific cumulative state, correct edited/regenerated DSPy ancestry, consistent bootstrap snapshots, history sanitization, and migration preservation.

Frontend coverage must include exact append/update round trips, edit-created sibling branches, persisted head navigation, exact tool/artifact restoration, slow-bootstrap race protection, thread isolation, reasoning exclusion, and bootstrap retry UI.

Run:

```text
cd apps/api && uv run alembic upgrade head
cd apps/api && uv run ruff check .
cd apps/api && uv run ruff format --check .
cd apps/api && uv run mypy app
cd apps/api && uv run pytest
pnpm --filter web lint
pnpm --filter web test
pnpm --filter web build
```

Also perform one fresh-browser edit, branch-switch, reload, and thread-switch validation with a clean console. The live DSPy smoke test remains optional and requires an explicitly supplied API key.

## Assumptions

- Full retained branching, exact safe UI restoration, and data-preserving migration are required.
- The existing `plan.md` is preserved.
- The backend remains authoritative for runs, DSPy history, process state, sources, and artifacts; assistant-ui persistence owns only its safe presentation repository.
- A disconnected run is durably cancelled rather than resumed; completed and approval-paused messages use adapter `update` for exact restoration.
