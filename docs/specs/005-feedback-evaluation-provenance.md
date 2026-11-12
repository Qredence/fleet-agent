# Spec 005 - Feedback and evaluation provenance

Status: implemented; browser release acceptance pending. Implementation baseline: `a6197e4`; original review baseline: `8b87caf`.

## Implementation delivered

Feedback is an owner-scoped message resource with server-derived run, branch and program identity. PUT/DELETE are idempotent; optional reasons are bounded and scrubbed. React Query restores feedback and presents update/removal errors. Feedback is not consumed by training. Completed optimizer attempts retain local manifests, bounded configuration, reports and failure summaries, including rejection and provider failure. Expanded optimization uses grouped development data and a separate final holdout. MLflow spans exclude execution content and retain bounded operational metadata; local reports survive MLflow outages.

See [implementation status and validation](implementation-status-2026-10-09.md) for commands, measurements and remaining checks. The original proposal below explains the design; the delivered behavior above records the current implementation.

Specification index | Review pages

## Original problem and baseline behavior

Feedback is stored in memory only. Routing utility is exposed as accuracy and uses numeric route rank despite non-nested capabilities. Failed optimization gates record metrics but generally not the full candidate report/configuration.

Sources: runtime provider, routing metric, optimizer, tracking.

## Desired behavior

Persist useful user feedback and curate it into versioned examples. Evaluate exact prediction correctness, actual task sufficiency and safety separately. Keep a reproducible report for every completed optimizer attempt without auto-promoting it.

## Invariants

- Feedback is tied to the correct message, run and branch; retries do not create accidental duplicates.

- User feedback is not automatically labeled ground truth or sent to an optimizer.

- Invalid route output is counted as invalid rather than silently rewarded after coercion.

- Required capability containment is checked against real tool metadata, not an assumed total order.

- Promotion holdout examples never enter optimizer training or selection.

- Evaluation and MLflow failures cannot authorize live changes.

## Contracts and frontend

Add a small authenticated/owner-scoped feedback API and persisted record with bounded optional reason, message/run identity, and program version. Restore feedback on bootstrap or resource fetch and surface save failure. Use existing REST state ownership; do not place evaluation state inside the live AG-UI execution store.

Use explicit metric names: exact match, invalid-output rate, capability sufficiency, over-selection and task success. Retain weighted utility only under that name. Treat unauthorized exposure/execution as a hard test failure.

## Dataset and optimization changes

Add compound and multi-turn cases first. Split by task/thread/repository to avoid near-duplicate leakage. Introduce train/development/final promotion separation when the expanded dataset supports it; retain the current held-out isolation until then.

Every completed optimization attempt writes a bounded manifest, candidate configuration, report and failure summary. Include git revision, model/config identity, DSPy version, program fingerprint, dataset digest and split IDs. Log passing and rejected attempts to the existing MLflow experiments; an unavailable tracker must leave local reports usable.

## Trace privacy

Operational metadata is the default. Detailed prompt/completion traces require separately documented opt-in, access control, redaction and retention. Do not expose raw trace payloads through the frontend or attach secrets to candidate manifests.

## Acceptance tests

- Feedback survives reload and remains attached to the intended branch/message.

- Feedback retry/update is idempotent for the chosen record identity.

- An artifact-required case predicted as workspace-only is correctly marked insufficient.

- Malformed predictions are reported separately and cannot receive exact-match credit through fallback coercion.

- Failed promotion gates still retain the candidate manifest and report.

- A corrupted or incompatible activated artifact is rejected with an operator-readable error.

- A deliberately failing safety case blocks promotion regardless of the mean quality score.

- MLflow outage does not delete the local evaluation report or change live behavior.

## Non-goals

No autonomous online self-training, feedback-as-truth shortcut, or new observability platform.
