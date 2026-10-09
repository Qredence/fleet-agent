# Spec 006 - DSPy runtime simplification and optional decisions

Status: implemented; browser release acceptance pending. Implementation baseline: `a6197e4`; original review baseline: `8b87caf`.

## Implementation delivered

The YAML agent language and private forced-submit patch were already removed at baseline a6197e4. Mutable synthesizer modules are now run-scoped; immutable signature definitions remain cached. Provider/history/usage overlap tests cover isolation. Public fields, callbacks, streaming and cancellation mechanisms are retained. Jev and ReAnchor remain deferred and have not been added.

See [implementation status and validation](implementation-status-2026-10-09.md) for commands, measurements and remaining checks. The original proposal below explains the design; the delivered behavior above records the current implementation.

Specification index | Review pages

## Original problem and baseline behavior

The synthesizer builder returns a cached mutable Module shared by run-scoped programs. The engine patches private forced-submit behavior. A custom YAML module dialect duplicates some native DSPy structure while routing and evidence transformation remain in Python.

Sources: signature.py, engine.py, spec schema.

## Desired behavior

Create a clearly run-isolated native DSPy program from immutable definitions. Keep one small supported runtime boundary, removing private compatibility and unused abstractions when behavior tests permit. An optional Jev/ReAnchor experiment must be independently gated and must not block this simplification.

## Invariants

- Runs with different providers/histories cannot mutate one another's predictors or stream attribution.

- All public events and safe output fields preserve the same contract during the refactor.

- DSPy callbacks, usage tracking and MLflow callback composition remain active.

- No generic framework or new private ReAct fork replaces the existing code.

- Experimental decision types stay internal; authorization remains deterministic.

## Implementation slices

A. Cache immutable prompt/spec definitions only; create run-scoped predictor/module instances. Add overlapping-run tests before changing lifetime rules.

B. Characterize supported locked-version termination behavior. Remove the private patch where possible; otherwise isolate a single documented compatibility shim with tests and an explicit removal criterion. Do not silently catch unrelated provider failures as normal partial answers.

C. Inventory YAML dialect uses. Keep real configuration needs; replace unused generality with direct typed Signature/Module composition. A requirements spec does not require a runtime graph language.

D. Optional experiment after the baseline: choose either a decision-typed capability selector or an evidence-sufficiency decision. Keep the old predictor available. Pin experimental behavior and use independent calibration/development and final holdout data.

## Contracts and frontend

No frontend DSPy imports or experimental types. Any selected decision is normalized to a plain domain result and the already-approved public schema. Show evidence limitations, not raw model confidence as a truth guarantee.

## DSPy evaluation and MLflow

Measure task quality, false-sufficient evidence judgments, invalid output, latency and request/token cost. Log model, dataset, prompt/program, calibration and dependency identities for every experiment. Do not label an unmeasured migration as faster, cheaper or better calibrated.

Official implementation references, checked October 8, 2026: Jev decisions, ReAnchor. These APIs are experimental; verify against the lockfile.

## Acceptance tests

- Two interleaved runs with different providers and histories retain isolated configuration, streams and usage attribution.

- Cancelling one run cannot cancel or contaminate the other.

- Streaming and non-streaming paths produce equivalent safe final fields.

- Forced/partial/error termination remains correctly normalized with no dependence on unrelated exception wording.

- Callback composition still permits opt-in MLflow tracing without making tracing a runtime dependency.

- Removed dialect features have no remaining callers; behavior fixtures pass without a second replacement DSL.

- An optional decision experiment is activated only after passing the same quality/safety/budget gates on the final holdout.

## Non-goals

No broad dependency upgrade, Flex program evolution, always-on critic or simultaneous migration to a new execution framework.

## Reconciled implementation status

The YAML dialect and private forced-submit patch were removed before this implementation. Remaining work: run-scoped synthesizers, characterization of exception normalization, and isolation regression coverage. Jev/ReAnchor experiments are deferred.
