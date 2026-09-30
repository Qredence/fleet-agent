# Backend dependency upgrade

Reviewed and implemented on 2026-09-30. Scope: `apps/api`, its provider
integration, and the checks/docs that consume it. Python 3.13 is the baseline.
DSPy and MLflow retain exact pins; other dependencies have tested minimums.
`apps/api/uv.lock` records the complete reproducible resolution.

## Dependency decisions

| Dependency | Before | After | Effect on this backend |
| --- | --- | --- | --- |
| FastAPI | `fastapi[standard]>=0.141.1`, locked 0.141.1 | `fastapi>=0.142.1`, locked 0.142.1 | Current stable fixes; core runtime avoids unused form/email/cloud packages. |
| DSPy | `dspy[typesafe]==3.4.0` at HEAD | `dspy==3.4.0` | Preserve the existing manifest edit. Use native lm15 engines; remove the unused TypeSafe extra and its HTTPX2 stack. |
| MLflow | `==3.16.1` | unchanged | Already current stable. Existing DSPy tracing remains opt-in; no HTTP tracing added. |
| AG-UI protocol | `>=0.1.20`, locked 1.0.0 | `>=1.0.0`, locked 1.0.0 | Express the version actually tested by current wire contracts. |
| SQLAlchemy | `>=2.0.52`, locked 2.1.1 | `sqlalchemy[asyncio]>=2.1.1` | Declare async support and let its extra provide greenlet; remove standalone greenlet. |
| OpenAI SDK | direct `>=2.54.0,<3` | transitive 2.54.0 | Native integration removes the application's SDK import/dependency. DSPy/LiteLLM still require OpenAI 2.x. |
| LiteLLM | transitive 1.102.1 | transitive 1.103.1 | Latest compatible stable version. Remains mandatory upstream, although application inference requires native execution. |
| AnyIO | transitive 4.15.1 | direct `>=4.15.1` | Explicit worker lifecycle management: wait for workers before releasing their clients. |
| Pydantic | transitive 2.13.5 | direct `>=2.13.5` | Existing models and strict, immutable provider configuration. |
| PyYAML | transitive 6.0.3 | direct `>=6.0.3` | Existing declarative spec/front-matter imports now correctly declared. |
| Starlette | transitive 1.7.0 | direct `>=1.7.0` | Existing middleware/response imports now correctly declared. |
| httpcore | transitive 1.0.9 | direct `>=1.0.9` | Existing web-tool transport imports now correctly declared. |
| HTTPX | runtime + duplicate dev declaration, 0.28.1 | runtime only, `>=0.28.1` | Keep the client used by web tools; remove duplicate declaration. |
| orjson | unused direct `>=3.12.0` | no direct declaration | Application code does not import it. Upstream packages may still install it. |
| FastAPI CLI | runtime through standard extra, 0.0.32 | dev `>=0.0.32` | Preserve `uv run fastapi dev` without installing the cloud CLI. |
| deptry | absent | dev `>=0.25.1` | Check missing, unused, transitive-only and development-only imports locally and in CI. |
| PyYAML types | absent | dev `>=6.0.12.20260906` | Remove the blanket untyped-import suppression in the spec loader. |

Other existing direct dependencies were already at their current stable locked
versions: Alembic 1.20.0, asyncpg 0.31.0, pydantic-settings 2.15.0, Uvicorn
0.54.0; development tools datamodel-code-generator 0.83.0, jsonpatch 1.33,
jsonschema 4.26.0, mypy 2.3.1, pytest 9.1.1, pytest-asyncio 1.4.0 and Ruff
0.16.9. No prerelease was selected.

The lock refresh also updates boto3/botocore, filelock, fonttools, google-auth,
graphql-core, librt, platformdirs, regex and Werkzeug. The lock shrinks from
175 to 167 package records, including platform-specific records. Use
`uv sync --locked --all-groups` to install this reviewed resolution.

### What upstream changes mean

- FastAPI 0.142 introduces native OpenTelemetry support; 0.142.1 fixes repeated
  endpoint wrapping. This change adopts the fixes without enabling request
  tracing. Existing middleware, startup, responses and AG-UI streams are tested.
  [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/).
- DSPy 3.4 is the LM transition release: canonical frozen lm15 requests,
  responses and stream events replace custom `BaseLM.forward` integrations,
  which are deprecated for removal in 3.5. DSPy owns retries, errors, callbacks,
  usage and conversion for adapters. Custom engines are caller-owned.
  [DSPy 3.4 release](https://github.com/stanfordnlp/dspy/releases/tag/3.4.0).
- SQLAlchemy 2.1 makes explicit asyncio extras relevant to greenlet installation;
  2.1.1 includes a packaging fix. Existing mappings, transactions and migrations
  work under the resolved version. MLflow still emits an upstream `noload`
  deprecation warning; it is not suppressed by application code.
  [SQLAlchemy 2.1 changes](https://docs.sqlalchemy.org/en/21/changelog/changelog_21.html).
- OpenAI 3.22.0 is newer than the resolved SDK, but LiteLLM 1.103.1 requires
  `openai>=2.20.0,<3`. Forcing 3.x would break the upstream dependency contract.
  OpenAI 3.0 also moves to HTTPX2; removing our SDK bridge avoids that migration
  in application code. Revisit when DSPy/LiteLLM support 3.x.
  [OpenAI 3.0 release](https://github.com/openai/openai-python/releases/tag/v3.0.0),
  [LiteLLM package metadata](https://pypi.org/pypi/litellm/1.103.1/json).

## Native provider boundary

`app/agent/gateway.py` declares endpoint, authentication, compatibility policy
and capabilities using public DSPy interfaces: `LM15Engine`, `RouterConfig`,
`ProviderDefinition`, `AccessPolicy` and `OpenAIChatCompat`. Each gateway run
owns its router; browser credentials are never registered globally. Hosted
providers use `dspy.LM(engine="lm15")` by default, or an owned native router when
diagnostics or a request ceiling is enabled. Unsupported native inputs fail clearly.

The 565-line OpenAI SDK bridge is removed. Application code no longer builds
SDK completions or LiteLLM streaming chunks. Scripted test engines return
canonical responses/events. Strict, frozen Pydantic configuration uses
`SecretStr`; provider keys are excluded from configuration serialization.

The existing application program, scoped DSPy context, callbacks, ChatAdapter
synthesis listeners, scrubbing, private-endpoint validation and wire contracts
remain the relevant boundaries. Native gateway wire tests cover credentials,
verbatim model IDs, system/developer roles, tool/schema payloads, usage,
streaming, authentication/rate/server errors and refusal to follow redirects.
OpenRouter attribution headers come only from trusted server configuration.

Run resources close on completion, exceptions and construction failure. The
streaming wrapper waits for its worker to unwind on cancellation/disconnect
before releasing the LM/router and web clients; a worker's closed-stream error
cannot replace a pending caller cancellation. Cleanup is idempotent. Active
provider calls still need to finish or hit their transport timeout; Python
worker threads are not forcibly terminated.

## Configuration migration

1. Replace `MODAL_API_KEY`, `MODAL_BASE_URL`, `MODAL_MODEL_ID` with
   `FLEET_AGENT_LLM_API_KEY`, `FLEET_AGENT_LLM_BASE_URL`, `FLEET_AGENT_LLM_MODEL`.
2. Set the intended gateway credential explicitly. `DATABRICKS_TOKEN` and
   `DATABRICKS_API_TOKEN` no longer substitute for missing or `dtn_` keys.
3. Replace legacy `X-OpenRouter-*` request headers with `X-LLM-Key`,
   `X-LLM-Base-Url`, and optionally `X-LLM-Model`. Legacy requests fail with a
   migration error. The current browser already uses the canonical headers.
4. Gateway model IDs are now truly verbatim. If the previous bridge stripped
   `openai/` from your configured model, remove that prefix yourself when the
   gateway expects a bare ID. Hosted model IDs retain their native provider
   prefix, e.g. `openai/gpt-4o-mini`.
5. An explicit `X-LLM-Response-Format: native_function_calling` now wins over a
   server setting of `false`; absent selection inherits the server setting.

No personal `.env` file is modified. Update local values yourself before a
live engine run.

## Verification

- Locked sync; Ruff lint/format; strict mypy on `app`; deptry: passed.
- API suite: **570 passed, 1 skipped** against a newly created, migrated native
  PostgreSQL database. The only skipped test requires paid/live provider opt-in;
  no database tests were skipped. MLflow's upstream SQLAlchemy warning remains.
- Both shared JSON schemas validate. Python generated contract freshness is
  checked by the API suite; TypeScript freshness by the web suite.
- Web suite: **194 passed across 25 files**; lint and production build passed.
  The existing large-bundle build warning remains.
- Real API boot: `/health`, `/ready`, `/api/tools`, `/metrics` answered
  successfully. Tool catalog reflects disabled workspace write/shell tools and
  the declared approval flags.
- Deterministic browser matrix: passed send, tool/activity, sources, cancel,
  reload and thread switching. The script now respects `API_BASE` throughout.
- Dependency audit: no additional known vulnerabilities with the existing
  `PYSEC-2026-2447` exception. Unfiltered audit reports diskcache 5.6.3's pickle
  deserialization advisory twice under the same ID (CVE-2025-69872); no fixed
  version is listed. The repository's existing exception remains unchanged.
- `git diff --check`: passed. CI configuration is updated; remote CI and paid
  inference are not part of this local validation.

### Reproduce the backend checks

```sh
cd apps/api
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run deptry .
# Create a disposable fleet_agent_test_<suffix> database first.
FLEET_AGENT_ENV_FILE=/dev/null FLEET_AGENT_DATABASE_URL="$TEST_DB_URL" \
  uv run alembic upgrade head
FLEET_AGENT_TEST_DATABASE_URL="$TEST_DB_URL" uv run pytest
```

The test harness captures `FLEET_AGENT_TEST_DATABASE_URL` before sanitizing
ambient settings, accepts only async PostgreSQL URLs naming `fleet_agent_test`
or `fleet_agent_test_<suffix>`, and never reads the developer's `.env`.
Deptry excludes sample evaluation workspace files; its only unused runtime
exceptions are asyncpg (SQLAlchemy driver loading) and Uvicorn (deployment CLI).


## Review follow-up

Authenticated `GET /api/agent/capabilities` reports the active `agent_mode`.
Browser run readiness uses that capability: fixture mode needs no provider and
sends no provider headers; engine mode requires an explicit configured profile.
Every agent POST refreshes capabilities before sending, and unavailable or
invalid capabilities block submission. No browser fixture-mode flag is needed.

Diagnostics retain only structural facts and fixed error-code/field/rule
vocabularies, not provider prose or partial prompt echoes. Historical receipts
remain unchanged. Hosted native providers support the same run-local transport
recorder and request ceiling as gateways; failed attempts count and retries are
disabled when a ceiling is configured. These checks use local transports only.


Review follow-up verification (2026-09-30):

- Full API suite: 610 passed, one paid/live-provider test skipped, against a
  disposable migrated PostgreSQL database. MLflow emitted its existing
  SQLAlchemy `noload` deprecation warning.
- Full web suite: 213 passed across 27 files on the final standalone run.
  A concurrent run had one sidebar hydration timeout; the complete standalone
  rerun passed without a sidebar implementation change.
- Ruff lint/format, mypy (92 source files), deptry, frontend lint and production
  build passed. Vite still reports large bundle chunks.
- All three shared JSON schemas validate; Python and TypeScript generated
  capability contracts pass freshness checks.
- Credential-free fixture browser matrix passed send/final answer,
  activity/sources, cancel, reload and thread switching with empty browser
  storage. A browser capability override to engine mode disabled submission
  without provider credentials.
- Fixture API health/readiness and the tool catalog passed. Workspace mutation
  tools remained disabled. The fixture API/web services and databases were
  isolated from the existing personal sessions and removed after verification.
- `git diff --check` passed. No paid provider calls, personal environment edits,
  commits, pushes or changes to the historical diagnostic receipt were made.
