"""The program's DSPy construction contract after the spec layer's removal.

The program is built directly from the Markdown prompts (``prompts/evidence.md``,
``prompts/synthesize.md``, shared ``prompts/policy.md``), so these tests pin the
construction facts the declarative loader used to guarantee: real DSPy classes,
least-privilege tool binding, the streaming field list, the DSL-free identity
rules of the build seam, and the explicit tools ``FleetAgent`` accepts.
"""

import dspy
import pytest
from dspy.clients.engines import LM15Engine

from app.agent import gateway
from app.agent.program import FleetAgent
from app.agent.signature import (
    build_gatherer,
    build_signature,
    build_synthesizer,
    prompt_body,
)
from app.agent.tool_registry import ToolMetadata, ToolRegistry
from app.agent.tooling import create_dspy_tool
from app.agent.tools.docs import SearchDocsTool


def test_dspy_native_surface_guard() -> None:
    """The next DSPy bump must fail loudly in CI, not at runtime.

    DSPy 3.5 keeps ``dspy.lm15`` as the public types namespace and
    ``LM15Engine`` (the bundled native router the BYOK engine subclasses) at
    ``dspy.clients.engines``; both are load-bearing while ``dspy==3.5.0`` is
    pinned. The private vendored transport the diagnostics layer used is gone
    entirely: the gateway source must contain none of it.
    """
    for symbol in (
        "AccessPolicy",
        "OpenAIChatCompat",
        "ProviderDefinition",
        "Request",
        "Response",
        "ResponseStream",
        "RouterConfig",
        "StreamDeltaEvent",
        "StreamEndEvent",
        "StreamErrorEvent",
        "StreamStartEvent",
        "ThinkingPart",
        "ToolCallPart",
    ):
        assert hasattr(dspy.lm15, symbol), f"dspy.lm15.{symbol} moved"
    assert issubclass(gateway.GatewayEngine, LM15Engine)

    import inspect
    from pathlib import Path

    source = Path(inspect.getsourcefile(gateway)).read_text(encoding="utf-8")
    assert "_vendor" not in source, "the gateway regained a private DSPy import"


def _search_docs_tool() -> dspy.Tool:
    return create_dspy_tool(SearchDocsTool(), name="search_docs")


def test_gatherer_is_a_real_react_over_the_markdown_contract() -> None:
    """D1 behavior guard: the shipping loop is the DSPy 3.5 ``dspy.ReAct``.

    ``dspy.ReAct`` now carries the implementation and ``dspy.ReActV2`` is a
    deprecated subclass, so asserting the base class is what catches a fallback
    to the old loop. The instructions come from the shared Markdown contract.
    """
    gatherer = build_gatherer([_search_docs_tool()], max_iters=6)

    assert isinstance(gatherer, dspy.ReAct)
    assert type(gatherer) is dspy.ReAct, "the deprecated ReActV2 subclass crept in"
    assert gatherer.max_iters == 6
    assert set(gatherer.tools) == {"search_docs", "submit"}
    # The Evidence node declares one input and no output fields by design: the
    # loop ends when the model stops asking for tools; synthesis writes publics.
    assert list(gatherer.signature.input_fields) == ["user_request"]
    assert list(gatherer.signature.output_fields) == []
    assert gatherer.signature.instructions == (
        f"{prompt_body('evidence.md')}\n\n{prompt_body('policy.md')}"
    )


def test_synthesizer_is_a_predict_over_the_synthesis_contract() -> None:
    synthesizer = build_synthesizer()

    assert isinstance(synthesizer, dspy.Predict)
    signature = synthesizer.signature
    assert list(signature.input_fields) == [
        "user_request",
        "output_intent",
        "evidence_json",
        "history",
    ]
    assert list(signature.output_fields) == [
        "answer",
        "process_summary",
        "key_decisions",
        "caveats",
    ]
    # dspy.History reaches the predictor as a typed field, not a str.
    assert signature.fields["history"].annotation is dspy.History
    assert signature.instructions == (
        f"{prompt_body('synthesize.md')}\n\n{prompt_body('policy.md')}"
    )


def test_program_composes_routed_react_over_least_privilege_profiles() -> None:
    tool = _search_docs_tool()
    program = FleetAgent(
        tool_profiles={"research": [tool], "artifact": [tool], "direct": []}
    )

    assert isinstance(program, dspy.Module)
    assert program.synthesis_stream_fields == ("answer", "process_summary")
    predictor_names = set(dict(program.named_predictors()))
    assert "router" in predictor_names
    assert "synthesizer" in predictor_names
    assert any(name.startswith("evidence_agents") for name in predictor_names)
    # A profile with no tools has nothing to gather: no loop at all.
    assert set(program.evidence_agents) == {"research", "artifact"}
    assert program.tool_names["direct"] == ()
    assert program.tool_names["artifact"] == ("search_docs",)


def test_build_signature_builds_a_fresh_class_per_name() -> None:
    fields = {"x": (str, dspy.InputField(desc="X."))}
    first = build_signature(fields, "Do X.", signature_name="First")
    second = build_signature(fields, "Do X.", signature_name="Second")

    assert first is not second
    assert first.instructions == second.instructions


def test_build_signature_requires_instruction_text() -> None:
    with pytest.raises(ValueError, match="has no instruction text"):
        build_signature({}, "   ", signature_name="Empty")


def test_synthesis_report_wire_fields_accept_markdown_and_empty_lists() -> None:
    from app.agent.signature import build_synthesizer

    signature = build_synthesizer().signature
    response = (
        "[[ ## answer ## ]]\n# Report\nProject Juniper; budget 730 units.\n"
        "[[ ## process_summary ## ]]\nRestated the selected branch facts.\n"
        "[[ ## key_decisions ## ]]\n[]\n"
        '[[ ## caveats ## ]]\n["Currency was not specified."]\n'
        "[[ ## completed ## ]]"
    )
    parsed = dspy.ChatAdapter().parse(signature, response)
    assert parsed["answer"].startswith("# Report")
    assert parsed["key_decisions"] == []
    assert parsed["caveats"] == ["Currency was not specified."]


# ---------------------------------------------------------------------------
# First-class ``FleetAgent`` module: explicit tools, tool binding, and the
# registry that feeds construction.
# ---------------------------------------------------------------------------


def lookup_docs(query: str) -> str:
    """Look up a short query in the test documentation."""
    return f"found:{query}"


def test_fleet_agent_is_a_first_class_dspy_module() -> None:
    tool = create_dspy_tool(lookup_docs)
    program = FleetAgent(tool_profiles={"research": [tool]}, max_iters=4)

    assert isinstance(program, dspy.Module)
    assert program.tool_names["research"] == ("lookup_docs",)
    assert program.tool_names["direct"] == ()
    # The spec resolves the tool by name, so the bound tool is an equivalent
    # dspy.Tool rather than the same object; the model-visible contract is what
    # must survive.
    bound = program.evidence_agents["research"].tools["lookup_docs"]
    assert (bound.name, bound.desc, bound.args) == (tool.name, tool.desc, tool.args)
    # DSPy's module tree walks the dict the profile agents live in, so the
    # router, every evidence loop, and the synthesizer stay optimizable.
    names = [name for name, _ in program.named_predictors()]
    assert "router" in names
    assert "synthesizer" in names
    assert "evidence_agents['research'].react" in names


def test_fleet_agent_requires_explicit_dspy_tools() -> None:
    with pytest.raises(TypeError, match="explicit dspy.Tool"):
        FleetAgent(tool_profiles={"research": [lookup_docs]}, max_iters=2)  # type: ignore[list-item]


def test_fleet_agent_rejects_async_tools_under_sync_react() -> None:
    async def async_lookup(query: str) -> str:
        """Look up a query asynchronously."""
        return query

    tool = create_dspy_tool(async_lookup)
    with pytest.raises(TypeError, match="executes tools synchronously"):
        FleetAgent(tool_profiles={"research": [tool]}, max_iters=2)


def test_tool_registry_creates_real_dspy_tools() -> None:
    metadata = ToolMetadata(name="lookup_docs", timeout_seconds=5)
    registry = ToolRegistry([(lookup_docs, metadata)])

    registered = registry.get("lookup_docs")
    assert isinstance(registered.tool, dspy.Tool)
    assert registered.tool.name == "lookup_docs"
    assert registered.tool.desc.startswith("Look up a short query")
    assert registered.tool.args == {"query": {"type": "string"}}
    assert registry.dspy_tools() == [registered.tool]


def test_tool_registry_accepts_prebuilt_tool_without_rewrapping() -> None:
    tool = create_dspy_tool(
        lookup_docs,
        name="docs",
        description="Search the test documentation by query.",
        arg_descriptions={"query": "The short search query."},
    )
    registry = ToolRegistry([(tool, ToolMetadata(name="docs"))])

    assert registry.get("docs").tool is tool
    assert tool.args["query"]["description"] == "The short search query."


def test_tool_registry_rejects_prebuilt_name_drift() -> None:
    tool = create_dspy_tool(lookup_docs, name="docs")
    with pytest.raises(ValueError, match="does not match metadata"):
        ToolRegistry([(tool, ToolMetadata(name="other"))])


def test_tool_registry_rejects_untyped_arguments() -> None:
    def untyped_lookup(query) -> str:  # type: ignore[no-untyped-def]
        """Look up an untyped query."""
        return str(query)

    with pytest.raises(TypeError, match="untyped argument"):
        create_dspy_tool(untyped_lookup)


def test_tool_registry_rejects_invalid_names_and_variadic_schemas() -> None:
    def variadic(**kwargs: str) -> str:
        """Return variadic values."""
        return str(kwargs)

    with pytest.raises(ValueError, match="tool names"):
        create_dspy_tool(lookup_docs, name="invalid tool")
    with pytest.raises(TypeError, match="unsupported parameter"):
        create_dspy_tool(variadic)


def test_tool_registry_requires_a_typed_return_value() -> None:
    def missing_return(query: str):  # type: ignore[no-untyped-def]
        """Return a value without declaring its type."""
        return query

    with pytest.raises(TypeError, match="return annotation"):
        create_dspy_tool(missing_return)


def test_sync_registry_rejects_async_tools() -> None:
    async def async_lookup(query: str) -> str:
        """Look up a query asynchronously."""
        return query

    tool = create_dspy_tool(async_lookup)
    with pytest.raises(TypeError, match="execute tools synchronously"):
        ToolRegistry([(tool, ToolMetadata(name="async_lookup"))])


def test_tool_allowlist_selects_availability_not_execution() -> None:
    def current_time() -> str:
        """Return a deterministic test time."""
        return "now"

    registry = ToolRegistry(
        [
            (lookup_docs, ToolMetadata(name="lookup_docs")),
            (current_time, ToolMetadata(name="current_time")),
        ]
    )

    selected = registry.dspy_tools(allowed_names=["lookup_docs"])
    assert [tool.name for tool in selected] == ["lookup_docs"]
    with pytest.raises(KeyError, match="unknown tool"):
        registry.dspy_tools(allowed_names=["missing"])


def test_factory_builds_fleet_agent_with_explicit_tools() -> None:
    from pydantic import SecretStr

    from app.agent.factory import build_dspy_engine
    from app.settings import Settings

    settings = Settings(
        llm_model="openai/test-model",
        llm_api_key=SecretStr("sk-test"),
        llm_max_iters=3,
    )
    engine = build_dspy_engine(settings)
    program = engine._program_factory()  # type: ignore[attr-defined]

    assert isinstance(program, FleetAgent)
    assert program.tool_names["research"] == ("search_docs", "get_current_time")
    assert program.tool_names["direct"] == ()
