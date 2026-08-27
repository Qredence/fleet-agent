# Fleet Agent

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/Qredence/fleet-agent/tree/main.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/Qredence/fleet-agent/tree/main)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Fleet Agent is an experimental agent workbench built around **DSPy**. Its
purpose is to make multi-step agent work useful, inspectable, and recoverable:
the user gets a direct answer while the workspace keeps the relevant process
state, tool activity, evidence, decisions, and generated artifacts available.

> Early-stage, pre-release software. The current application has a single
> local owner; it is not a complete multi-user identity or authorization
> system.

## Why Fleet Agent exists

Most agent interfaces show a conversation and hide the work behind it. Fleet
Agent treats the agent run as a first-class part of the product. A request
belongs to a project and thread, the DSPy agent can use bounded typed tools,
and the user can inspect what happened without receiving hidden model reasoning.

DSPy is the core reasoning framework. In engine mode, `dspy.ReActV2` receives
the user request and persisted branch history, chooses tools, and produces
explicit user-facing fields:

- a direct answer;
- a concise process summary;
- important decisions; and
- remaining caveats or uncertainty.

The FastAPI backend wraps DSPy behind an `AgentEngine` boundary, coordinates
the run, persists the safe result, and translates callbacks into AG-UI events.
The React frontend renders the conversation and the live process projection.

## Core features

### DSPy-powered agent execution

- ReActV2 is the default live agent loop, with provider configuration kept in
  one server-side boundary.
- An optional staged strategy uses DSPy modules for planning, parallel
  research, verification, and synthesis while keeping budgets and cancellation
  outside the model.
- The agent uses typed tools such as bundled documentation search, current
  time, and report generation. Optional Tavily configuration adds bounded
  `web_search` and `fetch_page` tools.
- OpenAI-compatible model endpoints are supported through the configured DSPy
  model and base URL.

### Evidence and artifacts

- Tool calls expose bounded status, inputs, outputs, and failures.
- Sources discovered during a run appear in the Sources view.
- `write_report` produces a sanitized, size-capped Markdown artifact with a
  controlled API download URL.
- The process state includes decisions, caveats, run status, and run metrics
  without exposing raw provider payloads.

### A persistent agent workspace

- Projects organize threads; the URL identifies the active project and thread.
- Conversation messages, branch heads, safe process snapshots, sources, runs,
  and artifacts persist in PostgreSQL.
- Reloading a thread restores its versioned bootstrap snapshot and branch-aware
  conversation history.
- The responsive three-pane UI combines project/thread navigation, an
  assistant-ui conversation with inline collapsible run activity, and an AG-UI
  process panel with Sources and Artifacts tabs plus file exploration.
- Frontend components use `@base-ui/react` primitives and Fluid Functionalism
  design tokens, adhering to CSS logical properties for bidirectional (RTL)
  layout support.

### Deterministic development and safe boundaries

- Fixture mode replays canonical AG-UI streams without an LLM provider, making
  local development and CI reproducible.
- Engine mode uses the live DSPy bridge for provider-backed runs.
- The public `AgentWorkspaceState` JSON Schema is the shared contract between
  backend and frontend.
- Raw `next_thought`, DSPy history, provider prompts, credentials, stack traces,
  and unredacted tool payloads remain server-side.
- Tool arguments and previews are bounded, public failures use safe error
  codes, and CORS accepts exact configured origins only.

## How the pieces fit together

```text
React workspace
  assistant-ui conversation + AG-UI process panel
                │ REST + SSE
                ▼
FastAPI run coordinator
  AgentEngine boundary + persistence + public-state reducer
                │
                ├── DSPy ReActV2 / optional staged strategy
                ├── typed tools and evidence sources
                └── PostgreSQL + controlled artifact storage
```

The browser never needs to understand DSPy internals. It consumes ordinary
conversation data plus `AgentWorkspaceState` snapshots and deltas, while the
server retains the model history needed for continuation.

## Repository map

```text
apps/web/          React 19 + Vite workspace and browser tests
apps/api/          FastAPI API, DSPy engine, AG-UI bridge, persistence, migrations
packages/contracts Public agent-state schema and deterministic fixtures
compose.yaml       Local PostgreSQL service
```

## Requirements

- Node.js 22+
- pnpm 11.15.1
- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Docker with Docker Compose

The package manager and Python dependencies are pinned in `package.json` and
`apps/api/uv.lock`.

## Quick start

From the repository root, install dependencies and prepare PostgreSQL:

```bash
pnpm install
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env

docker compose up -d postgres

cd apps/api
uv sync --locked --all-groups
uv run alembic upgrade head
```

Start the services in separate terminals:

```bash
# API — http://localhost:8000
pnpm dev:api
```

```bash
# Web — http://localhost:5173
pnpm dev:web
```

Open <http://localhost:5173>. The API docs are at
<http://localhost:8000/docs>; health checks are available at `/health` and
`/ready`.

If the API uses another port, set the matching browser origin before starting
Vite, for example:

```bash
pnpm dev:api -- --port 8001
VITE_API_BASE_URL=http://localhost:8001 pnpm dev:web
```

If the web app uses a different origin or port, add that exact origin to
`FLEET_AGENT_CORS_ORIGINS` in `apps/api/.env`. Wildcard CORS is not supported.

## Agent modes and configuration

The API defaults to deterministic fixture mode:

- `fixtures` replays canonical streams from `packages/contracts/fixtures` and
  does not need an LLM provider key.
- `engine` runs the live DSPy ReActV2 bridge and requires a configured provider.

To use engine mode, edit `apps/api/.env` and restart the API:

```dotenv
FLEET_AGENT_AGENT_MODE=engine
FLEET_AGENT_LLM_MODEL=openai/gpt-4o-mini
FLEET_AGENT_LLM_API_KEY=replace-me
# Optional OpenAI-compatible endpoint:
# FLEET_AGENT_LLM_BASE_URL=https://your-provider.example/v1
# Optional web tools:
# FLEET_AGENT_TAVILY_API_KEY=replace-me
```

API settings load from `apps/api/.env`; environment variables override that
file. The checked-in example contains the complete list. Common settings are:

| Variable | Purpose |
| --- | --- |
| `FLEET_AGENT_AGENT_MODE` | `fixtures` or `engine`. |
| `FLEET_AGENT_REASONING_PROGRAM` | `react` or opt-in `staged` reasoning. |
| `FLEET_AGENT_CORS_ORIGINS` | JSON array of exact allowed browser origins. |
| `FLEET_AGENT_DATABASE_URL` | PostgreSQL connection URL. |
| `FLEET_AGENT_LLM_MODEL` | DSPy/LiteLLM model identifier. |
| `FLEET_AGENT_LLM_BASE_URL` | Optional OpenAI-compatible provider endpoint. |
| `FLEET_AGENT_LLM_API_KEY` | Provider credential; never log it. |
| `FLEET_AGENT_TAVILY_API_KEY` | Enables bounded web search and page fetch tools. |
| `FLEET_AGENT_API_KEY` | Optional shared `X-API-Key` for `/api/*`. |

The web app reads `VITE_API_BASE_URL` for the API origin and `VITE_API_KEY` when
the API requires a shared key. `VITE_*` values are bundled into the browser;
`VITE_API_KEY` is not a substitute for user authentication.

PostgreSQL is required in both modes because the API initializes its
persistence layer at startup. Never commit `.env` files or provider keys.

## Development checks

Web:

```bash
pnpm --filter web lint
pnpm --filter web test
pnpm --filter web build
```

API:

```bash
cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

For deterministic browser coverage, start PostgreSQL and both services in
fixture mode, then run:

```bash
bash scripts/e2e-fixtures.sh
```

The engine flow in `scripts/e2e-engine.sh` needs provider credentials and a
safe test environment.

## Contracts, persistence, and security

`packages/contracts/agent-workspace-state.schema.json` is the source of truth
for the public agent-state contract. After changing it, regenerate the
TypeScript and Python models and run the freshness tests. The exact commands
are in [CONTRIBUTING.md](CONTRIBUTING.md).

Engine mode persists projects, threads, safe messages, runs, branch-aware
history, sources, artifacts, and public process snapshots. Thread restoration
uses the versioned bootstrap endpoint
`GET /api/threads/{thread_id}/bootstrap`. DSPy history and internal reasoning
never cross the API boundary. Artifacts are downloaded through controlled API
URLs; do not expose the local artifact directory directly.

Keep pull requests small and focused. Read [AGENTS.md](AGENTS.md) for
engineering boundaries and [CONTRIBUTING.md](CONTRIBUTING.md) for contract,
migration, validation, and review guidance. Report vulnerabilities privately
using [SECURITY.md](SECURITY.md).

Fleet Agent is released under the [MIT License](LICENSE).
