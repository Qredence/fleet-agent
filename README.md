# Fleet Agent

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/Qredence/fleet-agent/tree/main.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/Qredence/fleet-agent/tree/main)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Fleet Agent is a three-pane workspace for agent conversations and user-safe
process visibility. It combines an assistant-ui conversation, project and
thread navigation, and a live AG-UI Process panel backed by FastAPI and DSPy.

> **Status:** early-stage, pre-release software. The current application is
> designed for a single local owner. It is not a complete multi-user identity
> or authorization system.

## What it includes

- A responsive workspace with project/thread navigation, assistant-ui chat,
  and Activity, Sources, Artifacts, and Decisions views.
- AG-UI over server-sent events (SSE), with fixture streams for deterministic
  local development and CI.
- A DSPy ReActV2 engine behind a small `AgentEngine` boundary for provider-backed
  runs.
- PostgreSQL persistence for projects, threads, messages, runs, branch-aware
  history, sources, artifacts, and safe process snapshots.
- A versioned JSON Schema contract in `packages/contracts`, used to generate
  the TypeScript and Python state models.
- A deliberate chain-of-thought boundary: raw DSPy thoughts, provider prompts,
  stack traces, and unredacted tool payloads stay server-side.

## Architecture

```text
┌──────────────────┬───────────────────────────────┬────────────────────────┐
│ Projects/Threads │ Conversation                 │ Process panel          │
│                  │                               │                        │
│ Project A        │ assistant-ui messages         │ Activity               │
│  ├ Thread 1      │ user-visible answers          │ Sources                │
│  ├ Thread 2      │ attachments and tool output   │ Artifacts              │
│  └ New thread    │                               │ Decisions              │
└──────────────────┴───────────────────────────────┴────────────────────────┘
```

The frontend lives in `apps/web`, the FastAPI backend in `apps/api`, and the
public `AgentWorkspaceState` contract and deterministic fixtures live in
`packages/contracts`. PostgreSQL is provided for local development by
`compose.yaml`.

## Requirements

- Node.js 22 or newer
- pnpm 11.15.1
- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)
- Docker with Docker Compose

The repository pins the workspace package manager in `package.json` and the
Python dependencies in `apps/api/uv.lock`.

## Quick start

From the repository root:

```bash
pnpm install
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env

docker compose up -d postgres

cd apps/api
uv sync --locked --all-groups
uv run alembic upgrade head
```

Start the services in separate terminals from the repository root:

```bash
# terminal 1 — API at http://localhost:8000
pnpm dev:api

# terminal 2 — web app at http://localhost:5173
pnpm dev:web
```

Open <http://localhost:5173>. The default `fixtures` mode does not require an
LLM provider key, but PostgreSQL is still required because the API initializes
its persistence layer at startup.

The FastAPI interactive documentation is available at
<http://localhost:8000/docs>. Liveness and readiness checks are available at
`/health` and `/ready`.

## Agent modes

The backend supports two modes through `FLEET_AGENT_AGENT_MODE`:

- `fixtures` (default) replays canonical NDJSON streams from
  `packages/contracts/fixtures`. It is deterministic and provider-free.
- `engine` runs the live DSPy ReActV2 bridge. It requires
  `FLEET_AGENT_LLM_API_KEY` and may use an OpenAI-compatible endpoint through
  `FLEET_AGENT_LLM_BASE_URL`.

To try engine mode, set the following in `apps/api/.env`, then restart the API:

```dotenv
FLEET_AGENT_AGENT_MODE=engine
FLEET_AGENT_LLM_MODEL=openai/gpt-4o-mini
FLEET_AGENT_LLM_API_KEY=replace-me
# Optional OpenAI-compatible endpoint:
# FLEET_AGENT_LLM_BASE_URL=https://your-provider.example/v1
```

Never commit `.env` files or provider keys. The checked-in `.env.example`
files contain configuration examples only.

## Configuration

The API reads `apps/api/.env` using an absolute path derived from the app
location, so its behavior does not depend on the current working directory.
Environment variables override values from that file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FLEET_AGENT_ENVIRONMENT` | `development` | Environment label. |
| `FLEET_AGENT_ENV_FILE` | `apps/api/.env` | Optional settings-file path override for the API. |
| `FLEET_AGENT_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON array of exact allowed browser origins; wildcards are not supported. |
| `FLEET_AGENT_CORS_ALLOW_CREDENTIALS` | `true` | Whether CORS credentials are allowed. |
| `FLEET_AGENT_AGENT_MODE` | `fixtures` | `fixtures` or `engine`. |
| `FLEET_AGENT_DATABASE_URL` | `postgresql+asyncpg://fleet:fleet@localhost:5432/fleet_agent` | SQLAlchemy async database URL. |
| `FLEET_AGENT_LLM_MODEL` | `openai/gpt-4o-mini` | DSPy/LiteLLM model identifier. |
| `FLEET_AGENT_LLM_BASE_URL` | unset | Optional OpenAI-compatible provider endpoint. |
| `FLEET_AGENT_LLM_API_KEY` | unset | Provider credential; never logged or returned by the API. |
| `FLEET_AGENT_LLM_MAX_ITERS` | `6` | Maximum ReActV2 loop iterations, from 1 to 25. |
| `FLEET_AGENT_LLM_TEMPERATURE` | `0.2` | Provider sampling temperature, from 0 to 2. |
| `FLEET_AGENT_ARTIFACTS_DIR` | `.artifacts` | Local artifact storage directory. |
| `FLEET_AGENT_ARTIFACT_MAX_BYTES` | `65536` | Maximum stored artifact size. |
| `FLEET_AGENT_RUN_TIMEOUT_SECONDS` | `300` | Whole-run timeout. |
| `FLEET_AGENT_MAX_CONCURRENT_RUNS` | `4` | Per-process engine run limit. |
| `FLEET_AGENT_MAX_BODY_BYTES` | `1048576` | Request body limit; oversized requests return 413. |
| `FLEET_AGENT_API_KEY` | unset | Shared `X-API-Key` required for `/api/*` when configured. |

The web app reads:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | API origin used by the browser. |
| `VITE_API_KEY` | unset | Sends `X-API-Key` when the API key is enabled. |

`VITE_*` values are bundled into the frontend and are therefore visible to
browser users. `VITE_API_KEY` is a shared deployment credential, not a secret
user authentication mechanism. Do not use it as a substitute for real
identity and authorization in a shared deployment.

## Persistence and runtime behavior

Engine mode persists projects, threads, safe assistant-ui messages, runs,
branch-aware history, sources, artifacts, and public process snapshots. Apply
the latest Alembic migration before starting engine workers:

```bash
cd apps/api
uv run alembic upgrade head
```

Thread restoration is served by a versioned bootstrap snapshot at
`GET /api/threads/{thread_id}/bootstrap`. Assistant-ui presentation history is
written through idempotent message and branch-head endpoints. DSPy history and
internal reasoning never cross the API boundary.

Artifacts are served through controlled API download URLs. The default local
storage is suitable for development only. A shared production deployment
should provide durable storage behind the existing storage boundary and should
not expose the local artifact directory directly.

## Security and deployment notes

- Set `FLEET_AGENT_API_KEY` for any shared deployment. When it is unset, the
  API intentionally runs in open local mode and logs a warning.
- Keep `FLEET_AGENT_CORS_ORIGINS` limited to exact trusted origins.
- Put the API behind a network boundary and real user authentication before
  exposing it to untrusted users. Current project and thread ownership is the
  single local owner `local`.
- Preserve SSE streaming by disabling proxy buffering and allowing sufficiently
  long ingress timeouts. `X-Accel-Buffering: no` is sent by the API.
- Use a graceful shutdown strategy so open agent streams can drain.
- `run_semaphore` and metrics are per-process. Do not split traffic across
  multiple workers until a shared run/event backend is in place.
- Keep provider prompts, API keys, raw reasoning, stack traces, and private
  user data out of issues, fixtures, screenshots, and pull requests.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Development checks

Web checks:

```bash
pnpm --filter web lint
pnpm --filter web test
pnpm --filter web build
```

API checks:

```bash
cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

Contract types are generated from
`packages/contracts/agent-workspace-state.schema.json`. After changing the
schema, regenerate the TypeScript and Python models using the commands in
[`CONTRIBUTING.md`](CONTRIBUTING.md), then run the contract freshness tests.

For deterministic browser validation, start both services in fixture mode and
run:

```bash
bash scripts/e2e-fixtures.sh
```

The engine browser matrix in `scripts/e2e-engine.sh` requires a configured
provider and should only be run against a safe test environment.

## Repository map

```text
apps/
  api/          FastAPI backend, DSPy engine, persistence, migrations, tests
  web/          React 19 frontend and browser tests
packages/
  contracts/    JSON Schema and canonical AG-UI fixtures
.circleci/      Canonical CI configuration
.github/        Issue, pull-request, funding, and community configuration
compose.yaml    Local PostgreSQL service
AGENTS.md       Engineering invariants for contributors and coding agents
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Community

- [Discussions](https://github.com/Qredence/fleet-agent/discussions) — usage
  questions, ideas, and general project conversation.
- [Issues](https://github.com/Qredence/fleet-agent/issues) — reproducible bugs
  and scoped feature requests.
- [Support policy](SUPPORT.md) — how to choose the right channel.
- [Security policy](SECURITY.md) — private vulnerability reporting.
- [Code of Conduct](CODE_OF_CONDUCT.md)

## License

Fleet Agent is released under the [MIT License](LICENSE).
