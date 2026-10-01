# @fleet-agent/contracts

Single source of truth for the public protocol between the FastAPI backend and
the React frontend.

## Contents

- `agent-capabilities.schema.json` — active server run mode returned by
  authenticated `GET /api/agent/capabilities`.
- `agent-workspace-state.schema.json` — `AgentWorkspaceState` v1, the user-safe
  process state streamed via AG-UI `STATE_SNAPSHOT` / `STATE_DELTA`.
- `thread-bootstrap.schema.json` — `ThreadBootstrap` v1, the
  `GET /api/threads/{id}/bootstrap` restoration envelope.
- `error-codes.json` — stable public error codes and their safe messages.
  The backend loads it at import (`app/contracts/error_codes.py`); the web
  imports it directly where codes are rendered.
- `termination-reasons.json` — the canonical public run termination reasons.
  The backend derives its safe-set filtering from it; the web's presentation
  labels are pinned to it by a contract test.
- `provider.json` — BYOK provider endpoints and the wire-format selections
  (`responseFormats`, `messagesFormats`) shared by the browser settings UI and
  the server-side header parsing.
- `fixtures/` — canonical NDJSON AG-UI event streams for replay and contract
  tests.

## Rules

1. `schemaVersion` travels in every versioned payload. Any breaking shape
   change increments it; older versions must fail clearly, never silently
   misparse.
2. TypeScript types (`apps/web/src/contracts/`) and Python models
   (`apps/api/app/contracts/`) are **generated from the schemas** — never
   handwritten and committed alongside them. Constant lists
   (`error-codes.json`, `termination-reasons.json`, `provider.json`) are
   consumed directly or pinned by contract tests instead of being copied.
3. No fixture or payload may contain raw chain-of-thought (`next_thought`),
   provider prompts, stack traces, or unredacted tool payloads. CI enforces
   this (contract tests).

## Migration policy

Breaking change → new `schemaVersion`, old schema file kept for one release,
backend validates and negotiates. Non-breaking additions (new optional fields)
keep the version.
