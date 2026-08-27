# AGENTS.md

Working guidance for contributors and coding agents in Fleet Agent. Keep
changes focused, preserve unrelated work, and do not commit, push, open pull
requests, deploy, or make other remote changes unless explicitly requested.

## Project map

- `apps/web` — React 19 + Vite UI, assistant-ui integration, and browser tests.
- `apps/api` — FastAPI routes, AG-UI streaming, DSPy engine, persistence,
  migrations, and API tests.
- `packages/contracts` — the public `AgentWorkspaceState` JSON Schema and
  deterministic AG-UI fixtures.
- `compose.yaml` — local PostgreSQL service.

## Non-negotiable boundaries

- Never send raw DSPy `next_thought`, `dspy.History`, provider prompts, raw
  tool arguments, or stack traces to the browser. Expose only the intentional,
  user-safe `AgentWorkspaceState` and public error codes.
- `packages/contracts/agent-workspace-state.schema.json` is the source of
  truth. Payloads include `schemaVersion`; generated TypeScript and Python
  models must be regenerated from the schema rather than handwritten.
- Keep CORS exact and explicit through `FLEET_AGENT_CORS_ORIGINS`. Never use a
  wildcard origin.
- Keep dependency pins intentional: `@assistant-ui/*`, `@ag-ui/*`, and
  `dspy==3.3.*` are compatibility-sensitive. Re-audit DSPy invariants before
  changing its version.
- Do not log API keys, provider prompts, private user data, or unsanitized
  provider responses.

## State ownership

- URL — active project and thread:
  `/projects/:projectId/threads/:threadId`.
- Zustand — app and workspace UI preferences only.
- assistant-ui — conversation state.
- AG-UI `useAgUiState<AgentWorkspaceState>()` — agent process state.

Do not mirror agent process state in Zustand or reconstruct it by parsing chat
messages. The process panel reads the AG-UI state directly. Thread restoration
fetches one versioned bootstrap snapshot before mounting the keyed runtime;
preserve stable server message and parent IDs when restoring branches. Fallback
loads call raw `fetchBootstrap`; never nest a cached bootstrap query inside its
own `queryFn`.

The UI uses shadcn/ui's Base UI flavor. Compose links with `render={<a />}`;
do not introduce Radix-specific `asChild` patterns. Follow Fluid Functionalism
design tokens across custom components (`Card`, `Switch`, etc.), ensuring
interactive controls wire accessible names properly (e.g. `aria-labelledby`
linked to `CardTitle` or explicit labels). Maintain CSS logical properties
(`marginInlineStart`, `paddingInlineStart`, `insetInlineStart`, etc.) across
components and layouts for bidirectional (RTL) support.

Agent run activity is projected inline within the assistant-ui message stream
as collapsible step cards (`RunActivityInline`), while the desktop process
panel focuses on Sources, Artifacts, and file exploration.

## Backend and DSPy rules

- Routes depend on `AgentEngine.run()` and `AgentRunResult`, not ReAct internals.
  Raw history remains server-side.
- `fixtures` mode is deterministic and provider-free; `engine` mode uses the
  live DSPy bridge and requires an explicitly configured provider key.
- Use scoped `dspy.context(...)`; do not call global `dspy.configure`.
  Synchronous tools need typed annotations, and instrumenting a tool must not
  erase those annotations.
- Persistence changes use Alembic migrations. Engine runs require an existing
  thread, and bootstrap snapshots remain versioned and safe for the browser.
- Tests that exercise streaming or concurrency need real sockets; use the
  repository's `live_server_factory` instead of assuming ASGI transport can
  stream concurrently.

## Contract workflow

1. Edit `packages/contracts/*.schema.json`.
2. Regenerate TypeScript with `pnpm --filter web contracts:sync`.
3. Regenerate the Python model with the command documented in
   `CONTRIBUTING.md`.
4. Run the contract freshness tests and the relevant web/API checks.

Generated contract files are not authored models; do not edit them by hand.

## Common commands

Run these from the repository root unless noted otherwise:

| Task | Command |
| --- | --- |
| Web dev server | `pnpm dev:web` |
| API dev server | `pnpm dev:api` |
| Web lint, tests, build | `pnpm --filter web lint`, `pnpm --filter web test`, `pnpm --filter web build` |
| API lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` |
| API typecheck | `cd apps/api && uv run mypy app` |
| API tests | `cd apps/api && uv run pytest` |
| Apply migrations | `cd apps/api && uv run alembic upgrade head` |
| Fixture browser flow | `bash scripts/e2e-fixtures.sh` |

For UI changes, include real-browser evidence when practical: the URL and
identity used, accessible interaction, responsive behavior, and a fresh
console check. The engine browser flow in `scripts/e2e-engine.sh` requires a
configured provider and a safe test environment.

Before handing work off, report the exact checks that passed, anything that
could not run, and any remaining uncertainty. See `README.md` for setup and
`CONTRIBUTING.md` for pull-request and contract details.
