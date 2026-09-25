"""The live agent's prompts are declared in Markdown + YAML, not Python.

These tests lock the seam: the engine's synthesis step and evidence loops must
come from ``app/agent/agents/``, and an optimizer must be able to write
instructions back into the running program through the spec layer's state pair.
"""

from __future__ import annotations

from typing import Any

import dspy
import pytest

from app.agent.program import FleetAgent
from app.agent.routing import ROUTES
from app.agent.signature import (
    AGENTS_DIR,
    SYNTHESIS_STREAM_FIELDS,
    build_gatherer,
    build_synthesizer,
    synthesis_spec,
)
from app.agent.spec import SpecError, build_program, read_markdown
from app.agent.tooling import create_dspy_tool

SYNTHESIZE_MD = AGENTS_DIR / "prompts" / "synthesize.md"
EVIDENCE_MD = AGENTS_DIR / "prompts" / "evidence.md"
POLICY_TEXT = read_markdown(AGENTS_DIR / "prompts" / "policy.md")[1]
OPTIMIZED_INSTRUCTIONS = "Cite only supplied evidence; never speculate."


def _markdown_body(path) -> str:
    return read_markdown(path)[1]


def _synthesizer_spec():
    """The synthesis node alone, as a fresh spec.

    The YAML declares both nodes (the evidence loop and the synthesis step); the
    program assembles them around a computed field, so a test that wants a
    throwaway synthesis program trims the spec to that one node.
    """
    spec = synthesis_spec().model_copy(deep=True)
    spec.root = "synthesize"
    spec.modules = {"synthesize": spec.modules["synthesize"]}
    return spec


def test_spec_is_loaded_from_yaml() -> None:
    spec = synthesis_spec()
    assert spec.agent == "fleet-agent"
    assert spec.root == "synthesize"
    assert spec.source_dir == AGENTS_DIR.resolve()


def test_synthesizer_instructions_come_from_markdown() -> None:
    program = build_program(_synthesizer_spec())
    instructions = program.signature.instructions

    assert _markdown_body(SYNTHESIZE_MD) in instructions
    # the shared policy is opted into, so it is appended rather than duplicated
    assert POLICY_TEXT in instructions


def test_synthesizer_declares_the_public_contract() -> None:
    program = build_program(_synthesizer_spec())
    assert program.declared_inputs == ["user_request", "evidence_json", "history"]
    assert program.produced == [
        "answer",
        "process_summary",
        "key_decisions",
        "caveats",
    ]


def test_streamed_fields_are_declared_outputs() -> None:
    """The engine only streams fields the synthesis signature actually declares."""
    program = build_program(_synthesizer_spec())
    assert set(SYNTHESIS_STREAM_FIELDS) <= set(program.produced)


def _tool(name: str):
    def tool(query: str) -> str:
        """Look something up."""
        return query

    tool.__name__ = name
    tool.__qualname__ = name
    return create_dspy_tool(tool, name=name)


def test_evidence_loop_is_built_from_the_spec() -> None:
    """Regression: the tool-use policy used to live only in a test-only signature.

    The live evidence loop had no tool-use guidance at all after the program was
    split into an evidence loop plus a synthesizer. It is now the declared node,
    so the Markdown reaches it like any other instruction.
    """
    gatherer = build_gatherer("workspace_read", [_tool("search_docs")], max_iters=6)
    instructions = gatherer.signature.instructions

    assert _markdown_body(EVIDENCE_MD) in instructions
    assert POLICY_TEXT in instructions
    assert "untrusted evidence" in instructions


def test_evidence_loop_declares_no_output_fields() -> None:
    """The loop ends when the model stops asking for tools, not by submitting."""
    gatherer = build_gatherer("direct", [_tool("search_docs")], max_iters=6)
    assert list(gatherer.signature.output_fields) == []
    assert list(gatherer.signature.input_fields) == ["user_request"]


def test_evidence_loop_binds_only_the_tools_it_is_given() -> None:
    """The spec resolves tool names, so the profile's subset is what is bound."""
    gatherer = build_gatherer("research", [_tool("search_docs")], max_iters=6)
    bound = set(gatherer.tools)

    assert "search_docs" in bound
    # ReActV2 adds its own terminal submit tool and nothing else.
    assert bound - {"submit"} == {"search_docs"}


def test_each_route_gets_its_own_gatherer() -> None:
    """A shared node would alias every route's optimizer write-back together."""
    built = [
        build_gatherer(route, [_tool("search_docs")], max_iters=6) for route in ROUTES
    ]
    assert len({id(node) for node in built}) == len(ROUTES)
    assert len({id(node.signature) for node in built}) == len(ROUTES)


def test_zebra_editing_markdown_changes_the_live_prompt(tmp_path, monkeypatch) -> None:
    """The Markdown is the single source of truth, not a copy of a docstring."""
    copy = tmp_path / "agents"
    (copy / "prompts").mkdir(parents=True)
    for name in ("fleet_agent.yaml", "prompts/policy.md", "prompts/evidence.md"):
        (copy / name).write_text((AGENTS_DIR / name).read_text())
    (copy / "prompts" / "synthesize.md").write_text("Rewritten prompt for the test.")

    import app.agent.signature as sig

    monkeypatch.setattr(sig, "AGENTS_DIR", copy)
    monkeypatch.setattr(sig, "SPEC_PATH", copy / "fleet_agent.yaml")
    sig.synthesis_spec.cache_clear()
    sig.build_synthesizer.cache_clear()
    try:
        program = sig.build_synthesizer()
        assert "Rewritten prompt for the test." in program.signature.instructions
    finally:
        sig.synthesis_spec.cache_clear()
        sig.build_synthesizer.cache_clear()


def test_optimizer_state_round_trips_into_the_live_program() -> None:
    """A GEPA-style write-back reaches the running program, and only its own."""
    program = build_program(_synthesizer_spec())
    before = program.signature.instructions
    state = program.dump_state()

    # A bare top-level node is its own predictor, so its optimizer path is "self"
    # rather than the YAML node name (dspy's named_predictors() convention).
    paths = [key for key in state if key not in {"structure_hash", "metadata"}]
    assert paths == ["self"]
    state[paths[0]] = OPTIMIZED_INSTRUCTIONS
    applied = program.apply_state(state)

    assert applied == paths
    assert program.signature.instructions == OPTIMIZED_INSTRUCTIONS
    assert program.signature.instructions != before


def test_state_from_a_different_structure_is_refused() -> None:
    program = build_program(_synthesizer_spec())
    state = program.dump_state()
    state["structure_hash"] = "sha256:tampered"

    with pytest.raises(SpecError, match="different spec"):
        program.apply_state(state)


def test_fleet_agent_uses_the_declared_prompts() -> None:
    """The production program must be wired to the declarative definitions."""
    for route in ROUTES:
        gatherer = build_gatherer(route, [_tool("search_docs")], max_iters=6)
        assert POLICY_TEXT in gatherer.signature.instructions
        assert _markdown_body(EVIDENCE_MD) in gatherer.signature.instructions

    synthesizer = build_synthesizer()
    assert _markdown_body(SYNTHESIZE_MD) in synthesizer.signature.instructions
    assert FleetAgent is not None  # the program class stays importable


def test_operator_loop_bound_reaches_the_gather_node() -> None:
    """`FleetAgent(max_iters=…)` must bind, not just validate.

    The bound briefly stopped at the program boundary: the YAML default won and
    `FLEET_AGENT_LLM_MAX_ITERS` did nothing. The program validates the value and
    then threads it into every gather node it builds.
    """
    from app.agent.program import FleetAgent
    from app.agent.tool_registry import TOOL_SPECS, ToolRegistry
    from app.agent.tooling import create_dspy_tool
    from app.agent.tools import search_docs

    registry = ToolRegistry(
        [
            (
                create_dspy_tool(search_docs, name="search_docs"),
                TOOL_SPECS["search_docs"],
            )
        ]
    )
    profiles = {"research": registry.dspy_tools()}

    for bound in (1, 25):
        program = FleetAgent(tool_profiles=profiles, max_iters=bound)
        assert program.evidence_agents["research"].max_iters == bound


def test_fanout_with_multiple_chain_of_thought_branches() -> None:
    """Fanout must merge declared outputs without DSPy reasoning collisions."""
    from app.agent.spec.loader import build_program
    from app.agent.spec.schema import AgentSpec

    spec = AgentSpec(
        agent="fanout-test",
        root="parallel_step",
        signatures=[
            {
                "name": "SigA",
                "instructions": "Step A",
                "inputs": [{"name": "q", "type": "str"}],
                "outputs": [{"name": "out_a", "type": "str"}],
            },
            {
                "name": "SigB",
                "instructions": "Step B",
                "inputs": [{"name": "q", "type": "str"}],
                "outputs": [{"name": "out_b", "type": "str"}],
            },
        ],
        modules={
            "parallel_step": {
                "type": "fanout",
                "branches": ["branch_a", "branch_b"],
            },
            "branch_a": {"type": "chain_of_thought", "signature": "SigA"},
            "branch_b": {"type": "chain_of_thought", "signature": "SigB"},
        },
    )
    program = build_program(spec)

    class MockLM(dspy.LM):
        def __init__(self) -> None:
            super().__init__("openai/mock")

        def __call__(
            self,
            prompt: Any = None,
            messages: Any = None,
            **kwargs: Any,
        ) -> list[str]:
            text = str(messages or prompt)
            if "Step A" in text:
                return ['{"reasoning": "thought A", "out_a": "ans_a"}']
            return ['{"reasoning": "thought B", "out_b": "ans_b"}']

    with dspy.context(lm=MockLM(), adapter=dspy.JSONAdapter()):
        pred = program(q="test question")
    assert pred.out_a == "ans_a"
    assert pred.out_b == "ans_b"
