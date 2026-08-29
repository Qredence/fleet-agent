import asyncio
import json
import threading
from collections.abc import Callable

import dspy
import pytest
from dspy.utils.exceptions import ContextWindowExceededError

from app.agent.engine import AgentRunContext, AgentRunResult, DspyAgentEngine
from app.agent.signature import AgentSignature
from tests.helpers.scripted_lm import ScriptedLM, submit_call

CTX = AgentRunContext(thread_id="t-1", run_id="r-1")


def make_engine(
    steps: list,
    tools: list | None = None,
    max_iters: int = 4,
    cleanup: Callable[[], None] | None = None,
) -> DspyAgentEngine:
    """
    Create a DspyAgentEngine configured with a scripted language model.
    
    Parameters:
        steps (list): Scripted model responses used during execution.
        tools (list | None): Tools made available to the agent. Defaults to document search.
        max_iters (int): Maximum number of agent iterations.
        cleanup (Callable[[], None] | None): Optional callback invoked when execution finishes.
    
    Returns:
        DspyAgentEngine: The configured agent engine.
    """
    from app.agent.tools import search_docs

    lm = ScriptedLM(steps)

    def factory() -> dspy.ReActV2:
        """Create a configured ReActV2 agent for the test engine."""
        return dspy.ReActV2(
            AgentSignature,
            tools=tools if tools is not None else [search_docs],
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
    """
    Run the agent engine with a request and shared test context.
    
    Parameters:
        engine (DspyAgentEngine): Engine used to process the request.
        request (str): User request to submit.
        history: Optional conversation history.
    
    Returns:
        The engine's run result.
    """
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

    def factory() -> dspy.ReActV2:
        """Raise an error indicating that agent construction failed."""
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

    def factory() -> dspy.ReActV2:
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
    from app.agent.tools import get_current_time, search_docs

    engine = make_engine(
        [
            [
                {"name": "search_docs", "args": {"query": "protocol"}},
                {"name": "get_current_time", "args": {}},
            ],
            [submit_call(answer="Used both tools.")],
        ],
        tools=[search_docs, get_current_time],
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
