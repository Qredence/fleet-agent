"""Task contracts for the DSPy engine, authored as Markdown + YAML.

Prompt text lives in ``app/agent/agents/prompts/*.md`` so a reviewer reads prose
instead of a docstring. An optimizer that wants to tune these prompts targets the
same files a reviewer edits: the spec layer's ``dump_state``/``apply_state`` pair
manages per-node write-back, while ``evals/optimize.py`` promotes router
instructions as an artifact the factory reads at startup.

Only the parts the spec layer can express are declared there. What it cannot
express still lives in Python, with the reason named:

* ``ToolRoutingSignature`` (``routing.py``) is a conditional: choosing one of six
  least-privilege profiles is control flow, and the spec's closed module-type set
  deliberately has no ``switch``.
* The evidence loop is assembled in ``program.py`` rather than as a spec
  ``sequential`` node, because the synthesis step needs ``evidence_json``, which
  is computed from the loop's ``dspy.History`` rather than produced as a declared
  field. The spec expresses wiring by field name, never field math.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import dspy

from app.agent.routing import ToolRoute
from app.agent.spec import (
    AgentSpec,
    ToolRegistry,
    build_program,
    load_spec,
)

AGENTS_DIR = Path(__file__).resolve().parent / "agents"
SPEC_PATH = AGENTS_DIR / "fleet_agent.yaml"

# The synthesis predictor's public text fields. The engine streams exactly these
# with dspy.streamify listeners.
SYNTHESIS_STREAM_FIELDS = ("answer", "process_summary")


@lru_cache(maxsize=1)
def synthesis_spec() -> AgentSpec:
    """The declarative agent definition, validated once per process."""
    return load_spec(SPEC_PATH)


@lru_cache(maxsize=1)
def build_synthesizer() -> dspy.Module:
    """Build the declared synthesis node: one ``predict`` over Markdown text.

    Only this node is built from the spec: the evidence loop is a separate node
    because the program computes ``evidence_json`` between them, and building
    both here would resolve the gather node's tools for no reason.
    """
    spec = synthesis_spec().model_copy(deep=True)
    spec.root = "synthesize"
    spec.modules = {"synthesize": spec.modules["synthesize"]}
    return build_program(spec)


def build_gatherer(
    route: ToolRoute, tools: Sequence[dspy.Tool], max_iters: int
) -> dspy.Module:
    """Build the declared evidence loop for one capability profile.

    The spec owns the node and its prompt; the run's least-privilege profile
    supplies the tools, so a route still cannot reach a tool outside its profile.
    ``max_iters`` binds here - not at the YAML default - because the program, not
    the spec, owns the operator's loop bound. Built fresh per run because tools
    carry run-scoped state (an event bus, a thread id), and per route because
    ``Signature.instructions`` lives on the class - sharing one class would alias
    every route's optimizer write-back.
    """
    spec = synthesis_spec().model_copy(deep=True)
    names = [str(tool.name) for tool in tools]
    spec.root = "gather"
    spec.modules = {
        "gather": spec.modules["gather"].model_copy(
            update={"tools": names, "max_iters": max_iters}
        )
    }
    return build_program(
        spec,
        tools=ToolRegistry(
            {name: tool for name, tool in zip(names, tools, strict=True)}
        ),
    )
