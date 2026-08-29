# Fleet Agent DSPy architecture (DSPy 3.3.1)

## Goal

Fleet Agent should be a real DSPy program, not a FastAPI service that happens
to instantiate a DSPy class inside a closure. The application now separates:

1. **Task contract** - `AgentSignature`
2. **DSPy program** - `FleetAgent(dspy.Module)`
3. **Tool authoring and policy** - `create_dspy_tool` + `ToolRegistry`
4. **Runtime adaptation** - `DspyAgentEngine`
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
      v
ReActV2(AgentSignature, list[dspy.Tool])
      |
      +-- search_docs
      +-- web_search / fetch_page (when configured)
      +-- write_report
      +-- get_current_time
```

## Why keep ReActV2

DSPy 3.3.1 marks `ReActV2` experimental, but it is the relevant 3.3 agent
primitive for Fleet Agent because it uses structured `dspy.History`, explicit
`dspy.Tool` objects, `dspy.ToolCalls`, native function calling, and a typed
`submit` tool for final outputs.

The experimental dependency is contained inside `FleetAgent`. FastAPI, AG-UI,
persistence, and result mapping do not access `ReActV2.tools`, its internal
`Predict`, or its `submit` implementation.

## First-class program

`FleetAgent` is an application-owned `dspy.Module`. Its `react` attribute is a
DSPy sub-module, so DSPy's module tree can discover the underlying predictor.
That keeps `named_predictors()`, state serialization, callbacks, usage tracking,
and future optimizer integration on the normal DSPy path.

The engine always invokes the program through `program(...)`, never by calling
`forward()` directly.

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
publish that as an extension point. The current stream emits safe final fields
from the settled Prediction; true token streaming should be implemented
separately with public DSPy streaming APIs.

## Public safety invariant

The browser may receive:

- final answer
- user-safe process summary
- key decisions
- caveats
- sanitized tool/source/artifact events
- aggregate usage

It must never receive:

- `next_thought`
- raw `dspy.History`
- provider prompts or responses
- unsanitized tool arguments/results
- credentials or stack traces

## Acceptance checks

- `FleetAgent` is a `dspy.Module` and exposes its nested predictor to DSPy's
  module tree.
- Every default production tool is an explicit `dspy.Tool` before it reaches
  ReActV2.
- Duplicate, reserved, undocumented, variadic, or untyped tools fail early.
- Tool allowlists select availability deterministically.
- The default engine is strategy-neutral and never accesses ReActV2 internals.
- Existing history, termination, usage, cleanup, AG-UI, and no-chain-of-thought
  contract tests continue to pass.
