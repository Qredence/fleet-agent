# Backend review — DSPy-native conformance and recommendations

Reviewed on 2026-10-07 against fleet-agent@8b87cafc25a887b4b144df4ad938f47652d20866 and DSPy 3.4.0 (docs cited inline).
Scope: apps/api backend, agent/spec/engine/tools/safety layers, eval harness. No code was changed for this review.

DSPy guidance is cited as verbatim quotes with URL and access date (all fetched 2026-10-07). Repo claims carry `file:line` refs the reviewer read in full. The in-repo contracts of record (`docs/dspy-agent.md`, `docs/architecture.md`, `docs/backend-dependency-upgrade.md`) were checked against code; the two disagree nowhere material, and both admissions they make are confirmed in section 5.

## 1. Executive summary

The backend uses DSPy the way DSPy's own documentation recommends: one composed `dspy.Module` per run (`FleetAgent`), sub-modules invoked through `__call__`, settings injected via `dspy.context`, tools as explicit `dspy.Tool` objects, and a scoped-adapter synthesis step that makes `dspy.streamify` streaming possible. The approval model (withhold gated tools before the program is built) is strictly stronger than any in-loop control-flow scheme.

The two real debts are both "borrowed from DSPy's future": (F1) `_install_forced_submit_compat` monkeypatches DSPy-private `ReActV2._forced_submit` (`engine.py:177-231`), and (F2) the provider layer rides the LM-transition release wave via a broad `dspy.lm15` / `dspy.clients.engines` import surface plus one truly private `dspy._vendor` import (`gateway.py:14-29`, `provider_diagnostics.py:270`). Both are sound under the `dspy==3.4.0` pin; neither should survive the next upgrade silently. The P0/P1 recommendations are a CI guard for those seams and a consolidation of forced-submit failure handling at the program boundary.

Everything else is P2: contract values with no producer (already admitted in `docs/dspy-agent.md:312-317`), a message-regex coupling to DSPy error text, and a few one-line nits. The 1 skipped pytest case (live provider opt-in) and the MLflow `noload` warning are preexisting, not introduced by this review.

## 2. System map (verified)

```text
Browser (apps/web) --REST+SSE--> FastAPI (apps/api)
  app/main.py (126 ln): create_app, lifespan — orphan-run sweep (degrades on DB outage),
                        MLflow opt-in, api-key open-mode warning, CORS with X-LLM-* headers
  app/api/middleware.py (88 ln): request id, API-key (constant-time), body cap; /health,/ready allowlist
  app/api/agent.py (197 ln): POST /api/agent → provider-override SSRF validation → thread/run-id
                        preflight → semaphore(429) → reserve_run → SSE (permit released in finally)
  app/agui/live_coordinator.py (683 ln): LiveDSPyCoordinator — exactly-once terminal settlement
                        (settlement_lock + flags), event drain loop, disconnect/timeout/failure paths,
                        DSPy LM error class → public code mapping
  app/agent/factory.py (312 ln): make_engine_builder / build_dspy_engine; _build_lm (native lm15);
                        _build_adapter (JSONAdapter); _build_tool_registry (TOOL_SPECS-mandatory);
                        build_tool_profiles (least-privilege lattice, gated tools withheld)
  app/agent/engine.py (488 ln): DspyAgentEngine — scoped dspy.context(lm, adapter, callbacks,
                        track_usage); run via to_thread; stream via dspy.streamify + pinned listeners
                        + StreamingScrubber; forced-submit compat shim (private-symbol)
  app/agent/program.py (359 ln): FleetAgent(dspy.Module) — router (dspy.Predict) → one dspy.ReActV2
                        per least-privilege route ("direct" has none) → synthesizer (spec-built
                        Predict) under scoped ChatAdapter; evidence_json from loop history
  app/agent/signature.py (91 ln) + app/agent/spec/: declarative YAML (fleet_agent.yaml) → real DSPy
                        classes (spec/types.py: predict/chain_of_thought/react/refine/best_of_n/
                        sequential/fanout with import-time drift guard)
  app/agent/routing.py (144 ln): six-route vocabulary, fail-closed coerce_route, promoted-artifact
                        reader with format tag
  app/agent/gateway.py (223 ln): GatewayEngine/HostedEngine (LM15Engine subclasses), run-owned
                        routers, deepseek thinking-replay, diagnostics transport seam
  app/agent/tooling.py (181 ln) + tool_registry.py (360 ln): TOOL_SPECS single model-facing table;
                        strict schema validation; async tools rejected; name agreement enforced
  app/agent/approval.py (62 ln): approval = decision before the run; gated tools never offered
  app/agent/instrumented.py (88 ln): redaction for public tool args (masking + structural only)
  app/kernel/content_safety.py (223 ln): high-precision batch scrub + StreamingScrubber
                        (prefix-stable emission, anchor-based)
  app/kernel/history_safety.py (219 ln): MessageWrite validation — forbidden reasoning/server-only
                        keys, depth/cycle bounds; sanitize_message_content for legacy state
  app/persistence/ (models.py 218 ln, run_persistence.py 654 ln): projects/threads/messages/runs/
                        run_states/dspy_histories (schema_version+dspy_version, server-side only)/
                        sources/artifacts; branch-aware heads; short transactions
  evals/ (run.py 351 ln, optimize.py 352 ln, scoring.py 133 ln, agent_tool_routing.py 322 ln,
                        mlflow_tracking.py): validate/seeded/score modes; GEPA router optimization
                        with train-only valset, held-out gates, explicit --promote
```

## 3. DSPy-native conformance

### 3.1 Program composition (FleetAgent, spec layer)

The probe (section 7) confirms `FleetAgent` is a real `dspy.Module` exposing exactly three predictor roots: `router`, `evidence_agents['<route>'].react`, `synthesizer`. Composition follows the documented contract:

- Sub-modules are plain attributes / dict entries, so DSPy's discovery finds them: *"Sub-modules are discovered by walking `self.__dict__`, not registered. ... The tree-walk methods (`named_predictors`, `named_parameters`, `named_sub_modules`) inspect `self.__dict__` at call time and recurse into lists and dicts as well as direct attributes."* <https://dspy.ai/current/diving-deeper/modules/> — matches `program.py:56-76` (`self.router`, `self.evidence_agents` dict, `self.synthesizer`) and the probe output.
- The program is always invoked through `__call__`: the engine's run path (`engine.py:464-468`) and the program's internal calls (`program.py:108, 178, 208`) — *"Calling `forward()` directly bypasses all of that ... Always invoke a module as `module(...)`."* <https://dspy.ai/current/diving-deeper/modules/>
- Settings propagate by context, not constructor: the engine scopes `dspy.context(lm, adapter, callbacks, track_usage)` per run (`engine.py:373-378, 458-463`), and `_ThreadedProgram.acall` re-enters the same context — *"Sub-modules read `dspy.settings.lm` (and `.adapter`, `.callbacks`) at call time."* <https://dspy.ai/current/diving-deeper/modules/>
- The engine composes rather than replaces DSPy callbacks because `dspy.context(callbacks=...)` replaces the global list (`engine.py:100-117`) — this is what keeps `mlflow.dspy.autolog` alive on live runs; pinned by `tests/test_mlflow_tracing.py:127`.

The spec layer (`app/agent/spec/`) is a defensible narrowing, not a second framework: `spec/types.py:220-232` maps the closed YAML type set to real DSPy classes with an import-time drift guard against `schema.MODULE_TYPES`, composite child names are checked against DSPy attributes (`spec/types.py:54-65`), `Fanout` builds `dspy.Parallel` per call to honor current `num_threads` and disables the straggler resubmit on purpose to avoid duplicated LM calls and tool side effects (`spec/types.py:182-206`), and the router signature is rebuilt per instruction set because `Signature.instructions` lives on the class (`routing.py:104-117`). What the spec cannot express is kept in Python with the reason named (`signature.py:9-18`).

Router coercion is fail-closed: invented names, non-strings, and empty input all degrade to the least-privileged `direct` route, and normalization only recovers surface noise of real members (`routing.py:84-101`), pinned by 25 fixture cases (`evals/agent_tool_routing.py:220-249`). The router's own parse failure also degrades to `direct` rather than failing the run (`program.py:171-183`).

Evidence hand-off to the synthesizer is a str-typed JSON document with a budget that is spent on *valid JSON*: `bounded_json` keeps entries in order and binary-searches the overflowing entry down to the largest prefix that still fits, never slicing a serialized document (`evidence.py:37-105`, `program.py:248-278`, budget 8000 chars at `evidence.py:27`). Only tool names, results, and error flags cross; `next_thought` does not (`program.py:251-263`). This is the deliberate tradeoff pinned by `tests/test_evidence.py`.

### 3.2 Streaming (streamify, listeners, scrubber interplay)

The streaming path is DSPy-native end to end: `dspy.streamify(_ThreadedProgram(program), is_async_program=True, stream_listeners=..., include_final_prediction_in_output_stream=True)` under the scoped context (`engine.py:379-387`). The streamed fields are the synthesizer's public `answer`/`process_summary` — predictor output fields, which is exactly what `streamify` can carry: *"The only requirement is that the streamed field must be of type `str`."* <https://dspy.ai/current/tutorials/streaming/>

Two subtleties are handled correctly:

1. **Adapter pinning.** Synthesis runs under a scoped `dspy.context(adapter=ChatAdapter())` inside the worker thread (`program.py:207-212`), but the stream consumer runs on the event loop and cannot see that thread-local scope. `SynthesisStreamListener.receive` re-opens the ChatAdapter scope so chunk parsing uses the field boundaries the synthesizer actually produced (`synthesis_stream.py:19-38`). Without this the listener would parse ChatAdapter sections with the ambient JSONAdapter and never detect a boundary.
2. **Settled vs streamed text.** The listener buffers before finalizing — *"the listener buffers the output tokens before sending to the final generator, which is why you will usually see the last chunk of type `StreamResponse` has more than one token."* <https://dspy.ai/current/tutorials/streaming/> The engine therefore flushes every scrubber before consuming the final Prediction (`engine.py:414-421`) and suppresses the settled-field re-emit when tokens already streamed the answer (`live_coordinator.py:397-412`, `event_mapper.py:171-203`). The `include_final_prediction_in_output_stream=True` choice also covers the cache-hit case — *"When the program hit cache, or no listeners captured anything, the final prediction will still be included in the output stream even if this is `False`."* <https://dspy.ai/current/api/utils/streamify/>

Streamed deltas pass through one `StreamingScrubber` per field (`engine.py:366-395`) before becoming AG-UI text events, so the streamed prefix never diverges from the settled, batch-scrubbed fields (section 3.5). A stream that ends without a Prediction raises (`engine.py:422-423`), and the coordinator turns any unmapped engine exception into exactly one safe terminal event (`live_coordinator.py:555-617`).

### 3.3 Provider/gateway (lm15 ownership)

DSPy 3.4 made the native LM layer the recommended path — *"DSPy's LM layer now uses bundled lm15 request, response, and streaming types, available through `dspy.lm15` without a separate installation."* <https://github.com/stanfordnlp/dspy/releases> — and this backend is on it: `dspy.LM(engine="lm15")` for plain hosted models (`factory.py:55-64`) and run-owned `GatewayEngine`/`HostedEngine` (both `LM15Engine` subclasses) for browser-supplied or diagnostics-limited configurations (`gateway.py:47-214`). Keys never register globally; each run owns its router and closes it (`gateway.py:48, 160-169, 217-223`).

The complete import inventory (verified by reading): from `dspy.lm15` — `AccessPolicy`, `OpenAIChatCompat`, `ProviderDefinition`, `Request`, `Response`, `ResponseStream`, `RouterConfig`, `StreamDeltaEvent`, `StreamEndEvent`, `StreamErrorEvent`, `StreamStartEvent`, `ThinkingPart`, `ToolCallPart` (`gateway.py:15-29`) plus `ConfigurationError` (`provider_diagnostics.py:17`); from `dspy.clients.engines` — `LM15Engine` (`gateway.py:14`); and one deeper seam — `dspy._vendor.lm15.transports.StdlibTransport` (`provider_diagnostics.py:270`), acknowledged in-code as not re-exported through `dspy.lm15`. `dspy.lm15` is the release-documented public namespace; `dspy.clients.engines` and `dspy._vendor` are the fragile ends (risk register, section 4).

The deepseek thinking-replay special case (`gateway.py:71-73, 87-92, 117-158`) exists because ReActV2's history retains tool calls but not provider thinking parts; the engine caches `ThinkingPart`s keyed by tool-call ids in run-owned state and re-injects them on the next request, never publishing or persisting them (`gateway.py:74-77, 160-169`). Request budgets (`provider_request_limit`) translate to a pre-call rejection plus `lm.num_retries = 0` (`factory.py:89-91`, `provider_diagnostics.py:278-283`), and diagnostic receipts retain only structural facts and a fixed vocabulary — hashed call ids, no content strings (`provider_diagnostics.py:55-119, 171-263`).

### 3.4 Tools contract (sync-only, TOOL_SPECS, approvals)

`TOOL_SPECS` (`tool_registry.py:73-193`) is the single model-facing catalog: the registry rewrites every tool's description from the table at registration (`tool_registry.py:284-299`), the browser `GET /api/tools` renders the same rows (`tool_registry.py:240-252`), and an executable-but-undeclared tool fails at engine build (`factory.py:126-143`). This is the mechanism that ended the previously observed drift between Tools page and model schema (docstring, `tool_registry.py:9-16`; pinned by `tests/test_tool_contract.py`).

Tool construction is stricter than DSPy requires: concrete return annotations, typed arguments, no positional-only/varargs, non-empty descriptions, names matching `[A-Za-z0-9_-]{1,64}`, and `submit` reserved (`tooling.py:20-151`; `program.py:332-359`). DSPy's own contract is respected and tightened — *"Arguments are validated before execution ... `Tool.__call__(**kwargs)` and `Tool.acall(**kwargs)` validate arguments against the JSON schema."* <https://dspy.ai/current/diving-deeper/tools/> Production tool schemas are pinned in `tests/test_dspy_contract.py:80-113`.

The sync-only rule is deliberate and honest about its boundary: async tools raise at registration in both the registry and the program (`tool_registry.py:300-304`, `program.py:351-356`) because the DSPy 3.4.0 program path executes tools synchronously — *"Calling an asynchronous tool from synchronous code raises by default."* <https://dspy.ai/current/diving-deeper/tools/> The consequence (documented in finding F7): MCP tools cannot participate today — *"MCP tools are asynchronous because `mcp.ClientSession` is asynchronous. Use a module's async entry point, such as `acall`, or explicitly enable async-to-sync conversion when appropriate."* <https://dspy.ai/current/diving-deeper/tools/> The future async entry point is already foreshadowed by the runtime: the engine runs the program via `acall` semantics (`streamify(is_async_program=True)`, `engine.py:379-387`).

Approvals are a decision, not control flow: `approved_tool_names` reads `forwardedProps.approvedTools` fail-closed (`approval.py:29-48`), and `build_tool_profiles` drops gated tools from every profile unless authorized (`factory.py:146-179`) — an unauthorized `write`/`edit`/`bash` is never offered to the model, so it cannot be talked into calling it. This replaced an 846-line mid-loop fork of `ReActV2.forward` over four private DSPy symbols (`approval.py:8-13`, `docs/dspy-agent.md:302-306`). Public tool-argument events carry masked, structural values only (`instrumented.py:14-78`).

### 3.5 Safety kernels (content_safety, history_safety)

Batch scrubbing is deliberately high-precision (provider key formats, AWS/Google/GitHub/Slack tokens, JWTs, Bearer headers, PEM blocks, explicit credential assignments) with no generic base64/hex guesses that would corrupt legitimate answers (`content_safety.py:25-69`); it is applied to every public free-text surface — result fields (`engine.py:249-267`), tool previews, artifact content (`report.py:44-47`), and legacy bootstrap state (`content_safety.py:77-89`).

The `StreamingScrubber` argument holds up under local inspection: emission is limited to `min(len(scrubbed) - holdback, first remaining anchor index)`, then retreated to a fixpoint so no boundary fragment is a proper prefix of an anchor or of the `[redacted]` mask (`content_safety.py:169-223`). That makes the emitted concatenation equal `scrub_public_text(full_text)` **provided every secret pattern starts with a listed anchor** — the invariant the module documents (`content_safety.py:100-104`). The reviewer ran the two-list check (section 7): all ten `_SECRET_PATTERNS` prefix families (`-----BEGIN`, `sk-`, `AKIA`, `AIza`, `gh[pousr]_`, `github_pat_`, `xox`, `eyJ`, `Bearer`, and the api-key/secret/token/password alternation family) are covered by the 26 anchors, including every `[_-]` separator variant of the credential-assignment family. The lists agree today; nothing mechanical enforces them, which is why the drift check deserves a permanent test (P2 below).

`history_safety` closes the payload side: `MessageWrite` accepts only `aui/v0` user/assistant envelopes, rejects forbidden server-only keys (`next_thought`, `history`, provider prompts, stack traces, storage paths — `history_safety.py:20-60`), rejects any key whose normalized form contains `reasoning`/`chainofthought`/`nextthought` (`history_safety.py:118-125`), and bounds nesting/cycles without recursion (`history_safety.py:145-167`). The two kernels are complementary by design (`content_safety.py:3-7`).

`dspy_histories` (which does contain `next_thought`) is written server-side only, versioned with `schema_version` and `dspy_version` (`models.py:148-171`, `run_persistence.py:47, 507-514`), and never returned to the browser; assistant messages persisted for the wire carry only id/role/content with the scrubbed answer (`run_persistence.py:345-357`).

## 4. Upstream-risk register

| # | Risk | Evidence | DSPy doc evidence | Disposition today |
| --- | --- | --- | --- | --- |
| R1 | `dspy.ReActV2` alias removal in 3.6; becomes `dspy.ReAct` in 3.5 with different legacy-`ReAct` behavior to avoid | `app/agent/spec/types.py:105` (only import site); error text `program.py:353`; guard test `tests/test_dspy_contract.py:35-44` | *"`dspy.ReActV2` is its experimental, structured-history replacement and will become the implementation behind the canonical `dspy.ReAct` name in DSPy 3.5. The `dspy.ReActV2` name will remain as a deprecated compatibility alias throughout the 3.5 release line and will be removed in DSPy 3.6."* and *"Pin the DSPy version while using the experimental `ReActV2` name."* <https://dspy.ai/current/diving-deeper/react/> | Contained: one import site + a loud guard test that names the migration. Rename is a small, reviewable diff after the 3.5 upgrade. |
| R2 | lm15/engine churn — "3.5 is the migration deadline"; legacy `BaseLM.forward` integrations are what get removed, and this repo is already on the target interface, but the bundled engine/router symbols themselves can move | `gateway.py:14-29` (13 `dspy.lm15` symbols + `LM15Engine` from `dspy.clients.engines`) | *"3.4 is the LM transition release; 3.5 is the migration deadline."*, *"DSPy owns caching, managed retries, callbacks, history, and usage accounting. Custom engines remain caller-owned."*, *"Custom `BaseLM.forward()` and `aforward()` integrations. Migrate to the engine interface."* <https://github.com/stanfordnlp/dspy/releases>; repo claim at `docs/backend-dependency-upgrade.md:47-51` | Correctly isolated to two files; the repo doc itself calls this the highest-risk surface. Needs a CI guard (P0) so a bump breaks loudly. |
| R3 | Private vendored transport — `dspy._vendor.lm15.transports.StdlibTransport` | `provider_diagnostics.py:266-283` | Not covered by any documented `dspy.lm15` surface; in-code comment acknowledges it (`provider_diagnostics.py:268-269`) | Opt-in diagnostics only (`settings.provider_diagnostics_enabled`, default off), so runtime exposure is limited; still the most fragile import in the repo (P0 guard). |
| R4 | Error-text coupling — public termination reasons parsed from the DSPy error message | `engine.py:146-160` (`_FORCED_SUBMIT_REASON_RE`) | DSPy 3.4.0: *"Missing or invalid submission raises ValueError; parse and context-window failures from the forced submission propagate."* <https://github.com/stanfordnlp/dspy/releases> — no structured reason on the raise in 3.4 | Fallback to the loop's `break_reason` limits blast radius (`engine.py:223`); reason vocabulary pinned by the termination-matrix tests (`tests/test_dspy_contract.py:223`). P2. |
| R5 | Forced-submit behavior changed across DSPy versions (3.3 returned a Prediction; 3.4 raises) and the docs pages describe the post-raise shape differently than the release notes | `engine.py:177-183` (in-code history of the change) | React page: *"If that attempt fails, the prediction still returns its history and a termination reason describing why the normal loop stopped, but it may not contain the declared output fields."* <https://dspy.ai/current/diving-deeper/react/> vs release note above | The shim exists precisely to reconcile the 3.4 raise with the documented Prediction shape; consolidation at the program boundary (P1) removes the reconciliation from the private symbol. |
| R6 | ReActV2 does not truncate history on context overflow | `app/agent/engine.py:142` (public code for the mapped reason) | *"Unlike ReAct, ReActV2 does not currently truncate old history events on context overflow."* <https://dspy.ai/current/diving-deeper/react/> | Mapped to the public `agent_context_limit` error (`engine.py:142`); the loop's `max_iters` hard bound (`settings.py:52-57`, program default 20) caps worst-case growth. No action. |

## 5. Layer-by-layer findings

One row per review batch; severities map to section 6. "DSPy doc evidence" quotes are verbatim (accessed 2026-10-07).

| # | Severity | Area | Finding | Repo evidence | DSPy doc evidence |
| --- | --- | --- | --- | --- | --- |
| C1 | — | Entry surface | No finding. The route does transport-level work only (SSRF validation, preflight, reservation, permit release); no engine-boundary logic leaks above `AgentEngine`. | `app/api/agent.py:87-185`, `app/main.py:30-63`, `app/api/middleware.py:42-88` | — |
| F1 | P1 | Engine | `_install_forced_submit_compat` depends on DSPy-private `ReActV2._forced_submit` and converts its raises (ValueError/AdapterParseError/ContextWindowExceededError) back into the documented failed-Prediction shape with the in-loop history preserved. It is guarded, self-flagging, and pinned, but it is the only monkeypatch in the backend, and the program boundary (`_map_react_raise`) already maps the same exception classes — with one real difference: the mapper's result carries no history, the shim's does. **Addressed: `docs/specs/backend-simplification-2026-10.md` — handling moved to the program boundary, shim deleted.** | `app/agent/engine.py:177-231`, installed at `engine.py:369, 456`; boundary mapper `engine.py:163-174`; stream except-path `engine.py:402-412` | *"ReActV2 reserves `submit` as an internal tool."* and *"If the loop reaches `max_iters`, returns no calls, fails to parse, or exceeds the context window, ReActV2 makes one final LM call requesting `submit`."* <https://dspy.ai/current/diving-deeper/react/>; *"Missing or invalid submission raises ValueError; parse and context-window failures from the forced submission propagate."* <https://github.com/stanfordnlp/dspy/releases> |
| F2 | P2 | Engine | The shim's module walk handles direct attributes and dict values but not lists/tuples of modules, unlike DSPy's own `named_sub_modules` discovery. Harmless today (the probe confirms all three predictor roots are reachable; `evidence_agents` is a dict), fragile for future program shapes. **Addressed: evaporated with the shim's deletion.** | `app/agent/engine.py:184-201`; contrast `tests/test_fleet_agent_routing.py:96` | *"The tree-walk methods ... inspect `self.__dict__` at call time and recurse into lists and dicts as well as direct attributes."* <https://dspy.ai/current/diving-deeper/modules/> |
| F3 | P2 | Engine | Public termination reasons for forced-submit failures are extracted from the DSPy exception *message text* by regex. No structured alternative exists in 3.4; the fallback is the loop's `break_reason`, and the vocabulary is pinned by the termination-matrix tests. | `app/agent/engine.py:146-160, 223`; `tests/test_dspy_contract.py:223` | *"Missing or invalid submission raises ValueError; parse and context-window failures from the forced submission propagate."* <https://github.com/stanfordnlp/dspy/releases> (no structured reason field documented for the raise) |
| F4 | P1 | Gateway | Broad upstream surface: 13 `dspy.lm15` symbols, `LM15Engine` from `dspy.clients.engines`, and the private `dspy._vendor.lm15.transports` import. The `dspy.lm15` part is the release-documented public namespace; the engines/vendor ends are not covered by any documented surface and nothing currently fails CI if they move. **Partially addressed: `docs/specs/backend-simplification-2026-10.md` — the vendored/diagnostics seam is deleted entirely; the remaining public surface is guard-tested (CI fails loudly on a DSPy bump).** | `app/agent/gateway.py:14-29`, `app/agent/provider_diagnostics.py:17, 266-283` | *"3.4 is the LM transition release; 3.5 is the migration deadline."* <https://github.com/stanfordnlp/dspy/releases>; repo's own contract of record: `docs/backend-dependency-upgrade.md:47-51` |
| C4 | — | Provider | No additional finding. BYOK overrides are strictly validated with a fail-closed DNS-resolving SSRF guard, and keys are `SecretStr` end to end. | `app/agent/provider.py:55-150`, `app/agent/factory.py:42-94` | — |
| F5 | P2 | Program | The router's degrade path catches `(AdapterParseError, ValueError)` and silently returns `direct`. Fail-closed is right; silent is not — there is no log or metric distinguishing "model chose direct" from "router output was unusable", which will matter when promoted instructions misbehave. | `app/agent/program.py:171-183` | — |
| C2 | — | Program | No additional finding. Composition, routing, evidence budgeting, and history merging all hold the documented invariants (section 3.1). | `app/agent/program.py:44-169`, `app/agent/evidence.py:37-105` | — |
| F6 | P2 | Tools | Sync-only tool contract is correct for the current program (registration-time rejection, clear message), but it forecloses MCP tools, which are async by nature. The future path is known: async program entry (`aforward`/`acall` — the engine already uses `acall` semantics) plus `dspy.Tool.acall`. | `app/agent/tool_registry.py:300-304`, `app/agent/program.py:351-356`, async seam `app/agent/engine.py:379-387` | *"MCP tools are asynchronous because `mcp.ClientSession` is asynchronous. Use a module's async entry point, such as `acall`, or explicitly enable async-to-sync conversion when appropriate."* <https://dspy.ai/current/diving-deeper/tools/> |
| F7 | P2 | Tools | `write_report` truncates artifact content at a raw byte boundary; a multi-byte UTF-8 character split by the cap produces an invalid final character in the stored `.md`. | `app/agent/tools/report.py:63-64` | — |
| C5 | — | Tools | No additional finding. `TOOL_SPECS` single-table invariant, name agreement, bash PATH pinning (`/usr/bin:/bin:/usr/local/bin`, `--noprofile --norc`, minimal env), atomic writes, and prompt-injection wrapping of web content all verified. | `app/agent/tool_registry.py:73-252`, `app/agent/tools/workspace.py:70, 321-366, 476-530`, `app/agent/tools/web.py:36-68` | — |
| C6 | — | Safety | No finding. The two-list invariant holds: every `_SECRET_PATTERNS` prefix family is covered by `_STREAM_ANCHORS` (26 anchors; alternation variants checked by hand — see section 7 probe). The gap is that only convention + tests keep them from drifting. | `app/kernel/content_safety.py:25-55, 105-132`; probe output in section 7 | — |
| F8 | P2 | Contracts | Contract debt (admitted in the design doc): `RunStatus.interrupted` and termination reasons `approval_required`/`approval_expired`/`approval_invalid` have no producer; the sweep rewrites interrupted runs to `failed`/`server_restart`. Additionally the generated public schema description embeds the DSPy implementation term ("DSPy ReActV2 termination reason, e.g. ...") — the vocabulary is fine, the attribution is avoidable. | `packages/contracts/termination-reasons.json:12-14`, `apps/api/app/contracts/agent_state.py:16, 33`, `app/api/threads.py:31-40`, `app/persistence/repositories/runs.py:85-106`; admission `docs/dspy-agent.md:312-317` | — |
| C7 | — | AG-UI/persistence | No additional finding. Exactly-once terminal settlement is enforced by lock + flags across the completed/failed/cancelled/timeout/disconnect paths; terminal events are emitted even when both persistence attempts fail; `dspy_histories` never crosses to the browser; bootstrap state is re-sanitized before crossing the API. | `app/agui/live_coordinator.py:123-158, 182-248, 385-617, 620-641`; `app/persistence/run_persistence.py:329-475`; `app/api/threads.py:52-60` | — |
| C8 | — | Evals | No finding. The GEPA metric implements the full optimizer-facing signature and returns `dspy.Prediction(score, feedback)`; compilation uses exactly one budget knob with a required `reflection_lm`; the held-out split never touches GEPA (valset=train by design); gates require candidate > baseline AND min-accuracy, and byte-identical candidates are rejected so a depressed baseline cannot pass a no-op candidate. | `evals/agent_tool_routing.py:133-171, 184-215`; `evals/optimize.py:79-102, 180-252`; `evals/scoring.py:83-133` | *"GEPA expects the metric to returns a `dspy.Prediction(score=..., feedback=...)`."*, *"Exactly one of `auto`, `max_full_evals`, or `max_metric_calls` must be provided."*, *"The `reflection_lm` parameter is required"* <https://dspy.ai/current/api/optimizers/GEPA/overview/>; *"GEPA uses the trainset to perform reflective updates to the prompt, but uses the valset for tracking Pareto scores. If no valset is provided, GEPA will use the trainset for both."* <https://dspy.ai/current/api/optimizers/GEPA/overview/> |
| C8b | — | Evals | Agreement worth naming: the harness averages raw per-example metric values instead of `dspy.Evaluate`'s rounded percentage score, and surfaces provider failures (`failures`) separately because `failure_score` makes them indistinguishable from misses in the mean — both documented DSPy quirks, handled. | `evals/scoring.py:111-133`; `evals/run.py:168-175` | *"`score`: A float percentage score (e.g., 67.30)"*, *"When the metric raises (or returns `None`), `Evaluate` substitutes `failure_score` (default `0.0`) for that example and keeps going."* <https://dspy.ai/current/api/evaluation/Evaluate/> and <https://dspy.ai/current/diving-deeper/metrics-and-evaluation/> |

## 6. Prioritized recommendations

**P0 — Add upstream-surface guard tests so the next DSPy bump fails in CI, not at runtime.**
Extend the existing pattern in `tests/test_dspy_contract.py:29-44` (which already guards the ReActV2 alias) with: (a) an import-and-construct smoke of the exact symbols in the section 3.3 inventory (`dspy.lm15` names, `dspy.clients.engines.LM15Engine` subclass construction via `GatewayEngine`/`HostedEngine` config objects); (b) an existence check for `dspy._vendor.lm15.transports.StdlibTransport`; (c) an assertion that `_reason_from_react_exc` derives every public reason from the exact 3.4 message formats (extending `tests/test_dspy_contract.py:223`'s termination matrix to the regex path at `engine.py:146-160`).
Files to touch: `apps/api/tests/test_dspy_contract.py` (or a sibling `test_dspy_surface_guard.py`).
- Docs that force this: *"3.4 is the LM transition release; 3.5 is the migration deadline."* <https://github.com/stanfordnlp/dspy/releases>; *"Pin the DSPy version while using the experimental `ReActV2` name."* <https://dspy.ai/current/diving-deeper/react/>

**P1 — Consolidate forced-submit failure handling at the program boundary; delete the engine-side compat patch.**
(a) Catch `ValueError`/`AdapterParseError`/`ContextWindowExceededError` inside `FleetAgent.forward` around the gatherer call at `app/agent/program.py:108`, where the in-loop history is naturally in scope, and return the same failed-Prediction shape the shim produces today (answer=None, history preserved, termination_reason). (b) Delete `_install_forced_submit_compat` (`app/agent/engine.py:177-231`) and its two install sites (`engine.py:369, 456`). (c) Keep `_map_react_raise` (`engine.py:163-174`) as the single mapper for anything that still escapes. Acceptance criterion: failed runs must still persist their in-loop history server-side (today the shim's history-preservation feeds `run_persistence.py:468-474`; the consolidated path must not regress that), and the public termination vocabulary must be unchanged (`tests/test_dspy_contract.py:223`).
Files to touch: `apps/api/app/agent/program.py`, `apps/api/app/agent/engine.py`, `apps/api/tests/test_dspy_contract.py`, `apps/api/tests/test_dspy_engine.py`.
- Docs that force or permit this: the raise behavior is DSPy 3.4's public contract — *"Missing or invalid submission raises ValueError; parse and context-window failures from the forced submission propagate."* <https://github.com/stanfordnlp/dspy/releases> — and the docs' promised failure shape (history + termination reason, possibly without output fields) is exactly what the program boundary can return without touching a private symbol: *"If that attempt fails, the prediction still returns its history and a termination reason describing why the normal loop stopped, but it may not contain the declared output fields."* <https://dspy.ai/current/diving-deeper/react/> With the alias removal in 3.6 (R1), private-symbol shims are the first thing to break; after the 3.5 rename, re-verify whether `prediction.termination_reason`/`history` on failure makes the whole shim obsolete (R5).

**P2 — one-liners (each with a concrete, user-visible or operator-visible failure):**
1. Log (warning) + counter when the router degrades to `direct` (`app/agent/program.py:177-182`) — currently invisible; promoted-instruction regressions would look like ordinary direct answers.
2. Trim `write_report` truncation on a UTF-8 character boundary (`app/agent/tools/report.py:63-64`) — avoids a corrupted final character in downloaded artifacts.
3. Add the content-safety two-list drift check as a unit test (`app/kernel/content_safety.py:25-132`) — the streaming invariant silently depends on it.
4. On the next schema revision, mark `interrupted` and `approval_*` as reserved-for-future in `packages/contracts/termination-reasons.json` (or drop them with an explicit schema version bump) and reword the `terminationReason` description away from "DSPy ReActV2" (`apps/api/app/contracts/agent_state.py:33`).
5. When MCP/async tools become a requirement, enter via the async program path (program `aforward`, `dspy.Tool.acall`, `Tool.from_mcp_tool`) behind the existing engine `acall` seam — do not enable `allow_tool_async_sync_conversion` implicitly for the sync loop: *"The conversion is explicit because driving an async tool from an existing event loop can deadlock in some environments."* <https://dspy.ai/current/diving-deeper/tools/>
6. (Conditional) F2's list-walk gap evaporates with the P1 consolidation; only revisit if the shim survives.

## 7. Validation appendix

All commands run from `apps/api` with `FLEET_AGENT_ENV_FILE=/dev/null` (the app's `.env` was never read) and `FLEET_AGENT_DATABASE_URL=postgresql+asyncpg://fleet:fleet@localhost:5432/fleet_agent_test` where a database is involved.

**Baseline (Phase A):**

- `uv sync --locked --all-groups` → `Resolved 167 packages ... Checked 162 packages` (no changes).
- `pg_isready -h localhost -p 5432 -U fleet` → accepting connections; `uv run alembic upgrade head` → clean.
- `uv run pytest -q` → **610 passed, 1 skipped, 1 warning in 60.77s**. The skip is the paid/live-provider opt-in smoke; the warning is MLflow's upstream `SADeprecationWarning: The ``noload`` loader strategy is deprecated` (`mlflow/store/tracking/utils/sql_trace_metrics_utils.py:155`) — both preexisting and documented as known-green exceptions.

**DSPy module-tree probe (run once, output verbatim):**

```text
dspy 3.4.0
is_module True
['router', "evidence_agents['research'].react", 'synthesizer']
```

**Offline eval harness validator:** `uv run python -m evals.run --suite routing --validate` → `routing dataset: 45 examples validated`, exit 0 (twice: baseline and final).

**Secret-anchor invariant probe** (pattern roots vs `_STREAM_ANCHORS`):

```text
pattern roots:
  -----BEGIN [A-Z0-9 ]*PRI...   → anchor "-----begin"      (PEM)
  sk                            → anchor "sk-"             (+ ant-/or- variants)
  AKIA / AIza                   → anchors "akia" / "aiza"
  gh                            → anchors ghp_/gho_/ghu_/ghs_/ghr_  (char class expansion)
  github_pat / xox / eyJ / Bearer → anchors as listed
  (?:api[_-]?key|apikey|...     → apikey/api_key/api-key, secret, access*/auth* separator
                                   variants, password/passwd/pwd — all enumerated
anchors: 26
```

**Final validation (Phase E, re-run immediately before commit):**

- E1 `uv run pytest -q` → **610 passed, 1 skipped, 1 warning in 53.41s** — identical counts to baseline; the review ships.
- E2 `uv run python -m evals.run --suite routing --validate` → `routing dataset: 45 examples validated`, exit 0.
- E3 `git status --porcelain` after commit → only the pre-existing untracked `.hermes/` plan directory remains; `git diff --check` clean.
- E4 Every URL cited in this document is one fetched during review (section 3/4/6): the six `https://dspy.ai/current/...` pages, plus `https://github.com/stanfordnlp/dspy/releases`. No invented URLs.

**Sources (all accessed 2026-10-07):**

- <https://dspy.ai/current/diving-deeper/react/>
- <https://dspy.ai/current/diving-deeper/modules/>
- <https://dspy.ai/current/diving-deeper/tools/>
- <https://dspy.ai/current/tutorials/streaming/>
- <https://dspy.ai/current/api/utils/streamify/>
- <https://dspy.ai/current/api/evaluation/Evaluate/>
- <https://dspy.ai/current/diving-deeper/metrics-and-evaluation/>
- <https://dspy.ai/current/api/optimizers/GEPA/overview/>
- <https://github.com/stanfordnlp/dspy/releases>
