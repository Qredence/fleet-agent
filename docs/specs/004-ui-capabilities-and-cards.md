# Spec 004 - Honest UI capabilities and shared cards

Status: implemented; browser release acceptance pending. Implementation baseline: `a6197e4`; original review baseline: `8b87caf`.

## Implementation delivered

Both modes advertise text support. Image adapters are removed; the composer announces rejected attachments and rejects mixed unsupported paste/drop events. Both execution and message persistence reject unsupported modalities before reservation/provider creation. Historical images retain an unsupported-input explanation. A closed version-2 shared card contract validates live envelopes; bootstrap restores settled search, source and artifact references. Approval selection is explicit, defaults to none, resets on sending, and is replaced rather than reused for retry/regeneration. Inspector links support the mobile sheet and keyboard controls.

See [implementation status and validation](implementation-status-2026-10-09.md) for commands, measurements and remaining checks. The original proposal below explains the design; the delivered behavior above records the current implementation.

Specification index | Review pages

## Original problem and baseline behavior

Image attachments are offered by the runtime, but the execution extractor handles text only. Inline Data UI payloads have local handwritten parsers. Approval is supported at the backend boundary, but a frontend sender was not found in the inspected runtime/search results.

Sources: runtime provider, input extraction, inline cards, approval.

## Desired behavior and delivery slices

A. Advertise and enforce supported input modalities. Ship this first.

B. Add an explicit pre-run permission selection using the existing tool metadata and request property. Verify the full UI sender path before changing it.

C. Formalize the existing inline cards as bounded, versioned shared contracts; do not add new card kinds in the same change.

Each slice should be a separate reviewable PR with its own browser test.

## Invariants

- The UI does not imply an unsupported image reached the agent.

- Server validation remains authoritative even when the UI hides unsupported controls.

- Approval defaults to none, is explicit for the current run, and never comes from model confidence.

- The model cannot define arbitrary React, JavaScript, navigation or authentication behavior.

- Process state remains in AG-UI; layout state remains local; no new mutable execution-state mirror is introduced.

## Contracts

Extend the capabilities schema for accepted content types and limits. Add a closed discriminated schema for existing Data UI kinds, with stable entity/run/message references, version, bounded data and safe fallback semantics. Generate backend/frontend types and runtime validation using the established tooling.

Define which card state is durable in bootstrap. Prefer stable references into the authoritative public projection; transient events alone are not restored state. Provide migrations for older serialized card/snapshot versions.

## Frontend behavior

Use the existing assistant-ui registrations and ordinary React components. Unsupported inputs are hidden or explained before submission. An unknown card version does not break the answer. Source selections open the corresponding authorized inspector record. Historical activity does not restart when a newer run is active.

Pre-run approval lists named capabilities and warns about mutations. Hosted deployments must intersect the selection with server-owned principal permissions; the existing single-local-owner model must not be silently generalized.

## DSPy, MLflow and tests

No optimizer is required for the UI contract itself. Track safe schema rejection codes, not raw malformed payloads. Add fixtures for image rejection, denied approval, malformed and future-version cards, stable source linking and restored activity.

## Acceptance tests

- Image-only and mixed unsupported inputs yield a visible stable error; no silent text-only substitution.

- Denied tools are absent from the constructed program, including after a malformed approval request.

- All current card fixtures validate against generated contracts in Python and TypeScript.

- Unknown kinds/versions preserve the answer and show a safe fallback.

- Old completed-run cards remain settled while a new run is active.

- Live, reloaded and branch-selected views reference the same sources/artifacts.

- Keyboard focus, status announcements and small-screen inspector access work in the fixture browser journey.

## Non-goals

No second UI protocol, arbitrary model-generated page layout or private DSPy pause/resume fork.
