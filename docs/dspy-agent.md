# Fleet Agent DSPy architecture (DSPy 3.4.0)

## Goal

Fleet Agent should be a real DSPy program, not a FastAPI service that happens
to instantiate a DSPy class inside a closure. The application now separates:

1. **Declarative definition** - `app/agent/agents/fleet_agent.yaml` plus Markdown
   prompts; `app/agent/spec/` compiles them into real `dspy.Signature` classes and
   a real `dspy.Module` tree
2. **DSPy program** - `FleetAgent(dspy.Module)`: routed evidence loops + streamed synthesis
3. **Tool authoring and policy** - one `TOOL_SPECS` table in `tool_registry.py`, and
   `create_dspy_tool` for schema validation
4. **Runtime adaptation** - `DspyAgentEngine` (run, stream, cancellation)
5. **Transport** - the AG-UI coordinator and reducers, which depend on the agent
   layer and never the reverse (`tests/test_architecture.py` enforces it)

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
      +-- router: dspy.Predict over the routing contract
      |     plus the conditional that dispatches on its answer, in Python: the
      |     spec layer wires by field name and has no switch
      |
      +-- evidence_agents: dict[ToolRoute, spec React node]
      |     one per non-empty capability profile (research, artifact,
      |     workspace_read, workspace_write, workspace_shell); built from the
      |     spec, holding only that profile's tools, never submitting an answer.
      |     `direct` has no profile tools, so it goes straight to synthesis
      |     rather than spending a call on a loop with nothing to gather.
      |
      +-- synthesizer: spec Predict node
            streams answer + process_summary tokens through
            dspy.streamify + StreamListener (ChatAdapter)
```

## RLM availability in 3.4.0

DSPy 3.4.0 exposes `RLM` at the package root as `dspy.RLM`; the implementation
is also available at `dspy/predict/rlm.py` for explicit imports. Fleet Agent's
code does not depend on RLM — the routed `FleetAgent` uses `ReActV2` only — but
these notes keep older RLM examples aligned with the pinned DSPy version.

## Why keep ReActV2

DSPy 3.4.0 marks `ReActV2` experimental, but it is the relevant agent
primitive for Fleet Agent because it uses structured `dspy.History`, explicit
`dspy.Tool` objects, `dspy.ToolCalls`, native function calling, and a typed
`submit` tool for final outputs.

The experimental dependency is contained inside `FleetAgent`. FastAPI, AG-UI,
persistence, and result mapping do not access `ReActV2.tools`, its internal
`Predict`, or its `submit` implementation.

The routed program uses ReActV2 in a deliberately restricted mode
(`evidence_only=True`): its loops run `EvidenceSignature`, which declares no
output fields, so a loop ends when the model stops asking for tools and the
terminal fields are filled by a separate `SynthesisSignature` predictor. This
is what makes clean token streaming possible: the ReAct loop runs to
completion first, then the synthesis predictor's two public fields stream to
the browser while the loop's history stays server-side.

## First-class program

`FleetAgent` is an application-owned `dspy.Module`. Its predictors (the
router, the six evidence ReActV2 children, and the synthesizer) are DSPy
sub-modules, so DSPy's module tree can discover them. That keeps
`named_predictors()`, state serialization, callbacks, usage tracking, and
future optimizer integration on the normal DSPy path.

The profile agents live in one `evidence_agents` dict keyed by route rather
than in six named attributes. DSPy discovers sub-modules by walking
`self.__dict__` and recursing into dicts, so a dict is a normal place to hold
them — `named_predictors()` reports them as
`evidence_agents['workspace_read'].react`. One route table also means adding a
capability is a change to `routing.py`, not to the program.

There is one construction path: `tool_profiles` is required. An un-routed
`FleetAgent` would be a way to hand a run tools outside its least-privilege
profile, so the program does not offer one.

The engine always invokes the program through `program(...)`, never by calling
`forward()` directly. A program without `synthesis_stream_fields` keeps the
non-streaming contract: the engine settles on the final prediction's fields
rather than emitting token updates.

## Saving optimized program state

Treat tools as run-scoped infrastructure and optimized predictor state as the
portable DSPy artifact. Build a fresh `FleetAgent` with the same routes and
tool names, then save or load its DSPy state:

```python
program = FleetAgent(tool_profiles=build_tool_profiles(registry), max_iters=12)
optimized = optimizer.compile(program, trainset=trainset)
optimized.save("fleet-agent.json")

runtime_program = FleetAgent(
    tool_profiles=build_tool_profiles(run_registry),
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
                description="Look up one customer by id.",
                read_only=True,
                parallelizable=True,
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

`TOOL_SPECS` is the single table every tool's policy comes from: its
model-facing description, its capability tag, whether it reads only, whether it
may run in parallel, and whether it requires approval. The engine builds each
`dspy.Tool` from that table and `GET /api/tools` renders the same strings, so the
browser and the model cannot disagree about what a tool is.

Only enforced policy lives there. `idempotent`, `timeout_seconds` and
`max_output_chars` were removed: nothing on the live path read them, because
ReActV2 is handed raw `dspy.Tool` objects and the registry's own execution
wrapper never ran. Network-facing tools own their request timeouts, and a tool
that requires approval is withheld from every profile until the run authorizes
it.

## Async and MCP boundary

DSPy 3.4.0 `ReActV2` executes tools synchronously. `dspy.Tool.from_mcp_tool`
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

The runtime no longer mutates `agent.tools["submit"].func`. DSPy 3.4.0 does not
publish that as an extension point. The default program now does true token
streaming on the public DSPy path (`dspy.streamify` + `StreamListener`); see
the next section.

## Token streaming (synthesis)

`engine.stream()` drives routed programs through `dspy.streamify` with
`StreamListener`s bound to the synthesis predictor's public output fields
(`answer`, `process_summary`). The pieces:

- `dspy.LM` uses a native `lm15` engine. A run-owned gateway router declares
  endpoint, credentials and wire policy; DSPy converts canonical responses and
  stream events for its adapters/listeners. Application code does not assemble
  provider SDK responses or LiteLLM chunks. Caching is disabled per run.
- The async program wrapper waits for its thread to unwind on cancellation,
  timeout or disconnect before closing the native LM/router and web clients.
- Synthesis runs under a scoped `dspy.context(adapter=ChatAdapter())`. The
  JSON adapter leaks its section boilerplate into streamed fields; ChatAdapter
  reconstructs fields exactly from token deltas.
- The engine runs one `StreamingScrubber` per streamed field: emitted text is
  always a stable prefix of the scrubbed field (see "Secret scrubbing").

- The AG-UI coordinator accumulates `answer` tokens into incremental
  `TextMessageContentEvent`s and the live `process_summary` into state deltas;
  the final fields event suppresses the answer text when tokens already
  streamed it (exactly-once).

The evidence-gathering ReAct loop does not stream: its history stays
server-side by design. Only the final synthesis fields cross the wire, token
by token.

## Evidence boundary (synthesis input)

The evidence loop hands its work to the synthesizer through
`SynthesisSignature.evidence_json`, a `str` input the model parses as JSON.
That makes validity a hard requirement, not a nicety: a document the model
cannot parse is worse than less evidence, because the model then answers from
a broken fragment while believing it has the evidence.

`app/agent/evidence.py` owns that contract. `bounded_json` spends the whole budget
on valid JSON: entries are kept in document order, and the entry that
overflows is shortened to exactly the room that is left, so a single oversized
tool result still delivers nearly the entire budget as evidence rather than a
fraction of it. The previous renderer sliced the serialized payload
(`text[:max_chars - 1] + "…"`), which produced unparseable JSON for any run
whose evidence exceeded the cap; that is the common case once two or three
tool results accumulate.

What the synthesizer sees is still bounded and public-safe by construction:
only tool names, their already-bounded results, and error flags are rendered.
`next_thought` reasoning, provider payloads, and credentials stay out of the
synthesis prompt.

## Code capability (understand, change, verify)

The second program shape: `app/agent/agents/code.yaml` declares an
`understand` predictor, a tool-using `change` loop, and an `answer` predictor,
and `app/agent/code.py` drives them. The driver loop is plain Python because
"did the tests pass?" is a computed condition, not a field mapping - the same
boundary that keeps routing and evidence-rendering in `program.py`.

The loop is the product: plan once, then change-and-verify until the suite is
green or the attempt budget is spent. The test command is a required parameter,
never a default - a code agent that silently skips verification is the failure
mode this capability exists to remove. On exhaustion the run reports failure
honestly (`termination_reason="unverified"`) instead of claiming success.

Its eval (`python -m evals.run --suite code`) scores a fixture task by running
the real suite before and after: exit 0 requires green-after plus red-before,
so a task whose suite already passes proves nothing and fails loudly.

## Approval is a decision, not a pause

Approval-gated tools (`write`, `edit`, `bash`) are **withheld from the model**
unless the run authorizes them up front. `app/agent/approval.py` reads the
decision from the request (`forwardedProps.approvedTools`: `"*"`, one name, or a
list) and `build_tool_profiles` drops every gated tool the run did not authorize
from every profile before the program is built.

The consequence is stronger than declining a call: an unauthorized tool is never
placed in a profile, so the model cannot see it and cannot be talked into calling
it. `withheld_tool_names` reports what a run would have had to authorize, so the
client can make the refusal actionable.

This replaced a mid-loop pause. That design needed an 846-line fork of
`dspy.ReActV2.forward` over four private DSPy symbols, a hard `dspy == 3.3.1`
pin, a durable checkpoint table, a boot-time database dependency, and two
registries - to cover a checkpoint with a **five-minute TTL that was never
written** (`approval_checkpoints` held zero rows).

Nothing here needs a database. The API still reconciles orphaned runs at startup,
and a database outage no longer stops the service from booting: the sweep
degrades to a warning and the app serves.

The `interrupted` value is still accepted (`_SAFE_RUN_STATUSES`) and still present
in the public contract enum, but **nothing produces it**. The startup sweep
(`mark_orphaned_interrupted`) rewrites any surviving `interrupted` run *and* its
persisted snapshot to `failed` / `server_restart`, so the value has no producer and
no long-lived rows. It is listed defensively for the one window where the sweep has
not run yet - a boot whose database was unreachable, which now degrades to a warning.

## Secret scrubbing (batch and streaming)

`app/kernel/content_safety.py` masks high-precision credential patterns
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

`evals/agent_tool_routing.py` holds two example populations: 27 canonical
requests (the unambiguous core, every route covered) and 18 adversarial
requests attacking the two real failure modes - over-selection (granting
mutation for discussion) and under-selection (phrasing mutation as a question,
or a deletion that needs the shell because no delete tool exists).

The metric scores least privilege: exact route 1.0, over-selection 0.35,
under-selection 0.0 (the run cannot succeed). `routing_metric` returns the
score/feedback prediction that satisfies dspy 3.4.0's GEPA metric contract, so
`compile_gepa_candidate` can optimize the router offline; `routing_score` is
its numeric projection for `dspy.Evaluate`.

`evals/scoring.py` owns the scoring loop both offline callers share: it wraps
the router in a timing module, runs it through `dspy.Evaluate`, and returns the
mean score, the misses in devset order, and the mean per-request latency. The
eval runner and the GEPA optimizer therefore cannot drift apart on the metric,
the adapter, or the `dspy.context` they score under. Threads default to 1
because the harness talks to operator gateways; `score_router(num_threads=...)`
opts into `dspy.Evaluate`'s bounded parallelism.

Run it without any provider (CI mode - dataset structure only):

```bash
cd apps/api && uv run python -m evals.run --suite routing --validate
```

With provider credentials configured (`FLEET_AGENT_LLM_*`), the
same command scores every example through the production router predictor and
prints a per-route miss breakdown, exiting nonzero below `--min-accuracy`
(default 0.9). GEPA compilation stays an explicit, separate offline step.

Structural approval gating (that `write`/`edit`/`bash` are the only gated
mutators, that read-only routes can never reach a gated tool, and that
untrusted router output degrades to `direct`) is pinned by
`tests/test_routing_gating.py` in the normal pytest suite.

## Self-improvement (GEPA over the router)

`python -m evals.optimize` evolves the capability router's **instructions**. The
router is the one component with both a labelled dataset and a deterministic
metric, so a run costs one LM call per example rather than a full agent turn.

The loop is offline, manual, and gated:

```bash
cd apps/api && uv run python -m evals.optimize --auto light
```

1. The 45-example set (27 canonical + 18 adversarial) is split per route
   (fixed seed, stratified so a two-example route cannot vanish from the test
   half).
2. The baseline router is scored on the **held-out** half.
3. GEPA (`dspy.GEPA`, `auto=light|medium|heavy`) compiles a candidate with the
   production LM as both candidate and reflection model - over the **train half
   only**. Handing GEPA the held-out set would tune the candidate against the
   very examples the gate is measured on, which makes a pass meaningless. (The
   earlier Flex-based runner did exactly that; its 0.95 -> 1.00 result was
   selected on the set it was reported against.)
4. The candidate is scored on the same held-out half. It must beat the baseline
   **and** clear `--min-accuracy` (default 0.9) or nothing is written and the
   runner exits 2.
5. On success the runner writes a versioned artifact directory under
   `evals/artifacts/` (gitignored): `router_state.json` (the promoted
   instructions, plus the scores that justified them), `report.md` (baseline vs.
   candidate, misses on both sides, raised-call counts), and `manifest.json`
   (scores, budget, seeds, per-route train counts, dspy version). Every attempt,
   passing or not, is logged to MLflow as a `fleet-agent/router-optimization`
   run.

Promotion is a second, explicit human step:

```bash
uv run python -m evals.optimize --auto light --promote
```

This copies a passing candidate to `evals/artifacts/router_active.json`. Going
live still requires the operator to point `FLEET_AGENT_ROUTER_STATE_PATH` at
that file and restart. At startup the engine builder reads the artifact once and
logs the path it accepted, so a pin can be confirmed; a malformed or
unrecognized file **fails startup with a clear error** rather than being silently
ignored - an operator who pinned a file expects it in effect.

Safety properties that promotion cannot weaken:

- The artifact carries instruction text only; `coerce_route` still converts any
  router answer to a least-privileged route, so a degenerate candidate degrades
  to `direct` and can never widen a profile.
- Overriding one program's router uses a fresh signature class
  (`with_instructions`), so it cannot leak into the shared contract.
- Approval gating is profile-structural (gated tools are withheld before the
  program is built), not prompt based, so evolved prompts cannot unlock a tool.

## MLflow observability

The self-improvement loop keeps its history in MLflow:

- Every optimization attempt — gates passed **or** failed — is logged
  (`evals/mlflow_tracking.py`) with params (budget, seeds, split sizes),
  metrics (baseline/candidate means, latency, `gates_passed`), and, on pass,
  the full candidate artifact directory (`router_state.json`, `report.md`,
  `manifest.json`). A rejected
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
  opt-in (`FLEET_AGENT_ROUTER_STATE_PATH`).
- **Promoting a router costs nothing at runtime.** The artifact is instruction
  text, read once when the engine builder is constructed; an unpinned
  deployment keeps the baseline contract. The earlier Flex-based promotion
  needed a Deno sandbox and about a second of interpreter round-trip per routed
  request, which is why it was replaced.
- **The eval set is small and hand-authored.** 45 examples (27 canonical +
  18 adversarial), 13 held out. A
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
- The routed program has exactly one construction path, and every profile
  holds only its own route's tools, so no run can reach a tool outside the
  profile its router selected.
- Every default production tool is an explicit `dspy.Tool` before it reaches
  ReActV2.
- Duplicate, reserved, undocumented, variadic, or untyped tools fail early.
- Tool allowlists select availability deterministically; approval gating is
  structural (pinned by `tests/test_routing_gating.py`).
- The default engine is strategy-neutral and never accesses ReActV2 internals.
- Streamed synthesis equals batch synthesis: token concatenation always
  equals the scrubbed final fields, for every delta split
  (`tests/test_synthesis_streaming.py`, `tests/test_content_safety.py`).
- The synthesizer's evidence input is always parseable JSON within its budget,
  for both programs, including a single oversized tool result
  (`tests/test_evidence.py`).
- The eval runner and the GEPA optimizer score routers through one shared
  `dspy.Evaluate` call and report the same mean, misses, and latency
  (`tests/test_eval_scoring.py`).
- Gated tools are withheld before the program is built, so an unauthorized
  tool is never offered to the model (`tests/test_fleet_agent_routing.py`).
  Orphaned runs are still reconciled on startup, and a database outage no longer
  stops the service from booting (`tests/test_health.py`).
- The self-improvement harness writes an artifact only when the evolved
  candidate beats the baseline and clears the accuracy floor on a held-out split
  GEPA never saw; promoted state carries instruction text only
  (`tests/test_router_optimize.py`).
- Existing history, termination, usage, cleanup, AG-UI, and no-chain-of-thought
  contract tests continue to pass.
