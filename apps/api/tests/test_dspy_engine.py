import asyncio
import json
import threading
from collections.abc import Callable

import dspy
import pytest
from dspy.utils.exceptions import ContextWindowExceededError

from app.agent.engine import AgentRunContext, AgentRunResult, DspyAgentEngine
from app.agent.program import FleetAgent
from app.agent.tooling import create_dspy_tool
from tests.helpers.scripted_lm import (
    RecordingScriptedLM,
    ScriptedLM,
    evidence_end,
    router_call,
    submit_call,
    synthesis_call,
)
from tests.helpers.signatures import AgentSignature

CTX = AgentRunContext(thread_id="t-1", run_id="r-1")


def make_engine(
    steps: list,
    tools: list | None = None,
    max_iters: int = 4,
    cleanup: Callable[[], None] | None = None,
) -> DspyAgentEngine:
    from app.agent.tools.docs import SearchDocsTool

    lm = ScriptedLM(steps)

    def factory() -> dspy.ReAct:
        return dspy.ReAct(
            AgentSignature,
            tools=tools if tools is not None else [SearchDocsTool()],
            max_iters=max_iters,
        )

    return DspyAgentEngine(
        program_factory=factory,
        lm=lm,  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
        cleanup=cleanup,
    )


async def run(
    engine: DspyAgentEngine, request: str = "How does state sync work?", history=None
):
    return await engine.run(user_request=request, history=history, context=CTX)


async def test_tool_free_request_completes():
    engine = make_engine([[submit_call(answer="It just works.")]])
    result = await run(engine)

    assert result.status == "completed"
    assert result.answer == "It just works."
    assert result.process_summary == "Looked things up."
    assert result.termination_reason == "submit"
    assert result.error_code is None
    assert result.usage["total_tokens"] == 15


async def test_cleanup_runs_after_success_and_cannot_replace_result():
    cleanup_calls = 0

    def cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise RuntimeError("cleanup failed")

    engine = make_engine([[submit_call(answer="It just works.")]], cleanup=cleanup)
    result = await run(engine)

    assert result.status == "completed"
    assert result.answer == "It just works."
    assert cleanup_calls == 1


async def test_cleanup_runs_when_agent_construction_raises():
    cleanup_calls = 0

    def cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    def factory() -> dspy.ReAct:
        raise RuntimeError("agent construction failed")

    engine = DspyAgentEngine(
        program_factory=factory,
        lm=ScriptedLM([]),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
        cleanup=cleanup,
    )

    with pytest.raises(RuntimeError, match="agent construction failed"):
        await run(engine)
    assert cleanup_calls == 1


async def test_cleanup_waits_for_worker_after_outer_cancellation():
    started = threading.Event()
    release = threading.Event()
    cleaned = threading.Event()

    class BlockingAgent:
        def __call__(self, **kwargs: object) -> dspy.Prediction:
            del kwargs
            started.set()
            release.wait(timeout=5)
            return dspy.Prediction(
                answer="Done.",
                process_summary="Done.",
                key_decisions=[],
                caveats=[],
                termination_reason="submit",
            )

    def factory() -> dspy.ReAct:
        return BlockingAgent()  # type: ignore[return-value]

    def cleanup() -> None:
        cleaned.set()

    engine = DspyAgentEngine(
        program_factory=factory,
        lm=ScriptedLM([]),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
        cleanup=cleanup,
    )
    task = asyncio.create_task(run(engine))

    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not cleaned.is_set()
    finally:
        release.set()
        assert await asyncio.to_thread(cleaned.wait, 2)


async def test_one_tool_request_completes():
    engine = make_engine(
        [
            [{"name": "search_docs", "args": {"query": "AG-UI"}}],
            [submit_call(answer="Uses JSON Patch.")],
        ]
    )
    result = await run(engine)

    assert result.status == "completed"
    assert result.answer == "Uses JSON Patch."
    assert result.termination_reason == "submit"
    # Two history turns: tool execution + submit.
    assert len(result.history.messages) == 2


async def test_multi_tool_request_completes():
    from app.agent.tools import get_current_time
    from app.agent.tools.docs import SearchDocsTool

    engine = make_engine(
        [
            [
                {"name": "search_docs", "args": {"query": "protocol"}},
                {"name": "get_current_time", "args": {}},
            ],
            [submit_call(answer="Used both tools.")],
        ],
        tools=[SearchDocsTool(), get_current_time],
    )
    result = await run(engine)

    assert result.status == "completed"
    assert result.answer == "Used both tools."
    first_turn = result.history.messages[0]
    results = first_turn["tool_calls"].tool_call_results.tool_call_results
    assert len(results) == 2
    assert all(not r.is_error for r in results)


async def test_tool_exception_is_recoverable():
    def exploding_tool() -> str:
        """Always fails, for recovery testing."""
        raise RuntimeError("search backend exploded with key abc123")

    engine = make_engine(
        [
            [{"name": "exploding_tool", "args": {}}],
            [submit_call(answer="Recovered gracefully.")],
        ],
        tools=[exploding_tool],
    )
    result = await run(engine)

    assert result.status == "completed"
    assert result.answer == "Recovered gracefully."
    first_turn = result.history.messages[0]
    (tool_result,) = first_turn["tool_calls"].tool_call_results.tool_call_results
    assert tool_result.is_error is True
    assert "search backend exploded" in tool_result.value


async def test_missing_final_output_maps_to_public_error_code():
    # max_iters=1: one tool turn; forced submit omits `answer` -> the submit
    # tool raises, no final outputs -> termination_reason=max_iters.
    engine = make_engine(
        [
            [{"name": "search_docs", "args": {"query": "x"}}],
            [
                {
                    "name": "submit",
                    "args": {
                        "process_summary": "Tried.",
                        "key_decisions": [],
                        "caveats": [],
                    },
                }
            ],
        ],
        max_iters=1,
    )
    result = await run(engine)

    assert result.status == "failed"
    assert result.answer is None
    assert result.termination_reason == "max_iters"
    assert result.error_code == "agent_no_output"


async def test_unparseable_model_output_maps_to_agent_parse_error():
    # Under JSONAdapter + native function calling, a tool-calls-free turn with
    # unparseable content raises AdapterParseError -> break_reason=parse_error
    # (empty_tool_calls is only reachable with non-native adapters).
    engine = make_engine(
        [
            {"calls": [], "content": "definitely not structured output"},
            {"calls": [], "content": "still not structured output"},
        ]
    )
    result = await run(engine)

    assert result.status == "failed"
    assert result.termination_reason == "parse_error"
    assert result.error_code == "agent_parse_error"


async def test_context_window_maps_to_specific_error_code():
    engine = make_engine(
        [
            ContextWindowExceededError(message="context_length_exceeded"),
            ContextWindowExceededError(message="context_length_exceeded"),
        ]
    )
    result = await run(engine)

    assert result.status == "failed"
    assert result.termination_reason == "context_window_exceeded"
    assert result.error_code == "agent_context_limit"


async def test_forced_submit_success_carries_diagnostic_caveat():
    # max_iters=1: one normal tool turn, then the forced submit succeeds.
    engine = make_engine(
        [
            [{"name": "search_docs", "args": {"query": "x"}}],
            [submit_call(answer="Partial answer.")],
        ],
        max_iters=1,
    )
    result = await run(engine)

    assert result.status == "completed"
    assert result.termination_reason == "forced_submit"
    assert any("summarized from partial progress" in c for c in result.caveats)


async def test_continuation_history_across_two_turns():
    engine = make_engine([[submit_call(answer="First answer.")]])
    first = await run(engine)
    assert first.history is not None
    first_turns = len(first.history.messages)

    engine2 = make_engine([[submit_call(answer="Second answer.")]])
    second = await run(engine2, history=first.history)

    assert second.status == "completed"
    assert second.answer == "Second answer."
    # History accumulates the new turn.
    assert len(second.history.messages) == first_turns + 1


def test_result_public_fields_never_contain_chain_of_thought():
    result_fields = set(AgentRunResult.__dataclass_fields__)
    assert "next_thought" not in result_fields
    assert "nextThought" not in result_fields


async def test_public_result_json_contains_no_raw_reasoning():
    engine = make_engine([[submit_call()]])
    result = await run(engine)
    public_json = json.dumps(
        {
            "status": result.status,
            "answer": result.answer,
            "process_summary": result.process_summary,
            "key_decisions": result.key_decisions,
            "caveats": result.caveats,
            "termination_reason": result.termination_reason,
            "usage": result.usage,
        }
    )
    assert "next_thought" not in public_json
    assert "history" not in public_json


async def test_usage_is_accumulated_across_model_calls():
    engine = make_engine(
        [
            [{"name": "search_docs", "args": {"query": "x"}}],
            [submit_call()],
        ]
    )
    result = await run(engine)
    assert result.usage["total_tokens"] == 30
    assert result.usage["prompt_tokens"] == 20


# ---------------------------------------------------------------------------
# Engine/program boundary — the engine is strategy-neutral: it runs any
# ``dspy.Module`` and also the first-class ``FleetAgent`` program.
# ---------------------------------------------------------------------------


class StaticProgram(dspy.Module):  # type: ignore[misc]
    def forward(
        self,
        *,
        user_request: str,
        history: dspy.History | None = None,
    ) -> dspy.Prediction:
        del user_request
        return dspy.Prediction(
            answer="Done.",
            process_summary="Used the DSPy program boundary.",
            key_decisions=[],
            caveats=[],
            history=history or dspy.History(messages=[]),
            termination_reason="submit",
        )


async def test_strategy_neutral_engine_runs_a_dspy_module() -> None:
    program = StaticProgram()
    engine = DspyAgentEngine(
        program_factory=lambda: program,
        lm=ScriptedLM([]),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
    )

    result = await engine.run(user_request="go", history=None, context=CTX)

    assert result.status == "completed"
    assert result.answer == "Done."
    assert result.termination_reason == "submit"


async def test_engine_runs_the_first_class_fleet_agent_program() -> None:
    def lookup(query: str) -> str:
        """Look up one deterministic value."""
        return f"found:{query}"

    tool = create_dspy_tool(lookup)
    engine = DspyAgentEngine(
        program_factory=lambda: FleetAgent(
            tool_profiles={"research": [tool]}, max_iters=3
        ),
        lm=ScriptedLM(
            [
                router_call("research"),
                [{"name": "lookup", "args": {"query": "x"}}],
                evidence_end(),
                synthesis_call(answer="Used the tool.", summary="Looked it up."),
            ]
        ),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
    )

    result = await engine.run(user_request="look it up", history=None, context=CTX)

    assert result.status == "completed"
    assert result.answer == "Used the tool."
    assert result.termination_reason == "synthesis"
    # Two evidence turns: the tool call, then the empty ``submit`` that ends the
    # loop. ``submit`` is a real terminal condition, so it is recorded like any
    # other turn rather than being an out-of-band loop exit.
    assert len(result.history.messages) == 2
    assert result.history.messages[-1]["tool_calls"].tool_calls[0].name == "submit"


async def test_stream_does_not_require_react_internals() -> None:
    engine = DspyAgentEngine(
        program_factory=StaticProgram,
        lm=ScriptedLM([]),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
    )

    updates = [
        update
        async for update in engine.stream(
            user_request="go",
            history=None,
            context=CTX,
        )
    ]

    assert [update.kind for update in updates] == ["final_fields", "result"]
    assert updates[0].answer == "Done."
    assert updates[1].result is not None
    assert updates[1].result.answer == "Done."


async def test_fleet_agent_multi_turn_stateful_history() -> None:
    # Turn 1: direct route, answers the first question.
    engine1 = DspyAgentEngine(
        program_factory=lambda: FleetAgent(tool_profiles={"direct": []}, max_iters=3),
        lm=RecordingScriptedLM(
            [
                router_call("direct"),
                synthesis_call(
                    answer="RLM is a recursive language model.",
                    summary="Explained RLM.",
                ),
            ]
        ),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
    )

    result1 = await engine1.run(
        user_request="can you explain to me what is a rlm",
        history=None,
        context=CTX,
    )

    assert result1.status == "completed"
    assert result1.answer == "RLM is a recursive language model."
    assert result1.history is not None
    assert len(result1.history.messages) == 1
    assert (
        result1.history.messages[0]["user_request"]
        == "can you explain to me what is a rlm"
    )
    assert result1.history.messages[0]["answer"] == "RLM is a recursive language model."

    # Turn 2: follow-up passing continuation history.
    turn2_lm = RecordingScriptedLM(
        [
            router_call("direct"),
            synthesis_call(
                answer=(
                    "RLMs use recursion to decompose complex tasks "
                    "into smaller prompts."
                ),
                summary="Detailed RLM mechanics.",
            ),
        ]
    )
    engine2 = DspyAgentEngine(
        program_factory=lambda: FleetAgent(tool_profiles={"direct": []}, max_iters=3),
        lm=turn2_lm,  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
    )

    result2 = await engine2.run(
        user_request="go in depth",
        history=result1.history,
        context=CTX,
    )

    assert result2.status == "completed"
    assert "RLMs use recursion" in (result2.answer or "")
    assert result2.history is not None
    assert len(result2.history.messages) == 2

    # The synthesis predictor received the prior turn in context: the
    # recording LM captures the request DSPy 3.5 actually sends.
    synthesis_requests = turn2_lm.requests_mentioning("evidence_json")
    assert synthesis_requests, "Synthesizer must have been called"
    synth_text = synthesis_requests[-1]
    assert "can you explain to me what is a rlm" in synth_text
    assert "RLM is a recursive language model." in synth_text
    assert "go in depth" in synth_text
