# AGENTS.md

Guidance for coding agents working in this repo.

## Repository

pnpm + uv monorepo:

- `apps/web` — React 19 + Vite frontend (package name `web`)
- `apps/api` — FastAPI backend (uv project, Python 3.13)
- `packages/contracts` — `AgentWorkspaceState` JSON Schema, the single source
  of truth for the public agent-state contract

## Non-negotiables

1. **Chain-of-thought boundary.** Never send raw DSPy `next_thought`,
   `dspy.History`, provider prompts, or stack traces to the browser. The
   process panel renders the intentional, user-safe `AgentWorkspaceState` only.
2. **Contract discipline.** All payloads carry `schemaVersion`. TS types and
   Python models are generated from `packages/contracts/*.schema.json` — never
   commit handwritten duplicates of the state model.
3. **Exact pins** for `@assistant-ui/*`, `@ag-ui/*` (preview versions, churn
   expected) and `dspy==3.3.*` (ReActV2 alias is removed in DSPy 3.6; a rename
   to `dspy.ReAct` is required when upgrading to 3.5).
4. **Exact CORS origins** — no wildcards, configured via
   `FLEET_AGENT_CORS_ORIGINS`.
5. **State ownership.** App/UI state → Zustand/URL/TanStack Query; conversation
   state → assistant-ui (`useAuiState`); agent process state → AG-UI
   (`useAgUiState<AgentWorkspaceState>`). Do not mirror agent state in Zustand.

## Commands

| What            | Command |
| --------------- | ------- |
| Web dev server  | `pnpm dev:web` |
| API dev server  | `pnpm dev:api` |
| Web lint/test/build | `pnpm --filter web lint` / `test` / `build` |
| API lint        | `cd apps/api && uv run ruff check . && uv run ruff format --check .` |
| API typecheck   | `cd apps/api && uv run mypy app` |
| API tests       | `cd apps/api && uv run pytest` |

## Conventions

- Frontend: shadcn/ui **Base UI** flavor (`components.json` style `base-nova`),
  path alias `@/* → src/*`, vitest + testing-library for tests. oxlint excludes
  vendored registry components (`src/components/ui/**`,
  `src/components/assistant-ui/**`) via `.oxlintrc.json`.
- Workspace shell breakpoints: ≥1200px three resizable panes; 768–1199px
  process panel becomes a Sheet; <768px both side panels become Sheets. Panel
  open/tab prefs persist via the `fleet-agent-workspace` zustand key; pane
  sizes persist via `react-resizable-panels` `useDefaultLayout` (per-mode ids).
- Backend: ruff (lint + format), mypy `--strict` with the pydantic plugin,
  pytest + pytest-asyncio (`asyncio_mode = "auto"`). Configuration comes from
  `apps/api/.env` — resolved **absolutely from the app dir** (`_APP_DIR.parent
  / ".env"`), so `uv` invocations from ANY CWD pick it up; env vars still
  override the file, and tests build env-configured apps via
  `make_test_app(**env)` rather than `.env`.
- Contracts: `packages/contracts/agent-workspace-state.schema.json` is the
  source of truth. Regenerate the Python model after schema edits:
  `cd apps/api && uv run datamodel-codegen --input ../../packages/contracts/agent-workspace-state.schema.json --input-file-type jsonschema --output app/contracts/agent_state.py --output-model-type pydantic_v2.BaseModel --target-python-version 3.13 --use-union-operator --use-title-as-name --disable-timestamp --formatters ruff-check ruff-format`
  (a pytest freshness check enforces this; the generated file is lint/typecheck
  exempt — it is not authored code). TS types: `pnpm --filter web contracts:sync`
  regenerates `src/contracts/generated.ts` (a vitest freshness test enforces it;
  `src/contracts/**` is lint-exempt).
- Process panel (PR 4): renders `useAgUiState<AgentWorkspaceState>()` only —
  no message parsing, no Zustand mirror of agent state. Auto-open on the first
  tool call lives in `AgentWorkspace` (the panel is unmounted while closed);
  the once-per-user flag is the persisted `processPanelAutoOpened` store field.
  Base UI composition uses `render={<a/>}` (not Radix `asChild`).
- Mock transport (PR 3): `POST /api/agent` replays NDJSON fixtures from
  `packages/contracts/fixtures/` via `RunCoordinator`; fixture choice is
  keyword-routed from the last user message (`"tool error"` → tool failure +
  recovery, `"no output"` → RUN_ERROR path). Terminal events are emitted
  exactly once; disconnects stop the stream quietly.
- DSPy engine (PR 5): `app/agent/` — routes never import ReActV2 internals;
  they see `AgentEngine.run() -> AgentRunResult` only. `result.history` is
  server-side ONLY (contains raw `next_thought`). Config via
  `FLEET_AGENT_LLM_MODEL` / `FLEET_AGENT_LLM_API_KEY` (SecretStr — never log).
  Native function calling is explicit (`JSONAdapter(use_native_function_calling=True)`).
  Provider-free tests use `tests/helpers/scripted_lm.py` (ScriptedLM emits
  provider-format tool_calls; exceptions on a step raise in-loop). Under
  JSONAdapter + native calling, a content-only/no-tool-calls turn surfaces as
  `parse_error` — `empty_tool_calls` is only reachable with non-native adapters.
  Live provider smoke test: `FLEET_AGENT_LLM_API_KEY=... uv run pytest tests/test_engine_live.py`.
- Live bridge (PR 6): `FLEET_AGENT_AGENT_MODE=engine` switches `POST /api/agent`
  from fixture replay to `LiveDSPyCoordinator`. Structure matches plan.md:
  domain events in `app/contracts/domain.py`; `app/agui/` = event_bus +
  trace_reducer + event_mapper + live_coordinator. Instrumented tools publish
  via `RunEventBus.publish_from_worker` (`loop.call_soon_threadsafe`); per-run
  bus/engine/TraceReducer — nothing shared between runs. Tool args are
  redacted (`key|token|secret|password|auth|credential` → `***`) and previews
  capped (args 400c / state 300c / thread result 2000c). Failures map to public
  codes (`agent_no_output`, `agent_parse_error`, `agent_context_limit`,
  `internal_error`) with safe messages; raw exceptions never leave the backend.
- Persistence (PR 7): SQLAlchemy 2 async + Alembic + asyncpg. Migrations:
  `cd apps/api && uv run alembic upgrade head` (compose Postgres must be up;
  DB-backed tests skip when unreachable). Engine mode requires the run's
  thread to exist (404 otherwise); write path lives in
  `services/run_persistence.py` (runs, user+assistant messages, run_states
  snapshot, `dspy.History` model_dump with schema version + dspy version —
  history is server-side only, never serialized to clients). Restoration on
  the web: remount-per-thread runtime (`key={threadId}`) + isolated history
  adapter module (`features/threads/assistant-thread-adapter.ts`) +
  `RestoreAgentState` seeding the panel snapshot from `bootstrap.agentState`;
  the unstable `threadList` adapter is deliberately NOT used. URL owns active
  project/thread: `/projects/:projectId/threads/:threadId`.
- Sources & artifacts (PR 8): tool contracts in `app/contracts/domain.py`
  (`SourceResult`, `ArtifactResult` + lifecycle events). `SearchDocsTool`/
  `WriteReportTool` are per-run callable objects (explicit `__name__`/`__doc__`).
  Sources dedupe by canonical URI (`_normalize_uri`) or document id. Artifacts:
  per-thread directories, sanitized names, size-capped content,
  `ArtifactStorage` protocol w/ `LocalArtifactStorage` confinement; download
  only `ready` rows via `GET /api/artifacts/{id}` (attachment + nosniff, media
  allowlist) — never filesystem paths in payloads. Retention: delete thread
  → cascade rows + storage folder. Inline: `CUSTOM {name:"artifact"}` →
  `ArtifactDataUIRegistration` in the runtime provider; clicking opens the
  Artifacts tab + selects (transient `selectedArtifactId`, never persisted).
- Hardening (PR 9): public codes in `app/contracts/error_codes.py`. Cancellation:
  disconnect → `bus.cancel_token.cancel()` + engine task cancel + run row
  marked `cancelled` (`run_cancelled`); wrappers check the token before work.
  Timeout bounds the WHOLE run via `asyncio.timeout(run_timeout_s)`, not just
  the post-drain wait. Idempotency: existing runId → 409. Saturated engine
  semaphore → 429. Orphaned runs marked interrupted at startup. Optional
  `FLEET_AGENT_API_KEY` (X-API-Key) + body-size 413 middleware. MetricsRegistry
  is per-process JSON on `/metrics`. Env-configured tests MUST use
  `make_test_app(**env)` — middleware/semaphore read settings at construction.
  Concurrency/streaming tests need real sockets: `live_server_factory` —
  ASGITransport serializes streams.
- Live-integration fixes (post-PR 9, each found in-browser): bind
  `agent.threadId` to the URL thread (else engine 404s); server-generate
  message-row ids (client ids collide across turns); sources dedup with
  `ON CONFLICT DO NOTHING` (re-discovery violated PK);
  **`getThreadBootstrap`/TanStack `fetchQuery` must NEVER wrap another queryFn
  sharing the same queryKey** — it deadlocked "Loading conversation" forever;
  `RestoreAgentState` uses the RAW `fetchBootstrap`, adapter keeps the cache.
- Keep changes minimal and scoped to the PR sequence in `README.md`.
