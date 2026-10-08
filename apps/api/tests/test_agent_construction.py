"""The program's DSPy construction contract after the spec layer's removal.

The program is built directly from the Markdown prompts (``prompts/evidence.md``,
``prompts/synthesize.md``, shared ``prompts/policy.md``), so these tests pin the
construction facts the declarative loader used to guarantee: real DSPy classes,
least-privilege tool binding, the streaming field list, and the DSL-free
identity rules of the build seam.
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
from app.agent.tooling import create_dspy_tool
from app.agent.tools.docs import SearchDocsTool


def test_dspy_native_surface_guard() -> None:
    """The next DSPy bump must fail loudly in CI, not at runtime.

    DSPy 3.4 documents ``dspy.lm15`` as the public types namespace and
    ``LM15Engine`` (the bundled native router the BYOK engine subclasses) via
    ``dspy.clients.engines`` — both while ``dspy==3.4.0`` is pinned and the
    ``3.5`` migration deadline approaches. The private vendored transport the
    diagnostics layer used is gone entirely: the gateway source must contain
    none of it.
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


def test_gatherer_is_a_real_reactv2_over_the_markdown_contract() -> None:
    gatherer = build_gatherer([_search_docs_tool()], max_iters=6)

    assert isinstance(gatherer, dspy.ReActV2)
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
    assert list(signature.input_fields) == ["user_request", "evidence_json", "history"]
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


def test_program_composes_routed_reactv2_over_least_privilege_profiles() -> None:
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
