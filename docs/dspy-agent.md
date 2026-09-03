# Fleet Agent DSPy architecture (DSPy 3.3.1)

## Goal

Fleet Agent should be a real DSPy program, not a FastAPI service that happens
to instantiate a DSPy class inside a closure. The application now separates:

1. **Task contract** - `EvidenceSignature` / `SynthesisSignature` / `AgentSignature`
2. **DSPy program** - `FleetAgent(dspy.Module)`: routed evidence loops + streamed synthesis
3. **Tool authoring and policy** - `create_dspy_tool` + `ToolRegistry`
4. **Runtime adaptation** - `DspyAgentEngine` (run, stream, durable approvals)
5. **UI/public state** - AG-UI coordinator and reducers

```text
FastAPI / AG-UI
      |
      v
DspyAgentEngine
  scoped dspy.context(lm, adapter, callbacks, usage)
      |
      v
FleetAgent(dspy.Module)
      |
      +-- router: dspy.Predict(ToolRoutingSignature)  (least-privilege route)
      |
      +-- evidence agents: ApprovalAwareReActV2(EvidenceSignature, evidence_only=True)
      |     one per route profile (research, artifact, workspace_read,
      |     workspace_write, workspace_shell); they gather evidence only and
      |     never submit an answer themselves
      |
      +-- synthesizer: dspy.Predict(SynthesisSignature)
            streams answer + process_summary tokens through
            dspy.streamify + StreamListener (ChatAdapter)
```

## RLM availability in 3.3.1

DSPy 3.3.1 exposes `RLM` at the package root as `dspy.RLM`; the implementation
is also available at `dspy/predict/rlm.py` for explicit imports. Fleet Agent's
code does not depend on RLM — the routed `FleetAgent` uses `ReActV2` only — but
these notes keep older RLM examples aligned with the pinned DSPy version.

## Why keep ReActV2

DSPy 3.3.1 marks `ReActV2` experimental, but it is the relevant 3.3 agent
primitive for Fleet Agent because it uses structured `dspy.History`, explicit
`dspy.Tool` objects, `dspy.ToolCalls`, native function calling, and a typed
`submit` tool for final outputs.

The experimental dependency is contained inside `FleetAgent`. FastAPI, AG-UI,
persistence, and result mapping do not access `ReActV2.tools`, its internal
`Predict`, or its `submit` implementation.

The routed program uses ReActV2 in a deliberately restricted mode
(`evidence_only=True`): the loop's `submit` step terminates evidence
gathering and the terminal fields are filled by a separate `SynthesisSignature`
predictor. This is what makes clean token streaming possible: the ReAct loop
runs to completion first, then the synthesis predictor's two public fields
stream to the browser while the loop's history stays server-side.

## First-class program

`FleetAgent` is an application-owned `dspy.Module`. Its predictors (the
router, the six evidence ReActV2 children, and the synthesizer) are DSPy
sub-modules, so DSPy's module tree can discover them. That keeps
`named_predictors()`, state serialization, callbacks, usage tracking, and
future optimizer integration on the normal DSPy path.

The engine always invokes the program through `program(...)`, never by calling
`forward()` directly. Programs without `synthesis_stream_fields` (the staged
strategy, legacy single-pass ReAct) keep the non-streaming contract: the
engine settles on the final prediction's fields only.

## Saving optimized program state

Treat tools as run-scoped infrastructure and optimized predictor state as the
portable DSPy artifact. Build a fresh `FleetAgent` with the same signature and
tool names, then save or load its DSPy state:

```python
program = FleetAgent(tools=registry.dspy_tools(), max_iters=12)
optimized = optimizer.compile(program, trainset=trainset)
optimized.save("fleet-agent.json")

runtime_program = FleetAgent(
    tools=run_registry.dspy_tools(),
    max_iters=12,
)
runtime_program.load("fleet-agent.json")
```

Prefer state-only JSON persistence. Full-program pickle serialization can also
try to serialize run-scoped HTTP clients or storage handles owned by tools and
is therefore not the production deployment boundary.

## Creating tools

Tools are authored as trusted, synchronous, fully typed Python callables. The
registry converts them to `dspy.Tool` exactly once.

```python
from pydantic import BaseModel, Field

from app.agent.tool_registry import ToolMetadata, ToolRegistry
from app.agent.tooling import create_dspy_tool


class CustomerLookup(BaseModel):
    customer_id: str = Field(description="Stable customer identifier")


def find_customer(query: CustomerLookup) -> str:
    """Find a customer record by its stable identifier."""
    return customer_repository.find(query.customer_id)


tool = create_dspy_tool(
    find_customer,
    name="find_customer",
    arg_descriptions={"query": "Validated customer lookup input."},
)

registry = ToolRegistry(
    [
        (
            tool,
            ToolMetadata(
                name="find_customer",
                read_only=True,
                idempotent=True,
                parallelizable=True,
                timeout_seconds=10,
            ),
        )
    ]
)
```

`create_dspy_tool` validates that the model sees a real name, description, and
concrete argument types. A prebuilt `dspy.Tool` is preserved rather than wrapped
again, so explicit schemas and argument descriptions are not lost.

## "Use when needed" means selection, not code generation

There are two decisions:

- The application chooses which trusted tools are available for the run with
  `registry.dspy_tools(allowed_names=...)`.
- ReActV2 chooses whether and when to call one of those available tools.

Fleet Agent must not generate and execute arbitrary Python functions from user
text. New executable tools are added by trusted server-side code, a reviewed
plugin boundary, or a future MCP connector.

## Tool policy scope

`ToolMetadata` records application policy for catalog display, staged
orchestration, isolation, timeout selection, and bounded results. ReActV2
receives the corresponding `dspy.Tool` schema and callable; it does not natively
understand Fleet Agent's `read_only`, `idempotent`, or `parallelizable` flags.
Network-facing tools therefore continue to own their request timeouts, and a
future approval-required tool must be gated before it is placed in the run's
allowlist.

## Async and MCP boundary

DSPy 3.3.1 `ReActV2` executes tools synchronously. `dspy.Tool.from_mcp_tool`
creates async tools, so MCP tools must not be inserted into this program by
turning on implicit async-to-sync conversion. Under FastAPI's running event
loop that conversion can fail and it violates the current synchronous contract.

The registry accepts prebuilt synchronous `dspy.Tool` objects and rejects async
ones on this ReActV2 path. A future MCP program should use an async DSPy
module/agent path and call tools through `Tool.acall()`; it can reuse the same
metadata and catalog concepts without weakening the current contract.

## Engine boundary

`DspyAgentEngine` accepts a `program_factory`, not a concrete ReActV2 factory.
This allows a zero-shot `FleetAgent`, a compiled FleetAgent, or another DSPy
module to run behind the same API contract.

The runtime owns:

- run-scoped `dspy.context(...)`
- LM and adapter selection
- DSPy callbacks
- usage accounting
- thread handoff for the synchronous program
- cleanup
- mapping `dspy.Prediction` to `AgentRunResult`

The runtime no longer mutates `agent.tools["submit"].func`. DSPy 3.3.1 does not
publish that as an extension point. The default program now does true token
streaming on the public DSPy path (`dspy.streamify` + `StreamListener`); see
the next section.

## Token streaming (synthesis)

`engine.stream()` drives routed programs through `dspy.streamify` with
`StreamListener`s bound to the synthesis predictor's public output fields
(`answer`, `process_summary`). The pieces:

- `OpenAICompatibleLM.forward` watches `dspy_settings.send_stream`. When a
  listener-targeted predict opens a stream, the gateway request is sent with
  `stream: true`, each content delta is wrapped as a litellm-shaped chunk
  carrying the caller's `predict_id` and pushed through
  `sync_send_to_stream`, and the full completion is rebuilt from the
  accumulated content so the adapter's parse path is unchanged. Streamed
  responses are never served from the DSPy cache.
- Synthesis runs under a scoped `dspy.context(adapter=ChatAdapter())`. The
  JSON adapter leaks its section boilerplate into streamed fields; ChatAdapter
  reconstructs fields exactly from token deltas.
- The engine runs one `StreamingScrubber` per streamed field: emitted text is
  always a stable prefix of the scrubbed field (see "Secret scrubbing").
- Approval pauses raised inside the streamed evidence loop surface through
  streamify's anyio task group as an exception group; the engine flattens it
  and maps `ApprovalPause` / `ApprovalDecisionError` to interrupted/failed
  results, re-raising anything unrelated.
- The AG-UI coordinator accumulates `answer` tokens into incremental
  `TextMessageContentEvent`s and the live `process_summary` into state deltas;
  the final fields event suppresses the answer text when tokens already
  streamed it (exactly-once).

The evidence-gathering ReAct loop does not stream: its history stays
server-side by design. Only the final synthesis fields cross the wire, token
by token.

## Durable approval checkpoints

Approval-gated tools (`write`, `edit`, `bash`) pause the run with an AG-UI
interrupt. The pause state is durable:

- `DurableApprovalRegistry` persists each interrupt as an
  `approval_checkpoints` row (payload, thread, run, tool call id) inside the
  run's database session before the SSE stream surfaces the interrupt. The
  browser decision is consumed exactly once, in a database transaction, and
  the row is deleted when applied.
- On server restart, `main.py` lifespan reconciliation sweeps orphaned
  `interrupted` runs whose pending checkpoints no longer belong to a live
  process, so a crashed server cannot leave an unapprovable run forever.
- Resumed runs replay the durable history: the evidence loop continues from
  the persisted DSPy history, the approved tool call executes, and synthesis
  streams normally. Denials terminate the run with a safe error code; the
  raw tool arguments never leave the server beyond the bounded single-line
  action preview the approver needs.

Non-durable (in-memory) registries remain available for single-process
deployments without a database; the engine treats both through the same
`ApprovalRegistryProtocol`.

## Secret scrubbing (batch and streaming)

`app/services/content_safety.py` masks high-precision credential patterns
(provider keys, AWS/Google/GitHub/Slack tokens, JWTs, Bearer headers, PEM
blocks, explicit credential assignments) at every boundary where free text
crosses to the browser or persistent public state: final result fields, tool
argument/result previews, artifact content, and legacy bootstrap state.

Streaming adds a second, harder problem: a secret can arrive split across
token deltas. `StreamingScrubber` solves it by emitting only stable prefixes
of the *scrubbed* text:

- An anchor prefix still visible in the scrubbed pending text (a secret
  start such as `sk-`, `AKIA`, `-----BEGIN`, `password`…) holds the stream
  back from that position: later deltas may complete the pattern. Masked
  secrets leave no anchor text behind, so streaming resumes right after the
  `[redacted]` mask.
- A fragment ending at the emit boundary that is a proper prefix of an anchor
  (`...the pass` before `word = <secret>` can arrive) is held back too, to a
  fixpoint. The `[redacted]` mask is never split across two emissions.
- The concatenation of everything emitted equals `scrub(full text)` for every
  possible delta split; this equivalence is pinned by parametrized tests over
  chunk sizes 1–17.

The deliberate tradeoff is lag, not safety: benign text containing an
anchor-shaped word (`Bearer of good news`, `the password field`) holds back
until the field's flush rather than streaming incrementally. Fields without
any anchor stream immediately (minus a small 80-character confirmation window).

## Routing evaluation

`evals/agent_tool_routing.py` holds two example populations: 25 canonical
requests (the unambiguous core, every route covered) and 18 adversarial
requests attacking the two real failure modes - over-selection (granting
mutation for discussion) and under-selection (phrasing mutation as a question,
or a deletion that needs the shell because no delete tool exists).

The metric scores least privilege: exact route 1.0, over-selection 0.35,
under-selection 0.0 (the run cannot succeed). It satisfies dspy 3.3.1's
GEPA metric contract so `compile_gepa_candidate` can optimize the router
offline.

Run it without any provider (CI mode - dataset structure only):

```bash
cd apps/api && uv run python -m evals.run --suite routing --validate
```

With provider credentials configured (`MODAL_*` or `FLEET_AGENT_LLM_*`), the
same command scores every example through the production router predictor and
prints a per-route miss breakdown, exiting nonzero below `--min-accuracy`
(default 0.9). GEPA compilation stays an explicit, separate offline step.

Structural approval gating (that `write`/`edit`/`bash` are the only gated
mutators, that read-only routes can never reach a gated tool, and that
untrusted router output degrades to `direct`) is pinned by
`tests/test_routing_gating.py` in the normal pytest suite.

## Self-improvement (Flex + GEPA)

The router has a self-improving counterpart: `FlexToolRouter`
(`app/agent/flex_router.py`) implements the same routing task as a
`dspy.Flex` program, so GEPA's update unit is the router's *source code* —
decomposed predictors plus plain Python — not just its instructions.

The loop is offline, manual, and gated:

```bash
cd apps/api && uv run python -m evals.optimize --auto light
```

1. The 43-example set (25 canonical + 18 adversarial) is split per route
   (fixed seed, ~70/30) into train and held-out validation halves.
2. The baseline Flex router is scored on the held-out half. Every forward —
   baseline included — runs inside dspy's Deno sandbox; the optimizer never
   executes in the host process, and only predictor construction/calls bridge
   back to it.
3. GEPA (`dspy.GEPA`, `auto=light|medium|heavy`) compiles a candidate with
   the production LM as both candidate and reflection model.
4. The candidate is scored on the same held-out half. It must beat the
   baseline **and** clear `--min-accuracy` (default 0.9) or nothing is
   written and the runner exits nonzero.
5. On success the runner writes a versioned artifact directory under
   `evals/artifacts/` (gitignored): `state.json` (the only state a Flex
   router carries is `module_src`; any embedded LM state is dropped on
   purpose), `module_src.py` (the evolved source for human review),
   `report.md` (baseline vs. candidate, misses, measured sandbox latency),
   and `manifest.json` (scores, budget, seed, versions).

Promotion is a second, explicit human step:

```bash
uv run python -m evals.optimize --promote --artifact evals/artifacts/<dir>
```

This copies the chosen state to `evals/artifacts/flex_router_active.json`.
Going live still requires the operator to set `FLEET_AGENT_ROUTER_STATE` to
that file and restart the server. At startup the engine builder validates the
pinned artifact (parseable JSON, non-empty `module_src`, Deno present) and
fails fast otherwise; each run-scoped program then builds a fresh Flex router
from the pinned source. Unset, the production router stays the plain
zero-shot `dspy.Predict`.

Safety properties that promotion cannot weaken:

- The evolved source only ever runs inside the Deno interpreter; it cannot
  touch the host process, the database, or the filesystem.
- Its output still flows through `coerce_route`; a degenerate candidate
  degrades to `direct`, it can never widen a profile.
- Approval gating is registry-structural (profile tool sets), not prompt
  based, so evolved prompts cannot unlock gated tools.

## MLflow observability

The self-improvement loop keeps its history in MLflow:

- Every optimization attempt — gates passed **or** failed — is logged
  (`evals/mlflow_tracking.py`) with params (budget, seeds, split sizes),
  metrics (baseline/candidate means, per-request sandbox latency,
  `gates_passed`), and, on pass, the full candidate artifact directory
  (`state.json`, `module_src.py`, `report.md`, `manifest.json`). A rejected
  candidate is logged too: the history of failed attempts is as valuable as
  the winners.
- Scored routing evals (`python -m evals.run --suite routing`) log mean
  score, under/over-selection counts, and a `misses.json` artifact.
- The default store is local SQLite at `.artifacts/mlflow.db` (gitignored;
  MLflow 3.x placed the old filesystem store in maintenance mode). Point
  `FLEET_AGENT_MLFLOW_TRACKING_URI` — or standard `MLFLOW_TRACKING_URI` —
  at a server to centralize; browse with `mlflow ui --backend-store-uri
  sqlite:///.artifacts/mlflow.db`.

Live agent tracing is a separate, **opt-in** feature
(`FLEET_AGENT_MLFLOW_TRACING=true`, default off):
`mlflow.dspy.autolog()` traces predictor, ReAct, and tool-call spans into
the experiment `fleet-agent/agent-runs`. MLflow traces capture LLM prompts
and completions by design — enabling the flag is an explicit operator
decision about their own observability store; the app itself never sends
provider data to the browser, with or without the flag.

## Residual risks (honest)

- **Scrubbing is pattern-based.** High-precision patterns only; a credential
  format outside the list (an exotic gateway key with no recognizable
  prefix) is not masked. False positives are deliberately preferred over
  broad base64/hex guesses that would corrupt legitimate answers.
- **Approval previews leak one bounded line by design.** The approver must
  see the gated action (the bash command, the file path). That preview is
  single-line and length-capped, but it is real content.
- **Bash is a real shell.** The PATH is pinned to
  `/usr/bin:/bin:/usr/local/bin`, HOME is the workspace root, output is
  capped and process groups are killed on timeout - but an approved command
  executes with real filesystem access below the workspace root. Approval is
  a human decision, not a sandbox.
- **No delete tool.** Deletion requires the shell route, so "delete this
  file" requests select `workspace_shell`, the most privileged profile.
- **Router is a zero-shot predictor until an operator promotes a compiled
  one.** Route mistakes degrade to least privilege (`coerce_route`), and the
  evidence loop can still ask for tools within its own profile, but the
  default router is not optimizer-compiled; self-improvement is real but
  opt-in (`FLEET_AGENT_ROUTER_STATE`).
- **A promoted Flex router adds runtime dependencies.** It needs a Deno
  runtime on every API server (validated at startup), and each routed
  request pays one sandboxed interpreter round-trip (measured ~1s locally,
  reported per run in the artifact manifest) before the evidence loop even
  starts. Operators who value latency over route precision simply do not pin
  the state.
- **The eval set is small and hand-authored.** 43 examples (25 canonical +
  18 adversarial), ~13 held out. A
  candidate that clears the gates generalizes as well as that set measures;
  the gate is regression protection, not proof of optimality.
- **Detached/resumable runs beyond approvals are out of scope.** A paused
  approval survives restarts; a long-running non-approval run does not
  (cancel or crash ends it).

## Public safety invariant

The browser may receive:

- final answer (streamed token-by-token, scrubbed per delta)
- user-safe process summary (streamed as state deltas)
- key decisions
- caveats
- sanitized tool/source/artifact events
- aggregate usage
- one bounded, single-line preview of a gated action (approval interrupts)

It must never receive:

- `next_thought`
- raw `dspy.History`
- provider prompts or responses
- unsanitized tool arguments/results
- credentials or stack traces
- any fragment of a credential that is still arriving across tokens

## Acceptance checks

- `FleetAgent` is a `dspy.Module` and exposes its nested predictors (router,
  evidence agents, synthesizer) to DSPy's module tree.
- Every default production tool is an explicit `dspy.Tool` before it reaches
  ReActV2.
- Duplicate, reserved, undocumented, variadic, or untyped tools fail early.
- Tool allowlists select availability deterministically; approval gating is
  structural (pinned by `tests/test_routing_gating.py`).
- The default engine is strategy-neutral and never accesses ReActV2 internals.
- Streamed synthesis equals batch synthesis: token concatenation always
  equals the scrubbed final fields, for every delta split
  (`tests/test_synthesis_streaming.py`, `tests/test_content_safety.py`).
- Approval pauses survive server restarts; orphaned interrupted runs are
  swept on startup (`tests/test_durable_approvals.py`).
- The self-improvement harness writes an artifact only when the evolved
  candidate beats the baseline and clears the accuracy floor on held-out
  examples; promoted state carries `module_src` only, never an LM
  (`tests/test_flex_router_optimize.py`).
- Existing history, termination, usage, cleanup, AG-UI, and no-chain-of-thought
  contract tests continue to pass.
