# @fleet-agent/contracts

Single source of truth for the public protocol between the FastAPI backend and
the React frontend.

## Contents

- `agent-workspace-state.schema.json` — `AgentWorkspaceState` v1, the user-safe
  process state streamed via AG-UI `STATE_SNAPSHOT` / `STATE_DELTA`.
- `fixtures/` (added with the mock transport PR) — canonical NDJSON AG-UI
  event streams for replay and contract tests.

## Rules

1. `schemaVersion` travels in every payload. Any breaking shape change
   increments it; older versions must fail clearly, never silently misparse.
2. TypeScript types (`apps/web/src/contracts/generated.ts`) and Python models
   (`apps/api/app/contracts/`) are **generated from the schema** — never
   handwritten and committed alongside it.
3. No fixture or payload may contain raw chain-of-thought (`next_thought`),
   provider prompts, stack traces, or unredacted tool payloads. CI enforces
   this (contract tests, PR 3).

## Migration policy

Breaking change → new `schemaVersion`, old schema file kept for one release,
backend validates and negotiates. Non-breaking additions (new optional fields)
keep the version.
