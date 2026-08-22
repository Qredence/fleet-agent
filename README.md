# fleet-agent

Three-pane agent workspace: assistant-ui conversation (center), projects/threads
sidebar (left), and a live AG-UI agent-state **Process panel** (right), backed by
FastAPI + DSPy ReActV2.

## Stack

| Layer    | Tech |
| -------- | ---- |
| Frontend | React 19, TypeScript, Vite, shadcn/ui (Base UI), assistant-ui + `@assistant-ui/react-ag-ui`, TanStack Query, Zustand |
| Backend  | Python 3.13, FastAPI, AG-UI protocol (`ag-ui-protocol`), SSE |
| Agent    | DSPy ReActV2 (OpenAI, `dspy==3.3.*` pinned) |
| Contracts| JSON Schema in `packages/contracts` (single source of truth) |

## Repo layout

```
apps/
  web/          React frontend (Vite)
  api/          FastAPI backend (uv)
packages/
  contracts/    AgentWorkspaceState JSON Schema + fixtures
compose.yaml    local Postgres (used from PR 7)
```

## Develop

Requirements: Node ≥ 22, pnpm 11, uv, Docker.

```bash
# configuration (git-ignored; examples are committed)
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env

# database (required since PR 7)
docker compose up -d postgres
cd apps/api && uv run alembic upgrade head

# frontend (http://localhost:5173)
pnpm dev:web

# backend (http://localhost:8000)
pnpm dev:api
```

Backend config: `apps/api/.env` (resolved absolutely, so any CWD works) with
`FLEET_AGENT_`-prefixed vars. Frontend config: `apps/web/.env` (Vite loads it
automatically) with `VITE_`-prefixed vars.

## Checks

```bash
pnpm --filter web lint && pnpm --filter web test && pnpm --filter web build
cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
```

CI runs the same checks (`.github/workflows/ci.yml`).

## Deployment

- Migrations: `cd apps/api && uv run alembic upgrade head` before starting workers.
- SSE: disable proxy buffering (`X-Accel-Buffering: no` already set); allow long
  ingress timeouts for agent runs; drain with `uvicorn --timeout-graceful-shutdown`.
- Auth: `FLEET_AGENT_API_KEY` enforces `X-API-Key` on `/api/*` (unset = open local mode,
  startup logs a warning). Frontend pairs it via `VITE_API_KEY`.
- Caps: `FLEET_AGENT_MAX_CONCURRENT_RUNS` (429 when saturated),
  `FLEET_AGENT_RUN_TIMEOUT_SECONDS`, `FLEET_AGENT_MAX_BODY_BYTES` (413).
- Restart safety: orphaned `running` runs are marked interrupted at startup.
- Horizontal scale-out needs a shared run/event backend before multiple workers
  (`run_semaphore` and metrics are per-process — do not split traffic until then).

## Observability

- `X-Request-Id` on every response; correlation in logs via `request_id` plus
  run/thread ids in coordinator messages.
- `GET /metrics` → JSON counters/gauges/durations
  (`agent_runs_total`, `agent_run_errors_total`, `agent_tool_calls_total`,
  `agent_tool_errors_total`, `agent_run_duration_ms`, `agent_tool_duration_ms`,
  `active_sse_connections`).
- Load harness: `cd apps/api && uv run python scripts/load_sse.py --connections 20 --requests 2`
  (fixtures mode; reports p50/p95 for RUN_STARTED → first delta → first tool → terminal).

## PR sequence

1. **PR 1 — Workspace scaffolding** ✅
2. **PR 2 — Three-pane shell** ✅ (resizable panels, responsive sheets, persisted layout)
3. **PR 3 — AG-UI mock transport** ✅ (SSE endpoint replays fixture streams; live Thread)
4. **PR 4 — Agent state panel** ✅ (live `AgentWorkspaceState` in Activity/Sources/Artifacts)
5. **PR 5 — DSPy engine** ✅ (ReActV2 behind `AgentEngine`, OpenAI, signature + termination mapping)
6. **PR 6 — Tool instrumentation** ✅ (live DSPy→AG-UI bridge: RunEventBus, instrumented tools, TraceReducer)
7. **PR 7 — Persistence and threads** ✅ (Postgres + Alembic, projects/threads/messages/runs, DSPy history, restoration)
8. **PR 8 — Sources and artifacts** ✅ (SourceResult + dedup, artifact lifecycle + storage, inline CUSTOM renderer, retention)
9. **PR 9 — Hardening** ✅ (cancellation semantics, error taxonomy, concurrency limits, correlation IDs, metrics, load harness)

Slice gate: no DSPy until a mocked AG-UI run drives both panes (end of PR 4).
