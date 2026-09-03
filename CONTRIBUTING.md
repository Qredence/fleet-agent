# Contributing to Fleet Agent

Thank you for helping improve Fleet Agent. The project is an early-stage
FastAPI, React, AG-UI, and DSPy workspace. Small, focused pull requests are
easier to review and keep the public contract stable.

## Before you start

Read the [README](README.md) for setup and the current runtime limitations.
In Prime Lab workspaces, run `prime lab setup` before working; it generates the
ignored `AGENTS.md` with the engineering invariants for frontend, backend,
contracts, persistence, and the DSPy boundary.

For a usage question, start a [Discussion](https://github.com/Qredence/fleet-agent/discussions).
For a reproducible defect or scoped feature request, use an
[Issue](https://github.com/Qredence/fleet-agent/issues). Never use a public
issue for a security vulnerability; follow [SECURITY.md](SECURITY.md).

## Local setup

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

Run the web and API development servers in separate root-level terminals:

```bash
pnpm dev:web
pnpm dev:api
```

Fixture mode is the default and does not require a provider key. Engine mode
requires an explicitly configured provider key and should use a safe test
environment.

## Repository boundaries

- `apps/web` contains the React UI and browser tests.
- `apps/api` contains FastAPI routes, AG-UI coordination, the DSPy engine,
  persistence, migrations, and API tests.
- `packages/contracts` is the source of truth for the public agent-state JSON
  Schema and canonical fixtures.
- Prime Lab's generated `AGENTS.md` documents non-negotiable boundaries,
  including the rule that raw DSPy reasoning and provider prompts never reach
  the browser.

Keep runtime changes focused. Do not introduce handwritten duplicates of the
generated contract models, broaden CORS with wildcards, log credentials, or
return stack traces and raw provider data in public payloads.

## Contract changes

Edit `packages/contracts/agent-workspace-state.schema.json` first. Then
regenerate the generated models:

```bash
# TypeScript model
pnpm --filter web contracts:sync

# Python model
cd apps/api
uv run datamodel-codegen \
  --input ../../packages/contracts/agent-workspace-state.schema.json \
  --input-file-type jsonschema \
  --output app/contracts/agent_state.py \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.13 \
  --use-union-operator \
  --use-title-as-name \
  --disable-timestamp \
  --formatters ruff-check ruff-format
```

Breaking changes require a new `schemaVersion`. Keep older schema files and
make unsupported versions fail clearly rather than silently misparsing them.

## Database and migrations

Engine-mode persistence uses PostgreSQL and Alembic. Add a migration for
schema changes and test both upgrade behavior and the affected persistence
paths. Do not rewrite or delete existing migrations to repair a development
database.

```bash
cd apps/api
uv run alembic upgrade head
```

## Validation

Run the relevant checks before opening a pull request. The complete CI-equivalent
set is:

```bash
pnpm --filter web lint
pnpm --filter web test
pnpm --filter web build

cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

For UI changes, run the fixture browser flow when available:

```bash
bash scripts/e2e-fixtures.sh
```

Include the exact commands you ran in the pull request. If a check could not
run, explain why and identify what remains unverified. Do not include provider
keys, private data, raw reasoning, or unsanitized logs in test output,
screenshots, fixtures, or pull requests.

## Pull requests

Pull requests should:

- Explain the problem and the smallest useful change.
- Link the relevant issue or discussion when one exists.
- Describe user-visible behavior and any API, schema, migration, or
  configuration impact.
- Include focused tests and screenshots or browser evidence for UI changes.
- Update public documentation when setup, configuration, behavior, or
  security expectations change.
- Preserve unrelated work and avoid generated or local environment files.

Reviewers may request changes when a proposal crosses the chain-of-thought
boundary, weakens exact-origin CORS, exposes filesystem paths or credentials,
or changes generated contracts without updating their source schema.

## Commit and review etiquette

Use a clear, focused commit history and keep unrelated refactors out of a
feature or bug-fix pull request. Be specific and respectful in reviews. The
[Code of Conduct](CODE_OF_CONDUCT.md) applies to all project spaces.
