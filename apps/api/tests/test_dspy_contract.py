"""DSPy contract tests: pin the dspy==3.3.* assumptions the backend relies on.

These are tripwires, not behavior tests. When one fails after a dependency
bump, the failure message should say which invariant broke and what to do
(see the DSPy invariants in AGENTS.md). Provider-free: ScriptedLM/DummyLM,
no DB, no .env.
"""

import asyncio
import json
from typing import get_args

import dspy
import pytest
from dspy.adapters.types.tool import Tool

from app.agent.engine import AgentRunContext, DspyReActV2Engine
from app.agent.factory import build_dspy_engine
from app.agent.instrumented import instrument_tool
from app.agent.signature import AgentSignature
from app.agent.tools import get_current_time, search_docs
from app.agent.tools.docs import SearchDocsTool
from app.agent.tools.report import WriteReportTool
from tests.helpers.scripted_lm import ScriptedLM, submit_call

CTX = AgentRunContext(thread_id="t-1", run_id="r-1")


# ---------------------------------------------------------------------------
# 1. ReActV2 alias guard — dspy.ReActV2 is removed in 3.6 (rename to
#    dspy.ReAct required on upgrade; legacy dspy.ReAct has DIFFERENT behavior).
# ---------------------------------------------------------------------------


def test_react_v2_alias_still_exists():
    if not hasattr(dspy, "ReActV2"):
        pytest.fail(
            "dspy.ReActV2 is gone from this dspy version. DSPy removes the "
            "ReActV2 alias in 3.6 and renames the module to dspy.ReAct — "
            "update app/agent/engine.py + factory.py to the new name and "
            "re-audit termination reasons. Do NOT let the code fall back to "
            "the legacy dspy.ReAct silently."
        )
    assert dspy.ReActV2 is not getattr(dspy, "ReAct", None)


# ---------------------------------------------------------------------------
# 2. Tool schema fidelity — what the model sees must stay typed.
#    Regression test for instrument_tool annotation propagation.
# ---------------------------------------------------------------------------


class _FakeBus:
    cancel_token = None

    def publish_from_worker(self, event) -> None: ...


class _FakeStorage:
    def save(self, *, storage_key: str, content: bytes) -> int:
        return len(content)


def _production_tools() -> list[Tool]:
    report = WriteReportTool(
        storage=_FakeStorage(),
        bus=_FakeBus(),
        thread_id="t",
        max_bytes=1024,
    )
    return [
        Tool(search_docs),
        Tool(get_current_time),
        Tool(instrument_tool(SearchDocsTool(), _FakeBus())),
        Tool(instrument_tool(report, _FakeBus())),
        Tool(instrument_tool(get_current_time, _FakeBus())),
    ]


@pytest.mark.parametrize("tool", _production_tools(), ids=lambda t: t.name)
def test_production_tools_have_typed_schemas(tool: Tool):
    assert tool.name in {"search_docs", "get_current_time", "write_report"}
    # A tool without a description gives the model nothing to select on.
    assert tool.desc and tool.desc.strip()

    if tool.name == "search_docs":
        assert tool.args == {"query": {"type": "string"}}
    elif tool.name == "write_report":
        assert tool.args == {
            "title": {"type": "string"},
            "content": {"type": "string"},
        }
    else:  # get_current_time takes no arguments
        assert tool.args == {}


def test_instrumented_wrapper_keeps_return_annotation():
    """The wrapper must expose the real signature, not (**kwargs) -> Any."""
    wrapped = instrument_tool(get_current_time, _FakeBus())
    hints = wrapped.__annotations__
    assert hints.get("return") is str


def test_native_function_call_descriptor_is_wellformed():
    """Adapters send format_as_litellm_function_call() verbatim on the wire."""
    search = Tool(search_docs)
    descriptor = search.format_as_litellm_function_call()
    assert descriptor["type"] == "function"
    assert descriptor["function"]["name"] == "search_docs"
    assert descriptor["function"]["parameters"]["properties"] == {
        "query": {"type": "string"}
    }


# ---------------------------------------------------------------------------
# 3. Tool arg validation — dspy.Tool validates args against the schema before
#    execution; degraded Any schemas skip this silently.
# ---------------------------------------------------------------------------


def test_tool_rejects_args_violating_schema():
    wrapped_search = Tool(instrument_tool(SearchDocsTool(), _FakeBus()))
    with pytest.raises(ValueError, match="Arg query is invalid"):
        wrapped_search(query=12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4. ReActV2 structure guards.
# ---------------------------------------------------------------------------


def test_user_tool_named_submit_is_rejected():
    def submit(**kwargs) -> str:  # noqa: ARG001 — reserved name probe
        """Reserved."""
        return "nope"

    with pytest.raises(ValueError, match="submit"):
        dspy.ReActV2(AgentSignature, tools=[submit], max_iters=2)


def test_submit_tool_exposes_all_signature_outputs_in_order():
    agent = dspy.ReActV2(AgentSignature, tools=[search_docs], max_iters=1)
    submit_tool = agent.tools["submit"]
    expected = list(AgentSignature.output_fields)  # order is model-visible
    assert list(submit_tool.args) == expected


def test_reactv2_wraps_inputs_as_optional():
    """ReActV2's internal signature makes every user input `| None` so the
    loop can drop them across turns."""
    agent = dspy.ReActV2(AgentSignature, tools=[search_docs], max_iters=1)
    user_request = agent.react.signature.input_fields["user_request"]
    assert type(None) in get_args(user_request.annotation)


# ---------------------------------------------------------------------------
# 5. Signature contract — docstring IS the instructions; field names/order are
#    part of the program's public interface (optimizers never rename them).
# ---------------------------------------------------------------------------


def test_agent_signature_contract():
    assert list(AgentSignature.input_fields) == ["user_request"]
    assert list(AgentSignature.output_fields) == [
        "answer",
        "process_summary",
        "key_decisions",
        "caveats",
    ]
    instructions = AgentSignature.instructions
    assert "Do not expose hidden reasoning" in instructions


# ---------------------------------------------------------------------------
# 6. Adapter behavior pin — empty_tool_calls is only reachable with a
#    NON-native adapter; under native function calling the same model turn
#    surfaces as parse_error instead.
# ---------------------------------------------------------------------------


def _make_engine(steps: list, *, use_native: bool) -> DspyReActV2Engine:
    lm = ScriptedLM(steps)

    def factory() -> dspy.ReActV2:
        return dspy.ReActV2(AgentSignature, tools=[search_docs], max_iters=3)

    return DspyReActV2Engine(
        agent_factory=factory,
        lm=lm,  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(use_native_function_calling=use_native),
    )


async def test_empty_tool_calls_only_with_non_native_adapter():
    # Content parses as a complete non-native output object whose tool_calls
    # list is empty -> ReActV2 breaks with empty_tool_calls.
    content_turn = {
        "calls": [],
        "content": json.dumps({"next_thought": "", "tool_calls": []}),
    }

    non_native = await _make_engine([content_turn] * 2, use_native=False).run(
        user_request="hi", history=None, context=CTX
    )
    assert non_native.termination_reason == "empty_tool_calls"
    assert non_native.error_code == "agent_no_output"

    # Under native calling, content-only turns cannot produce tool call
    # objects and fail output parsing instead.
    plain_content = {"calls": [], "content": "no tools today"}
    native = await _make_engine([plain_content] * 2, use_native=True).run(
        user_request="hi", history=None, context=CTX
    )
    assert native.termination_reason == "parse_error"
    assert native.error_code == "agent_parse_error"


# ---------------------------------------------------------------------------
# 7. Termination matrix — every reason ReActV2 can emit maps to the public
#    error taxonomy (or completes).
# ---------------------------------------------------------------------------


def test_unknown_termination_reason_falls_back_to_agent_no_output():
    # _map_result consults the reason map only for failed runs; feed it a
    # failed prediction carrying a reason no current dspy version emits.
    from app.agent.engine import AgentRunResult, _map_result

    prediction = dspy.Prediction(
        answer=None,
        termination_reason="some_future_reason",
        history=dspy.History(messages=[]),
    )
    result = _map_result(prediction)
    assert isinstance(result, AgentRunResult)
    assert result.status == "failed"
    assert result.error_code == "agent_no_output"


# ---------------------------------------------------------------------------
# 8. Usage contract — keys and types of AgentRunResult.usage.
# ---------------------------------------------------------------------------


async def test_usage_keys_are_exact_and_summed():
    engine = _make_engine(
        [
            [{"name": "search_docs", "args": {"query": "x"}}],
            [submit_call(answer="done")],
        ],
        use_native=True,
    )
    result = await engine.run(user_request="hi", history=None, context=CTX)
    assert set(result.usage) <= {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    assert all(isinstance(v, int) for v in result.usage.values())
    # ScriptedLM emits 10/5/15 per call, two calls -> doubled.
    assert result.usage == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
    }


# ---------------------------------------------------------------------------
# 9. Context isolation — concurrent runs must not bleed LM config or usage.
# ---------------------------------------------------------------------------


async def test_concurrent_runs_isolate_lm_and_usage():
    def make(steps: list) -> DspyReActV2Engine:
        lm = ScriptedLM(steps)
        lm.model = f"scripted-{id(steps)}"  # distinct usage key per engine

        def factory() -> dspy.ReActV2:
            return dspy.ReActV2(AgentSignature, tools=[search_docs], max_iters=2)

        return DspyReActV2Engine(
            agent_factory=factory,
            lm=lm,  # type: ignore[arg-type]
            adapter=dspy.JSONAdapter(use_native_function_calling=True),
        )

    engine_a = make(
        [[{"name": "search_docs", "args": {"query": "a"}}], [submit_call()]]
    )
    engine_b = make(
        [[{"name": "search_docs", "args": {"query": "b"}}], [submit_call()]]
    )

    result_a, result_b = await asyncio.gather(
        engine_a.run(user_request="a", history=None, context=CTX),
        engine_b.run(user_request="b", history=None, context=CTX),
    )

    assert result_a.status == "completed"
    assert result_b.status == "completed"
    # Each run accounted exactly its own two calls — no cross-run doubling.
    assert result_a.usage["total_tokens"] == 30
    assert result_b.usage["total_tokens"] == 30


# ---------------------------------------------------------------------------
# 10. Sync-tools invariant — ReActV2 executes tools synchronously; an async
#     tool raises instead of deadlocking. Future MCP bridging MUST go through
#     an async entry point (Tool.from_mcp_tool is async-only).
# ---------------------------------------------------------------------------


async def test_async_tool_raises_under_sync_loop():
    pytest.importorskip("dspy")
    import warnings

    async def fetch_thing(query: str) -> str:
        """Async tool that must not be silently driven from the sync loop."""
        return "result"

    engine = _make_engine(
        [[{"name": "fetch_thing", "args": {"query": "x"}}]],
        use_native=True,
    )
    engine._agent_factory = lambda: dspy.ReActV2(
        AgentSignature, tools=[fetch_thing], max_iters=2
    )
    # ReActV2 converts the raised ValueError into an error observation; the
    # dangling coroutine warning is the expected artifact of the refusal.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = await engine.run(user_request="hi", history=None, context=CTX)
    first_turn = result.history.messages[0]
    (tool_result,) = first_turn["tool_calls"].tool_call_results.tool_call_results
    assert tool_result.is_error is True


# ---------------------------------------------------------------------------
# 11. History round-trip — persisted continuation format stays JSON-safe and
#     server-side only.
# ---------------------------------------------------------------------------


async def test_history_round_trips_through_json_and_continues():
    engine = _make_engine(
        [
            [{"name": "search_docs", "args": {"query": "x"}}],
            [submit_call(answer="First.")],
        ],
        use_native=True,
    )
    first = await engine.run(user_request="q1", history=None, context=CTX)

    dumped = first.history.model_dump(mode="json")
    json.dumps(dumped)  # must be JSONB-ready without custom encoders
    restored = dspy.History.model_validate(dumped)

    engine2 = _make_engine([[submit_call(answer="Second.")]], use_native=True)
    second = await engine2.run(user_request="q2", history=restored, context=CTX)

    assert second.status == "completed"
    assert second.answer == "Second."
    assert len(second.history.messages) == len(first.history.messages) + 1


def test_reasoning_field_never_reaches_public_result():
    """CoT boundary, structurally pinned: `next_thought` (the ReActV2
    Reasoning output field) exists on the loop's internal signature and in
    history events server-side. AgentRunResult carries `history` as a
    documented SERVER-ONLY field (never serialized to clients — enforced by
    test_dspy_engine.py), but no public field can carry raw reasoning."""
    agent = dspy.ReActV2(AgentSignature, tools=[search_docs], max_iters=1)
    assert "next_thought" in agent.react.signature.output_fields

    from app.agent.engine import AgentRunResult

    assert "next_thought" not in AgentRunResult.__dataclass_fields__
    # The only reasoning-bearing member is the server-side history slot.
    assert "history" in AgentRunResult.__dataclass_fields__


# ---------------------------------------------------------------------------
# 12. Factory wiring — production engine uses native calling + no cache so
#     runs are reproducible and isolated.
# ---------------------------------------------------------------------------


def test_production_engine_builds_native_uncached_lm():
    from pydantic import SecretStr

    from app.settings import Settings

    settings = Settings(llm_api_key=SecretStr("sk-test-contract"))
    engine = build_dspy_engine(settings)
    assert isinstance(engine, DspyReActV2Engine)
    assert isinstance(engine._adapter, dspy.JSONAdapter)
    assert engine._adapter.use_native_function_calling is True
    # cache=False is an LM-instance flag (lm.cache), not a request kwarg —
    # runs must never replay a previous run's provider responses.
    assert engine._lm.cache is False
    assert "sk-test-contract" not in repr(engine._lm)
