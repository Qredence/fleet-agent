# Fleet Agent Engineering Guidance

Fleet Agent is a DSPy-powered agent workbench with a React/assistant-ui frontend, FastAPI backend, AG-UI transport, shared versioned contracts, PostgreSQL persistence, and deterministic fixture mode.

The primary product interaction is:

```text
User
  ↕
Frontend UI
  ↕
public contracts / AG-UI
  ↕
backend orchestration
  ↕
DSPy programs + tools
```

The UI is the primary user-facing product. Backend and DSPy work must always be evaluated in terms of the user-visible behavior and the public contract connecting backend and frontend.

## Core engineering principles

### Keep the codebase simple

Prefer the smallest coherent implementation.

Do not introduce:
- generalized frameworks for one feature;
- speculative extension points;
- unnecessary factories or wrappers;
- parallel sources of truth;
- abstractions with one caller unless they clarify an important boundary;
- compatibility layers that can simply be removed after migration.

Prefer deleting code over adding another abstraction when behavior can remain unchanged.

### Spec first

For non-trivial work:

1. inspect the current implementation;
2. write or update a concise spec under `docs/specs/`;
3. identify invariants and acceptance criteria;
4. implement only the required scope;
5. validate behavior;
6. update the spec if implementation materially differs.

A spec should normally describe:

- problem;
- current behavior;
- desired behavior;
- invariants;
- public contract impact;
- frontend/UI impact;
- DSPy/evaluation impact;
- observability/MLflow impact;
- tests;
- acceptance criteria.

Do not use a spec as an excuse to redesign unrelated code.

## Architectural boundaries

Prefer this dependency direction:

```text
DSPy programs / tools
        ↓
application orchestration + deterministic policy
        ↓
domain/run semantics
        ↓
public safe projection
        ↓
AG-UI transport
        ↓
React UI
```

Do not make frontend code understand DSPy internals.

Do not make DSPy decide authorization.

Do not put application business semantics inside AG-UI serialization code.

## DSPy

Use DSPy as DSPy.

Prefer native:
- `Signature`;
- `Module`;
- `Predict`;
- `ReActV2`;
- streaming;
- `Evaluate`;
- GEPA;
- Jev;
- ReAnchor;

over building another generic agent framework around DSPy.

Prompt text may live in Markdown where useful, but avoid creating a second programming language for agent behavior unless there is a demonstrated product requirement.

### Model judgment vs policy

DSPy may determine:

```text
what capability appears necessary
what evidence is needed
whether evidence appears sufficient
what bounded presentation mode is appropriate
```

Deterministic application code determines:

```text
what capability exists
what is authorized
what requires approval
what tools are exposed
what actions may execute
```

Never use an LM probability or Jev score as authorization.

Approval-gated tools must continue to be withheld before the model/tool program is constructed.

## Experimental DSPy APIs

Jev and ReAnchor are experimental DSPy APIs.

Keep experimental DSPy types behind a narrow internal boundary.

Do not expose `dspy.experimental` objects through:
- public API contracts;
- persistence contracts;
- AG-UI state;
- frontend TypeScript types.

The rest of Fleet Agent should consume ordinary application/domain types.

## Evaluation

Do not change agent behavior based only on manual inspection.

Agent behavior changes require:
- baseline measurement;
- representative examples;
- held-out validation where optimization occurs;
- explicit metrics;
- regression checks.

GEPA and ReAnchor must never optimize against the same held-out examples used for promotion.

Rejected optimization candidates are useful evidence and should remain observable.

## MLflow

MLflow is observability, not runtime truth.

Runtime behavior must continue if MLflow is disabled or unavailable.

Use MLflow for:
- evaluation runs;
- optimizer/calibration attempts;
- candidate comparison;
- dataset/split metadata;
- relevant aggregate metrics;
- bounded reports/artifacts.

Never log:
- API keys;
- credentials;
- raw secret-bearing headers;
- data excluded by Fleet Agent's public safety boundary.

## Public safety invariants

Never expose to the browser:
- raw chain-of-thought;
- `next_thought`;
- raw DSPy history;
- provider prompts/responses;
- credentials;
- stack traces;
- unsanitized tool arguments/results.

Preserve streamed-secret scrubbing behavior.

## Contracts

Shared public contracts belong in `packages/contracts`.

Prefer generated Python and TypeScript models over separately handwritten representations.

Breaking contract changes require an explicit schema version change.

Do not expose DSPy-specific implementation terms in public contracts when a stable domain concept exists.

## Frontend state ownership

Maintain these boundaries:

```text
React Query
  → REST/server resources such as projects and threads

AG-UI / useAgUiState
  → agent execution and public run/process state

Zustand
  → local UI/layout/preferences only
```

Do not mirror agent state into Zustand.

## Frontend composition

Reuse existing product mechanisms before introducing new ones.

Preferred hierarchy:

```text
normal React components
        ↓
AG-UI state projections
        ↓
assistant-ui Data UI / CUSTOM events
        ↓
bounded generative UI when justified
```

Application shell layout remains controlled by application code/configuration.

The model must not control:
- navigation;
- core workspace panes;
- permissions;
- arbitrary React imports;
- executable frontend behavior.

Model-selected UI must resolve through an explicit allowlist and validated schemas.

## Backend/frontend changes

For every backend feature, explicitly determine:

- Is it internal only?
- Does it change AG-UI events?
- Does it change `AgentWorkspaceState`?
- Does it need a new frontend representation?
- Does fixture mode need updating?
- Does thread bootstrap/replay still behave correctly?

Do not call backend work complete if the corresponding user-visible state is broken or missing.

## Testing

Prefer tests for behavior and invariants rather than implementation structure.

Important invariants include:
- unauthorized tools cannot be presented to the model;
- route/capability failure degrades safely;
- public state never contains private reasoning;
- streaming output equals safe final output;
- fixtures remain deterministic;
- optimization cannot change authorization;
- public contract generation is fresh;
- frontend renders restored and live state consistently.

## Orb workflow

Each substantial implementation task should be handled as one focused task/thread.

Before editing:
- inspect relevant specs and code;
- state the intended change;
- identify validation commands.

Before finishing:
- run the relevant backend tests;
- run frontend tests/build when frontend behavior is affected;
- run relevant evals when DSPy behavior changes;
- exercise the UI through the development service/Portal when user-visible behavior changes.

Report:
- files changed;
- behavior changed;
- contracts changed;
- UI impact;
- tests/evals executed;
- measured before/after results;
- remaining limitations.

See @docs/specs/*.md for feature-specific requirements.