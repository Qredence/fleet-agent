# Spec 001 - Run outcome and durability

Status: implemented; browser release acceptance pending. Implementation baseline: `a6197e4`; original review baseline: `8b87caf`.

## Implementation delivered

Workspace state and bootstrap use version 2. Save status is independent of execution status. Terminal writes retry once, persist saved snapshots only within the committed terminal transaction, and publish save failure while retaining the answer. Accepted settlement survives disconnect for a bounded interval. Runtime assistant messages cannot be overwritten by frontend history writes; pending branches cannot advance. Legacy snapshots infer saved only from matching terminal records. Copy and local Markdown download are available after save failure.

See [implementation status and validation](implementation-status-2026-10-09.md) for commands, measurements and remaining checks. The original proposal below explains the design; the delivered behavior above records the current implementation.

Specification index | Review pages

## Original problem and baseline behavior

A completed answer can be streamed even when both terminal persistence attempts fail. The coordinator logs the failure and emits `RunFinishedEvent`. Execution completion and durable save success are not the same guarantee.

Source: live_coordinator.py, successful terminal branch; run_persistence.py.

## Desired behavior

Keep useful streaming output visible. Explicitly distinguish the execution outcome from whether that output was saved. Show "Saved" only after the terminal transaction commits. A failed save must remain visible in the current browser session, with an explanation that reload may not recover the answer.

## Invariants

- Exactly one logical terminal transition is accepted for a run; repeated settlement cannot produce duplicate assistant messages or artifacts.

- Public output remains scrubbed. Never expose driver errors, provider payloads or private history.

- A successful stream is not described as durable until persistence succeeds.

- A save failure does not erase already delivered useful text or trigger an automatic re-execution of mutating tools.

- Closing a connection retains the explicitly documented cancel-on-disconnect behavior for this slice.

## Contract and migration

Propose a shared versioned run field `saveStatus: pending | saved | failed`, independent from the existing execution status. Define a stable public save-failure code. Decide the version increment in the schema PR; version-1 records require an explicit normalization/migration path because the existing schema forbids unknown properties.

Use the existing AG-UI state snapshot/delta and terminal events. Do not invent a parallel transport. The persisted terminal state may contain its intended saved value inside the transaction, but the client receives that value only after commit succeeds. On commit failure, emit a safe unsaved state for the current session.

## Backend and frontend

Extract only enough settlement policy to test it independently from SSE serialization. Keep the existing short transactions and branch/message identifiers. The frontend run banner must distinguish working, execution complete, and save failure, while retaining copy/download access to the visible answer where safe.

## DSPy, MLflow and fixtures

No DSPy optimization is needed. Record sanitized settlement outcome/count metrics; MLflow availability must not affect settlement. Add deterministic fixtures for successful save, retry success, both retries failing and cancellation during save.

## Acceptance tests

- Successful commit produces one saved answer and the same answer after reload.

- First persistence attempt fails, second succeeds: no duplicate message and no false permanent failure.

- Both attempts fail: answer remains visible, UI says not saved, and bootstrap does not invent a persisted answer.

- Duplicate finalization and disconnect races produce no contradictory saved/failed states.

- A save retry never reruns the DSPy program or a workspace mutation.

- Old snapshots normalize predictably; live and restored terminal state agree whenever a terminal transaction succeeded.

## Non-goals

No background-job platform, token-by-token event log, unbounded retry queue, or promise to recover data that was never saved.
