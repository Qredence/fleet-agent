# Live acceptance and safe tracing

Status: accepted. Baseline: current uncommitted staged implementation on a6197e4.

Validate the browser-selected Command provider, not the backend default. Use an
isolated engine service/database/workspace for three repetitions of twelve
versioned task scenarios and scoped failure probes. The normal backend remains
on 8001; validation uses 8002 and the existing frontend origin/provider storage.

## Invariants and interfaces

No public contract changes. No production fault endpoints. Provider credentials
remain browser-owned and travel only through the existing agent request headers.
Reports contain safe configuration and IDs, never keys or raw provider exchanges.
All 36 scenario executions must pass on the same final source/configuration.
Browser evidence is required; an access denial blocks UI acceptance.

Native MLflow DSPy autologging can record exception events and status details
beyond the span processor's mutable public fields. Replace that capture path
with a DSPy callback using supported manual MLflow spans. Export constant names,
operation types, timings, and OK/ERROR status only. Never pass inputs, outputs,
instance names, exception values, stack traces, or user-defined metadata to the
span API. Observability failures cannot fail execution. Tracing stays opt-in.

## Acceptance repair: workspace attribution

Live read tools produced grounded answers but no source entity. A successful
bounded workspace read must publish a scrubbed workspace source through the
existing last_sources callback mechanism. Failed/empty reads must clear stale
sources. Sources use the existing repository source type, a relative title, and no
navigable filesystem URI. The live restoration check exposed an invalid source
type; generated-contract validation now guards this projection. Existing
source/card/persistence contracts remain unchanged.

## Acceptance repair: managed report presentation

A live answer claimed attachments were unavailable despite a ready managed
artifact. Give synthesis the validated output intent through an internal input;
request report contents without premature save claims or manual-save advice.
Keep artifact success/failure authoritative and independent of answer generation.
Record the observed baseline mismatch and rerun provider-backed acceptance.

## Acceptance repair: authenticated downloads

The browser's direct artifact link returned Unauthorized although authenticated
preview worked. Download through the existing API header boundary, then use a
local Blob download; never put keys in URLs. Offer only controlled artifact paths,
disable the action while pending, and expose failures without changing ready
artifact truth. Cover authentication, filename, failure, and actual browser
file contents before restarting the frozen matrix.

## Acceptance repair: evidence recency provenance

Live synthesis treated a prior-turn pre-write read as conflicting with a current
write and confirming read. Pass a current-run boundary and stable observation
indices into bounded evidence JSON; retain newest-first order and label prior
observations explicitly. No public or persistence contract change. Regression
coverage must distinguish old/current reads and preserve JSON limits.

## Acceptance repair: edited branches

The existing queued-parent dependency patch interpreted explicit root edits as
continuations and deleted their source user message. Narrow that patch: preserve
source messages and explicit root parent for edit; retain head fallback for normal
queued sends. Validate through the public runtime and live branch selector, both
before and after reload. No dependency version upgrade or backend schema change.

## Acceptance and validation

Inspect exported traces from normal/failing operations containing synthetic
private markers. Verify events are absent and names/status descriptions cannot
contain those markers. Test unavailable/disabled stores and concurrent callbacks.
Use pytest, web tests/build/lint, Ruff, mypy, deptry, contract freshness, and
Browser live/restored acceptance. Do not promote optimization candidates.

### Synthesis formatting acceptance repair

A live Command follow-up report failed output parsing after an otherwise usable
first turn. Keep the native ChatAdapter and its no-retry-after-visible-output
rule. Reinforce the existing four-field output format in the synthesis prompt,
including JSON arrays and empty sections. Never retry tools to repair malformed
synthesis. Record the failed diagnostic attempt and restart the complete live
matrix after this prompt change; a successful manual retry is not a case pass.

## Final acceptance — 2026-10-09

All 36 live scenario assertions passed on the frozen application implementation
and Command configuration. The 36 scenarios contain 63 underlying runs; follow-ups
and edits stay on their case branches, and each concurrent pair counts once.
The source freeze fingerprint is recorded in the evidence manifest. Subsequent
changes were limited to evidence/scripts/docs and Ruff quote formatting in one
test; no application behavior or provider configuration changed during the matrix.

The isolated failure matrix passed: first-commit retry, exhausted retries,
idempotent duplicate settlement, cancellation, disconnect before/after completion,
file and metadata artifact failures, feedback write failure/recovery, legacy
saved/unknown normalization, and conflicting history writes/head advancement.
The synthetic private exception ran after a genuine provider response. Metadata
trace exports excluded all five planted/private markers, exception events, stack
traces, inputs, outputs, and status descriptions. Disabled and unavailable MLflow
both preserved genuine-provider answers and terminal persistence. No optimization
or promotion ran. Existing optimizer outage/local-manifest tests remain regression
coverage; no optimization was started merely to validate observability.

See implementation-status-2026-10-09.md and the bounded evidence directory for
individual results, exact commands, provider configuration, usage, and limitations.
The engine E2E harness now waits for a distinct follow-up artifact and validates
zero follow-up tool calls. Its alternate-browser workflow was not executed; the
required browser acceptance used only the permitted in-app Browser.
