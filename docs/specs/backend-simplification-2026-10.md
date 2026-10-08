# Spec: Backend simplification — lightest coherent DSPy-native app

Written 2026-10-07. Source evidence: `docs/backend-dspy-review-2026-10-07.md` and a
usage census taken this session. Deliverable owner: this spec + the commits it gates.

## Problem

The backend is DSPy-native but carries dead weight that DSPy 3.4 already solves:

- `app/agent/spec/` (947 lines) + `fleet_agent.yaml` (65) compile YAML into real DSPy
  classes — but only `react` and `predict` are used in production; five node types and
  the composite namespace machinery are test-only, and the optimizer write-back pair
  (`dump_state`/`apply_state`) has no production or eval caller.
- `app/agent/provider_diagnostics.py` (349 lines) exists to inject a transport into the
  gateway through the private `dspy._vendor.lm15.transports` import; its receipts are
  logged server-side and consumed by nothing.
- `app/agent/gateway.py` (223 lines) carries `HostedEngine` (diagnostics/budget arm only)
  next to the plain `dspy.LM(engine="lm15")` fast path.
- `_install_forced_submit_compat` (`engine.py:177-231`) monkeypatches DSPy-private
  `ReActV2._forced_submit` — the only monkeypatch in the backend — while the same
  exception classes are already mapped at the public boundary.
- The `compose_callbacks` `application_tool_lifecycle` branch is dead in production
  (test-only attribute), and `search_docs` is wired through two different callables.

Goal: the lightest coherent implementation that keeps DSPy-native capabilities:
`FleetAgent` (`dspy.Module`), the routed `dspy.ReActV2` loop with least-privilege
profiles, `dspy.streamify` + pinned `StreamListener` synthesis streaming, scoped
`dspy.context`, the `dspy.Tool` contract, server-side-only `dspy.History`, and the
`dspy.Evaluate`/GEPA harness.

## Current behavior (census, verified)

| Area | Lines | Verdict |
| --- | --- | --- |
| `app/agent/spec/` (6 files) | 947 | Test-only weight; one production importer (`signature.py`) |
| `app/agent/agents/fleet_agent.yaml` | 65 | Declares only `react` + `predict` nodes |
| `app/agent/provider_diagnostics.py` | 349 | Logs-only receipts; private transport seam |
| `app/agent/gateway.py` | 223 | `HostedEngine` arm removable; `GatewayEngine` core stays |
| `app/agent/engine.py` | 488 | Shim (55 ln) + dead callback branch + diagnostics stamps removable |
| forced-submit behavioral coverage | — | 3 tests must keep passing unchanged |
| Baseline (main @ `01463d1`) | — | pytest: 610 passed / 1 skipped / 1 warning; `def test_`: 485 |

## Desired behavior

- `signature.py` builds the two nodes directly: `build_gatherer` →
  `dspy.ReActV2(make_signature(...), tools, max_iters)`, `build_synthesizer` →
  `dspy.Predict(make_signature(...))`. Prompt text stays in
  `agents/prompts/*.md`; the shared policy body is appended to both instruction
  texts exactly as the loader did (`evidence.md`/`synthesize.md` bodies + policy).
- BYOK-with-base_url keeps a run-owned `GatewayEngine` (the documented caller-owned
  engine pattern); hosted settings use plain `dspy.LM(engine="lm15")`.
- `dspy.lm15.register_provider(...)` is rejected for BYOK: registration is process-global
  while overrides are per-request; `gateway.py`'s handled invariant ("never register
  browser keys globally") is preserved.

## Invariants

1. Public AG-UI events, REST contracts, and error codes unchanged, except the approved
   contract trim (`approval_*` termination reasons removed; schema description reworded).
2. The three forced-submit behavioral tests pass unchanged
   (`test_dspy_engine.py:260`, `test_agent_endpoint.py:131`, `test_engine_live.py:34`);
   failed runs still persist server-side history for continuation.
3. Streaming semantics unchanged (scrubber interplay, settled-field duplication guard).
4. Wire-policy coverage retained: developer/system role choice, native-call toggle,
   OpenRouter header pinning, idempotent engine close.
5. After C3: no `dspy._vendor` import anywhere (CI-grepped); no `app.agent.spec` import.
6. MLflow surfaces and the eval harness keep working (`--validate`, `--seeded`).

## Public-contract impact

`packages/contracts/termination-reasons.json` loses `approval_required`,
`approval_expired`, `approval_invalid` (no producer since the mid-loop design's
deletion; the design doc admits it). `interrupted` is kept: the startup sweep reads it
defensively (`app/api/threads.py:31-40`, `app/persistence/repositories/runs.py:85-106`).
`Run.terminationReason` schema description rewords away from the DSPy implementation
term. Contracts regenerate through the repo's own generation flow so Python + TS models
stay fresh.

## Frontend/UI impact

TS contract models regenerate identically minus the three removed reason literals
(grep `apps/web` proves none are referenced — they were never produced). No UI behavior
change; fixtures mode untouched.

## DSPy impact

Construction becomes direct, documented DSPy usage: `dspy.make_signature` over Markdown
instructions, `dspy.ReActV2`/`dspy.Predict` nodes invoked via `__call__`, scoping via
`dspy.context`, `streamify`/listeners unchanged, `Evaluate`/GEPA untouched. Booster of
the review's D-4 risk position: the vendored transport import disappears; the remaining
`dspy.lm15`/`dspy.clients.engines` import set becomes a CI guard test.

## Observability/MLflow impact

Opt-in provider diagnostic receipts (and the associated request budget they made
possible) are removed with operator-facing documentation in this spec; runaway-call
defense returns to DSPy's own bound (`FLEET_AGENT_LLM_MAX_ITERS`/`llm_max_iters`, default
6) plus DSPy-managed retries. MLflow autolog/tracing, eval datasets/scorers, and the
metrics registry are untouched.

## Tests (change ledger)

- DELETE: `tests/test_spec_loader.py` (29), `tests/test_spec_schema.py` (19),
  `tests/test_declarative_agent.py` (14), `tests/test_provider_diagnostics.py` (13).
- REPLACE: `tests/test_agent_construction.py` — gatherer is a real `dspy.ReActV2`
  built over the Markdown Evidence signature with the route's exact tools; synthesizer
  is a real `dspy.Predict` over the Synthesis signature; `synthesis_stream_fields` ==
  (`answer`, `process_summary`); prompts load from `agents/prompts/*.md` including
  policy append; `routing_signature` promoted-instruction path unchanged; DSPy surface
  guard (lm15 symbol tuple + `LM15Engine` import + no `_vendor` import).
- ADJUST: `test_gateway.py` (drop diagnostics/HostedEngine tests, keep wire-policy),
  `test_provider.py` (BYOK engine identity), `test_factory.py` (settings removal),
  `test_dspy_engine.py`/`test_dspy_contract.py` (shim → boundary),
  `test_mlflow_tracing.py` (`application_tool_lifecycle` branch removal),
  `test_contract_constants.py` (reason trim).
- What dies with the spec layer (recorded loss, no caller existed): the
  structure-fingerprint-guarded `dump_state`/`apply_state` write-back contract.

## Acceptance criteria

1. Every Phase C commit leaves `uv run pytest -q` green.
2. Phase D runs the CI-identical cycle (appendix A) clean.
3. Post-change probe: named-predictor roots still show `router`, a per-route ReActV2,
   and `synthesizer` (appendix B records before/after).
4. `grep -rn "dspy._vendor" apps/api` and `grep -rn "app.agent.spec" apps/api` → zero.
5. Line delta vs baseline recorded in appendix C (target ≈ −1,400 app lines).

## Appendix A — CI-identical validation commands (from `.circleci/config.yml`)

```sh
cd apps/api && uv sync --locked --all-groups
cd apps/api && uv run ruff check .
cd apps/api && uv run ruff format --check .
cd apps/api && uv run mypy app
cd apps/api && uv run deptry .
FLEET_AGENT_DATABASE_URL=postgresql+asyncpg://fleet:fleet@localhost:5432/fleet_agent_test uv run alembic upgrade head
FLEET_AGENT_TEST_DATABASE_URL=postgresql+asyncpg://fleet:fleet@localhost:5432/fleet_agent_test uv run pytest
# boot smoke: uvicorn app.main:app on :8123 with DB/API key/mlflow sqlite; /health 200,
# /ready 200|503, /metrics 401 without key + 200 with key (exact script in CI config).
# contracts job: jsonschema Draft202012 validation of packages/contracts/agent-workspace-state.schema.json
cd apps/api && uv run python -m evals.run --suite routing --validate   # offline extra
cd apps/api && uv run python -m evals.run --suite routing --seeded     # offline extra
```

## Appendix B — probe recordings (recorded 2026-10-07)

- BEFORE (main @ `01463d1`), `FleetAgent(tool_profiles={"research": [get_current_time tool]})`:
  `named_predictors()` → `['router', "evidence_agents['research'].react", 'synthesizer']`
- Empty profile (`{"research": []}`): `['router', 'synthesizer']` (tool-free routes get no
  loop — unchanged by this work).
- Offline `dspy.LM("openai/gpt-4o-mini", engine="lm15", cache=False, api_key=..., temperature=0.2)`
  constructs without network and closes cleanly.

## Appendix B2 — DSPy doc evidence added by Phase B (all accessed 2026-10-07)

From <https://dspy.ai/current/community/normalized-lm-api-migration/>:

- *"3.4 is the transition release; 3.5 removes the old LM integration interfaces."*
- *"Custom engines are caller-owned and are not closed by DSPy."*
- *"A custom engine owns its connection: `api_key`, `api_base`, `timeout`, `extra_headers`
  and the other client settings are refused on `dspy.LM(engine=...)`, on `copy()` and on
  every call, rather than dropped."* — keys therefore belong to the engine constructor
  (`ProviderConfig`/`RouterConfig`), never to `dspy.LM(engine=...)`; the current
  construction already obeys this.
- For HTTP providers lm15 can speak to: *"declare it with `dspy.lm15.register_provider(...)`
  instead of writing an engine: each `dspy.LM` binds the registrations present at
  construction"* — a **process-global** declaration, an import-time environment fact. The
  browser's BYOK endpoints are per-request values, so declaring them globally would
  accumulate unbounded and re-bind every later LM. Rejected; caller-owned engine stays.
- Public error family survives 3.5: *"Applications can keep catching `dspy.LMError`,
  `dspy.LMAuthError`, `dspy.ContextWindowExceededError`, and their siblings. These public
  error names are not part of the 3.5 interface removal."*
- Deprecated (not used by this backend): custom `BaseLM.forward()`/`aforward()`,
  `LegacyEngine`/`AsyncLegacyEngine` (from `dspy.clients.engines`), `complete_legacy()`.

From <https://dspy.ai/current/api/models/LM/>: *"engine: 'auto' prefers lm15 for
representable requests; 'litellm' preserves the compatibility backend; 'lm15' refuses
unsupported mappings rather than selecting LiteLLM. A custom engine implements
`complete(Request) -> Response` and optionally `stream(Request)`."*

From <https://dspy.ai/current/tutorials/custom_lm_engines/>: two situations — an HTTP
provider is a *"declare the provider"* job and *"Each `dspy.LM` binds the registrations
present when it is constructed and keeps them for its whole life"*; anything else is
*"Write an engine. It owns its whole connection."* GatewayEngine stays the latter.

## Appendix C — line-delta ledger (filled in Phase D)

To be recorded: `git diff --stat` summary per Phase C commit.
