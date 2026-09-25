from __future__ import annotations

from typing import Any

import dspy

from app.agent.engine import (
    AgentRunContext,
    DspyAgentEngine,
)
from app.agent.program import FleetAgent
from app.agent.tooling import create_dspy_tool
from tests.helpers.scripted_lm import (
    ScriptedLM,
    evidence_end,
    router_call,
    synthesis_call,
)

CTX = AgentRunContext(thread_id="thread-1", run_id="run-1")


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


async def test_stream_does_not_require_react_v2_internals() -> None:
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
    recorded_calls: list[list[dict[str, Any]]] = []

    class MultiTurnRecordingLM(ScriptedLM):
        def forward(self, prompt=None, messages=None, **kwargs):  # noqa: ANN001, ANN201
            if messages:
                recorded_calls.append(list(messages))
            return super().forward(prompt=prompt, messages=messages, **kwargs)

    # Turn 1: direct route, answers RLM question
    turn1_steps = [
        router_call("direct"),
        synthesis_call(
            answer="RLM is a recursive language model.",
            summary="Explained RLM.",
        ),
    ]
    engine1 = DspyAgentEngine(
        program_factory=lambda: FleetAgent(tool_profiles={"direct": []}, max_iters=3),
        lm=MultiTurnRecordingLM(turn1_steps),  # type: ignore[arg-type]
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

    # Turn 2: follow-up "go in depth" passing continuation history
    recorded_calls.clear()
    turn2_steps = [
        router_call("direct"),
        synthesis_call(
            answer=(
                "RLMs use recursion to decompose complex tasks into smaller prompts."
            ),
            summary="Detailed RLM mechanics.",
        ),
    ]
    engine2 = DspyAgentEngine(
        program_factory=lambda: FleetAgent(tool_profiles={"direct": []}, max_iters=3),
        lm=MultiTurnRecordingLM(turn2_steps),  # type: ignore[arg-type]
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

    # Verify that in Turn 2, the synthesis predictor received prior turn in context
    synthesis_messages = [
        call
        for call in recorded_calls
        if any("evidence_json" in str(m.get("content")) for m in call)
    ]
    assert synthesis_messages, "Synthesizer must have been called"
    last_synth_call = synthesis_messages[-1]
    synth_text = " ".join(str(m.get("content")) for m in last_synth_call)
    assert "can you explain to me what is a rlm" in synth_text
    assert "RLM is a recursive language model." in synth_text
    assert "go in depth" in synth_text
