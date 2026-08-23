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
   to `dspy.ReAct` is required when upgrading past 3.5).
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
| Migrations      | `cd apps/api && uv run alembic upgrade head` (compose Postgres up) |

## Frontend

- shadcn/ui **Base UI** flavor (`components.json` style `base-nova`), path
  alias `@/* → src/*`, vitest + testing-library. Composition uses
  `render={<a/>}`, never Radix `asChild`. oxlint excludes vendored components
  (`src/components/ui/**`, `src/components/assistant-ui/**`) via `.oxlintrc.json`.
- Workspace breakpoints: ≥1200px three resizable panes; 768–1199px process
  panel becomes a Sheet; <768px both side panels become Sheets. Panel open/tab
  prefs persist via the `fleet-agent-workspace` zustand key; pane sizes via
  `react-resizable-panels` `useDefaultLayout` (per-mode ids).
- URL owns active project/thread: `/projects/:projectId/threads/:threadId`.
- Sidebar (Codex-style, vendored kit `components/ui/sidebar.tsx`): one
  collapsible `SidebarMenuItem` per project with a thread-count badge; only the
  active project's group starts expanded (transient, never persisted); thread
  lists cap at 5 behind a Show more/less expander; current thread row gets
  `data-active` + `aria-current="page"`. Project-row hover reveals `+` (new
  thread in that project) and a `…` menu (rename/delete dialogs); the
  "Projects" label carries a create-with-name `+`. The kit's provider is LOCAL
  to the sidebar (`persistState=false`, `enableKeyboardShortcut=false`,
  `collapsible="none"`) — panel open/collapse ownership stays with the
  workspace shell.
- Process panel renders `useAgUiState<AgentWorkspaceState>()` only — no message
  parsing, no Zustand mirror. Auto-open on first tool call lives in
  `AgentWorkspace` (panel unmounted while closed); flag persisted as
  `processPanelAutoOpened`.
- Thread restoration: the route fetches one versioned bootstrap snapshot before
  mounting the keyed runtime (`key={threadId}`). `AgentRuntimeProvider` passes
  it to the serialized history adapter, which restores the branch repository and
  returns the safe `agentState` through adapter state. `HistoryHeadSync` persists
  the selected branch head. The unstable `threadList` adapter and late restore
  effects are deliberately NOT used. Adapter fallback loads
  call raw `fetchBootstrap`; they never nest a cached bootstrap query.

## Backend

- ruff (lint + format), mypy `--strict` with the pydantic plugin, pytest +
  pytest-asyncio (`asyncio_mode = "auto"`).
- Config comes from `apps/api/.env`, resolved absolutely from the app dir (any
  CWD works); env vars override the file. Tests build env-configured apps via
  `make_test_app(**env)` — never `.env` (middleware/semaphore read settings at
  construction).
- Streaming/concurrency tests need real sockets: `live_server_factory`
  (ASGITransport serializes streams).

## Contracts

- Source of truth: `packages/contracts/agent-workspace-state.schema.json`.
- Python model regen after schema edits:
  `cd apps/api && uv run datamodel-codegen --input ../../packages/contracts/agent-workspace-state.schema.json --input-file-type jsonschema --output app/contracts/agent_state.py --output-model-type pydantic_v2.BaseModel --target-python-version 3.13 --use-union-operator --use-title-as-name --disable-timestamp --formatters ruff-check ruff-format`
- TS types: `pnpm --filter web contracts:sync` → `src/contracts/generated.ts`.
- Freshness tests enforce both; generated files are lint/typecheck exempt
  (not authored code).

## Agent pipeline

- **Mock mode:** `POST /api/agent` replays NDJSON fixtures from
  `packages/contracts/fixtures/` via `RunCoordinator`, keyword-routed from the
  last user message (`"tool error"` → failure+recovery, `"no output"` →
  RUN_ERROR). Terminal events emitted exactly once; disconnects stop quietly.
- **Engine mode** (`FLEET_AGENT_AGENT_MODE=engine`): `LiveDSPyCoordinator`.
  Domain events in `app/contracts/domain.py`; `app/agui/` = event_bus +
  trace_reducer + event_mapper + live_coordinator. Per-run bus/engine/reducer —
  nothing shared between runs. Tool args redacted
  (`key|token|secret|password|auth|credential` → `***`), previews capped
  (args 400c / state 300c / result 2000c). Failures map to public codes
  (`agent_no_output`, `agent_parse_error`, `agent_context_limit`,
  `internal_error`) with safe messages — raw exceptions never leave the backend.
- **Persistence:** SQLAlchemy 2 async + Alembic + asyncpg. Engine mode requires
  the run's thread to exist (404 otherwise). Write path in
  `services/run_persistence.py` uses short transaction-bound sessions for
  branch-aware messages, runs, per-head process snapshots, and versioned
  DSPy histories; terminal transitions are idempotent and advance heads with
  compare-and-set. Bootstrap is one repeatable-read, `schemaVersion`-tagged
  safe snapshot. Sources dedupe by canonical URI or document id
  (`ON CONFLICT DO NOTHING`). Artifacts: per-thread dirs, sanitized names, size
  caps, `ArtifactStorage` protocol w/ confined `LocalArtifactStorage`; download
  only `ready` rows via `GET /api/artifacts/{id}` (attachment + nosniff + media
  allowlist) — never filesystem paths in payloads. Thread deletion cascades
  rows + storage folder.
- **Hardening:** public codes in `app/contracts/error_codes.py`. Disconnect →
  cancel token + engine task cancel + run marked `cancelled`; wrappers check
  the token before work. `asyncio.timeout(run_timeout_s)` bounds the WHOLE run.
  Every accepted engine stream emits at most one safe terminal event, including
  settlement failures. Existing runId → 409; saturated semaphore → 429;
  orphaned runs marked interrupted at startup. Optional
  `FLEET_AGENT_API_KEY` (X-API-Key) + 413 body-size middleware. MetricsRegistry:
  per-process JSON on `/metrics`.

## DSPy engine (`app/agent/`)

- Routes never import ReActV2 internals; they see `AgentEngine.run() ->
  AgentRunResult` only. `result.history` contains raw `next_thought` —
  server-side only.
- Config: `FLEET_AGENT_LLM_MODEL` / `FLEET_AGENT_LLM_API_KEY` (SecretStr —
  never log). Native function calling is explicit
  (`JSONAdapter(use_native_function_calling=True)`); under it, a content-only
  turn surfaces as `parse_error` (`empty_tool_calls` needs non-native adapters).
- Invariants pinned by `tests/test_dspy_contract.py` (re-audit on any dspy
  bump): `dspy.ReActV2` is the 3.3 loop (distinct from legacy `dspy.ReAct`);
  tools are synchronous callables with typed hints; `instrument_tool` propagates
  `__annotations__` (`functools.wraps` does not) — wrapping without it degrades
  schemas to `Any` and disables arg validation; only scoped `dspy.context(...)`
  (never `dspy.configure`); LM knobs live on `dspy.LM`; usage requires
  `track_usage=True`; persistence is `History.model_dump` + version columns,
  never `Module.save`/`dspy.load`; the `AgentSignature` docstring IS the
  instructions and output-field order defines the built-in `submit` tool's
  schema; re-check the termination-reason map on upgrades.
- Provider-free tests: `tests/helpers/scripted_lm.py`. Live smoke test:
  `FLEET_AGENT_LLM_API_KEY=... uv run pytest tests/test_engine_live.py`.

## Gotchas (each found in-browser)

- Bind `agent.threadId` to the URL thread — else engine calls 404.
- Server-generate message-row ids — client ids collide across turns.
- Bootstrap query functions must use raw `fetchBootstrap`; never wrap a cached
  bootstrap query (`queryClient.fetchQuery`) inside another queryFn sharing the
  same queryKey — it deadlocks "Loading conversation" forever.

Keep changes minimal and scoped to the PR sequence in `README.md`.
