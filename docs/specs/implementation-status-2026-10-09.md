# Fleet Agent implementation status — 2026-10-09

Baseline: a6197e4. Original review: 8b87caf. Existing user edits and document deletions were preserved. No dependency upgrade, experimental DSPy decision API, or optimization promotion was performed.

## Delivered behavior

- Text-only capabilities and request/history validation. Unsupported mixed content is rejected before reservation/provider construction; historical images explain the limitation. Text files remain supported.
- Workspace and bootstrap schema version 2. Execution outcome and saveStatus are independent. Terminal persistence is authoritative, retries are bounded, legacy snapshots normalize server-side, and frontend history writes cannot replace terminal truth. Failed saving preserves the answer with copy and Markdown download.
- Run-scoped synthesizers; overlapping providers, histories, cancellation and usage attribution have regression coverage.
- Branch-local bounded routing context, separate decision validity and permission-safe fallback, recent-first attributed evidence, truncation and partial/insufficient outcomes.
- Deterministic managed Markdown export after synthesis; stable run/output identity, failed artifact state on storage or metadata failure, and no workspace write permission requirement.
- Closed versioned card schemas, generated Python/TypeScript, runtime validation, safe unknown-card fallback, restored settled cards, source/artifact references and owning-run activity.
- Explicit approval controls consume/reset the next-run selection. Server configuration and policy remain authoritative before model construction.
- PostgreSQL-backed message feedback with server-derived run/branch associations, React Query restoration, update/removal, and visible errors. Migration: 8d62b1f0c934_message_feedback.
- Separate routing exactness, validity, capability sufficiency, unnecessary exposure, intent and authorization metrics. Expanded development/promotion groups remain disjoint. Rejected optimization candidates retain local bounded reports/configuration/manifests.
- Metadata-only MLflow spans replace native DSPy content capture. Inputs, outputs, exception events/details, private names and status descriptions are excluded; tracing/export outages do not control runtime behavior.

## Final live acceptance

**Passed: 36/36 scenarios (12 cases × 3 repetitions)**, using the frontend's
existing **Command** profile. The browser request middleware verified each run's
request-scoped override: model `deepseek/deepseek-v4.1-flash`, endpoint
`https://api.commandcode.ai/provider/v1`, response format `json_tool_calls`, and
message format `system_role`. Credentials and the existing profile were preserved.

Application baseline HEAD: `a6197e444659488b21914788a15e68c48fa23bc3` with the
uncommitted implementation and acceptance repairs. Frozen source fingerprint:
`1ff2062314960129ebca0e134f5d42f943adcfef78a32e1d6cac666ac4ae2aad`.
No application behavior changed during the final matrix. After it completed,
Ruff changed quote formatting in one test; documentation and isolated validation
scripts were also finalized. Those mechanical changes did not change execution.

| Case | Repetition 1 | Repetition 2 | Repetition 3 |
| --- | --- | --- | --- |
| Plain text / terminal saving | Pass | Pass | Pass |
| Text attachment / reload | Pass | Pass | Pass |
| Unsupported inputs / historical explanation | Pass | Pass | Pass |
| Workspace facts / source attribution | Pass | Pass | Pass |
| Inspection plus downloaded report / restoration | Pass | Pass | Pass |
| Branch follow-up report without tools | Pass | Pass | Pass |
| Corrected branch / sibling exclusion | Pass | Pass | Pass |
| Unavailable capability / insufficient evidence | Pass | Pass | Pass |
| Approval reset, regeneration and edit withholding | Pass | Pass | Pass |
| Concurrent pair / cancellation isolation | Pass | Pass | Pass |
| Feedback update, failure, recovery, branches, removal | Pass | Pass | Pass |
| Settled cards, links, keyboard, 390px inspector | Pass | Pass | Pass |

The matrix contains **63 underlying runs**: 60 primary runs plus three concurrent
peers. Unsupported-input scenarios reserved zero runs. Available provider usage:
312,287 prompt tokens + 44,910 completion tokens = **357,197 total tokens**.
Three cancelled runs have no provider usage. Primary-run mean latency: **8.72s**;
range **1.30–25.40s**. These totals cover the final matrix, not diagnostic attempts,
61 routing evaluation examples, or additional failure probes. Exact provider HTTP
call count and account-wide remaining usage were not available.

[Individual matrix results](live-acceptance-evidence-2026-10-09/matrix-results.json),
[browser observations](live-acceptance-evidence-2026-10-09/browser-evidence.json), and
[safe provider request metadata](live-acceptance-evidence-2026-10-09/requests.ndjson)
correlate thread/run IDs. Actual downloaded report contents matched stored files.
Branch follow-up reports executed zero tools; corrected reports included Larch/900
and excluded Cedar/100. Only approved runs executed write; model construction
withheld unapproved privileged tools. Browser automation was permitted in this
run, resolving the earlier access block.

## Acceptance repairs

- Explicit safe metadata tracing through supported DSPy callbacks and MLflow spans.
- Scrubbed relative workspace source attribution using the existing repository enum.
- Managed report intent and stable four-field synthesis formatting.
- Authenticated artifact downloads through the existing API header boundary.
- Newest-first evidence with current-run/prior-turn provenance.
- Version-specific assistant-ui patch preserving edited root branches and prior
  queued-parent/resume fixes, without a dependency upgrade.
- Message renderer identity reset on branch switch.

A diagnostic report follow-up hit an AdapterParseError before the synthesis-format
repair. Its manual regeneration did not count as a pass. The complete matrix was
then restarted in a fresh project. Earlier diagnostic results are excluded.

## Failure and privacy gates

Passed with genuine provider execution on isolated engine port 8002:
terminal retry success, two exhausted retries with preserved answer/copy/download,
duplicate settlement, cancellation, disconnect before and after accepted completion,
artifact file/metadata failures, feedback failure/recovery, legacy v1 saved/unknown
normalization, and frontend history-write/head-advance conflicts. Failed artifacts
restored without a download control. Saving failures remained independent from
completed execution. No tools were re-executed to recover saving/export failures.

The private-exception fault ran after genuine synthesis. The browser saw only a
safe run error. **965 exported metadata traces/spans** were inspected: 497 module,
334 LM, 134 tool; 951 OK and 14 ERROR. All five marker checks passed; inputs,
outputs, exception events, stack traces and status descriptions were absent.
MLflow enabled, disabled and unavailable cases passed. Tracing remains disabled
by default. Existing optimizer local-manifest/outage tests passed; no optimizer
or promotion was run.

[Failure browser evidence](live-acceptance-evidence-2026-10-09/failure-browser.json),
[persistence checks](live-acceptance-evidence-2026-10-09/failure-persistence.json),
[availability checks](live-acceptance-evidence-2026-10-09/availability-and-continuation.json),
and [privacy audit](live-acceptance-evidence-2026-10-09/trace-privacy-results.json).

## Validation commands and results

Commands run from repository root unless prefixed with `apps/api`.

| Command | Result |
| --- | --- |
| apps/api: `uv run pytest -q` | 560 passed, 1 skipped, 1 upstream deprecation warning; 51.61s |
| `pnpm test:web` | 33 files, 227 tests passed |
| `pnpm build` | Passed; bundle-size warning |
| `pnpm lint` | Passed; one redundant-spread warning |
| apps/api: `uv run ruff check .` | Passed |
| apps/api: `uv run ruff format --check .` | Passed, 160 files |
| apps/api: `uv run mypy app` | Passed, 90 source files |
| apps/api: `uv run deptry .` | Passed, 100 files |
| Generated Python/TypeScript freshness suites | Passed within backend/web tests |
| `apps/api/.venv/bin/ruff check scripts/live_acceptance*.py` | Passed |
| `bash -n scripts/e2e-engine.sh scripts/e2e-fixtures.sh` | Passed |
| `git diff --check` | Passed |

Isolated validation commands (from apps/api, with existing API authentication):

```sh
PYTHONPATH=.:../../scripts .venv/bin/python ../../scripts/live_acceptance_admin.py setup
PYTHONPATH=.:../../scripts .venv/bin/python ../../scripts/live_acceptance_inputs.py
PYTHONPATH=.:../../scripts .venv/bin/python ../../scripts/live_acceptance_persistence.py audit
PYTHONPATH=.:../../scripts .venv/bin/python ../../scripts/live_acceptance_persistence.py duplicate
PYTHONPATH=.:../../scripts .venv/bin/python ../../scripts/live_acceptance_verify.py
PYTHONPATH=.:../../scripts .venv/bin/python ../../scripts/live_acceptance_traces.py
```

These commands require the isolated resources and recorded browser case evidence;
cleanup intentionally removes the disposable database/workspace. Never run seed
or fault operations on the normal service. The isolated wrapper consumes an
explicit thread/run/stage fault manifest; no production fault API was added.
The wrapper's one-shot `evaluate.flag` uses the next actual browser provider
override for 45 routing and 16 product examples. Backend-default CLI evaluations
were not counted as frontend-provider acceptance. The E2E shell harness was
adapted, syntax-checked, and not executed through its alternate browser path.

## Command-provider routing measurements

| Metric | Routing (45) | Product regression (16) |
| --- | --- | --- |
| Exact route | 44/45 (97.78%) | 16/16 (100%) |
| Invalid output | 0 | 0 |
| Capability sufficiency | 100% | 100% |
| Unnecessary selection | 2/45 (4.44%) | 0 |
| Authorization failures | 0 | 0 |
| Output intent | No intent labels in this corpus | 16/16 (100%) |
| Mean latency | 2.00s | 1.85s |
| Provider failures | 0 | 0 |

Earlier Command measurement: 43/45 exact routing and 16/16 product regression.
The router was not optimized between samples; differences are sampling variation,
not an improvement claim. End-to-end task success is reported separately above.
Previously inspected promotion examples are now regression evidence. Future
promotion requires a fresh untouched holdout.

## Feedback curation

Feedback never enters automatic training. Offline curation must explicitly select owner-authorized examples, remove private content, review labels, record corpus revision/digest and source-message provenance, group related branch examples, and assign immutable train/development/promotion splits. Promotion holdout examples must not reach optimization.

## Remaining limitations and environment restoration

- One exact-route mismatch and two unnecessary selections remain in the routing
  corpus; they did not cause authorization failures or final task failures.
- Unapproved regeneration sometimes summarizes the already-approved prior write
  as “Done”; the current run executes only read, and its public evidence status
  remains insufficient. The approved content is unchanged.
- Failed artifact restoration displays a cosmetic `null B` size label; no download
  is offered. Neither issue changed the defined acceptance invariants.
- The skipped backend smoke test is opt-in; the separate Command browser matrix
  supplies actual live acceptance. Build/lint and upstream deprecation warnings
  are retained above.
- No automatic optimization/training/promotion, commit, deployment, or new public
  contract change was performed for these acceptance repairs.
- Normal engine port 8001 and frontend port 5173 are restored after validation.
  The temporary 8002 service, validation database, workspace, artifact store,
  trace store, fault controls and secret-bearing environment file are removed.
  Bounded safe evidence remains under the linked evidence directory.
