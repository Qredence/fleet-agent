# Spec 002 - Compound tasks and managed output

Status: implemented; browser release acceptance pending. Implementation baseline: `a6197e4`; original review baseline: `8b87caf`.

## Implementation delivered

Routing selects evidence capabilities and managed output intent in the same DSPy prediction. Managed export runs once after synthesis through application orchestration, independently of workspace write permission. Run/output-slot identity is deterministic. Storage or artifact metadata failure preserves the answer and publishes a failed artifact without a download URL. Bootstrap associates artifacts with their owning run and message.

See [implementation status and validation](implementation-status-2026-10-09.md) for commands, measurements and remaining checks. The original proposal below explains the design; the delivered behavior above records the current implementation.

Specification index | Review pages

## Original problem and baseline behavior

`artifact` exposes research and report creation. Workspace profiles expose research and workspace tools, but not report creation. The program selects exactly one profile. A task needing workspace evidence plus a managed report cannot access both through the current composition.

Sources: factory.py, `build_tool_profiles`; program.py, `forward`.

## Desired behavior

A user can request "Inspect the workspace and create a managed report" as one task. Evidence gathering uses the minimum authorized workspace profile; managed report export is a separately authorized output action after synthesis. The report cites the evidence actually gathered.

## Invariants

- Requested capabilities, configured availability and authorization remain distinct.

- Only deterministic application policy decides which tools/actions may execute.

- Denying workspace writes or shell access must not prevent a read-only inspection and allowed managed export.

- A report cannot claim a source was inspected when it was not.

- Retried delivery/export must not duplicate artifact records or silently overwrite unrelated artifacts.

## Minimal design

Retain evidence routing and add a bounded output intent, rather than introducing a generic planner or every possible profile combination. Reuse the existing report storage, validation and event machinery outside the mutually exclusive evidence choice. Synthesis can supply report content from the same evidence; avoid an extra LM call when the answer already contains the report.

A tactical combined profile is permitted only as a small documented step with the same tests. Do not expand route rank assumptions into authorization logic.

## Contract and frontend

Represent managed-output request/status through the existing artifact lifecycle, extending generated contracts only where needed. Return stable artifact and source references. The transcript shows artifact progress/ready/failed; the inspector and restored branch refer to the same record.

## DSPy evaluation

Add deterministic tool doubles for read-only workspace inspection, research plus report, missing required tool, denied mutations and export failure after a useful answer. Update capability sufficiency scoring to use actual sets. Exact route match, task success and authorization invariants are separate measurements.

## MLflow and fixtures

Record selected evidence profile, requested output kind, export status and program version as safe metadata. Fixture scenarios must exercise combined capabilities rather than merely show a prebuilt artifact card.

## Acceptance tests

- One task reads known workspace content and produces one managed artifact containing the expected grounded finding.

- No write/edit/bash tool is exposed when not approved.

- An unavailable evidence capability yields a clear limitation, not fabricated inspection.

- A follow-up "make that a report" uses the correct branch evidence.

- Export failure keeps the answer, marks the artifact failed and never shows a ready download.

- Repeated export settlement is idempotent for the same run/output identity.

- Reload and branch switching preserve the correct report and source associations.

## Non-goals

No arbitrary generated agent graph, no new artifact service, no automatic permission escalation.
