# Spec 003 - Evidence continuity and outcome

Status: implemented; browser release acceptance pending. Implementation baseline: `a6197e4`; original review baseline: `8b87caf`.

## Implementation delivered

Routing receives bounded selected-branch conversation context, newest turns first. Synthesis prioritizes newer tool observations, retains safe evidence attribution, and records truncation. Gatherer completion and synthesis completion remain distinct. Public evidence status and stop reason survive persistence and appear in the UI. Compound requests and branch-local report follow-ups have a separate development corpus and untouched promotion holdout.

See [implementation status and validation](implementation-status-2026-10-09.md) for commands, measurements and remaining checks. The original proposal below explains the design; the delivered behavior above records the current implementation.

Specification index | Review pages

## Original problem and baseline behavior

Routing sees only current request text. Evidence is serialized from accumulated history into a bounded prefix. The final prediction labels termination as synthesis, without preserving the gatherer reason. These choices can make follow-ups under-specified, omit current corrections and hide partial evidence collection.

Sources: program.py, evidence.py, engine.py.

## Desired behavior

Routing receives bounded, branch-local conversational context. Synthesis receives current relevant observations plus explicitly needed prior evidence. The result distinguishes successful synthesis from complete, partial or insufficient evidence gathering.

## Invariants

- Private DSPy history remains server-side; public explanations are deliberately written summaries.

- Current corrective evidence cannot be crowded out solely because older observations filled the budget first.

- Evidence JSON is always valid and bounded; preserve the existing valid-JSON guarantee.

- Invalid routing remains permission-safe and retains a diagnostic/degraded signal.

- Gatherer failures cannot disappear merely because a synthesis call returns valid text.

## Minimal implementation

Pass a bounded conversation summary or recent relevant turns into the routing signature. Separate raw decision validity from the coerced fallback route. Partition current-run observations from older history before selecting evidence; preserve stable source/tool-call IDs and a deterministic truncation record. Avoid a vector database or another agent for this first iteration.

Carry a plain application-level evidence outcome and original normalized stop reason through `AgentRunResult`. Define when to synthesize a partial answer and when to return an insufficiency explanation. A future model-based sufficiency checker must not replace deterministic error and authorization handling.

## Contract and frontend

Version the public quality/limitation fields using the shared schema. The answer and run banner disclose partial or insufficient evidence without showing raw exception messages or internal thoughts. Source references resolve to records accessible in the selected branch.

## DSPy and evaluation

Use controlled histories containing old claims and newer corrections. Include request-only versus contextual routing comparisons, parse-error fallback and forced-stop cases. Report omission of required evidence, unsupported success claims, task completion, tokens and latency. Any improvement claim must be measured against the old implementation on the same cases.

## MLflow and fixtures

Log evidence selection counts, truncation status, normalized outcome and version metadata. Do not log raw user documents or hidden history by default. Create fixtures for a follow-up, a correction near the budget boundary, and a partial result.

## Acceptance tests

- "Use the newer file, not the old result" includes the newer evidence even after a long history.

- "Create a report from that" resolves the selected branch, not a sibling branch.

- Budget-boundary outputs parse as JSON and retain stable evidence attribution.

- A malformed router result never grants additional tools and never implies successful external verification.

- A gatherer max-iteration/context/parse stop remains observable after synthesis.

- Streamed and restored caveats agree, with no private reasoning in either surface.

## Non-goals

No automatic long-term memory store, unbounded history, or universal second-model critic.
