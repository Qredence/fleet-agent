from __future__ import annotations

import dspy

from app.agent.engine import (
    AgentRunContext,
    DspyAgentEngine,
)
from app.agent.program import FleetAgent
from app.agent.tooling import create_dspy_tool
from tests.helpers.scripted_lm import ScriptedLM, submit_call

CTX = AgentRunContext(thread_id="thread-1", run_id="run-1")


class StaticProgram(dspy.Module):  # type: ignore[misc]
    def forward(
        self,
        *,
        user_request: str,
        history: dspy.History | None = None,
    ) -> dspy.Prediction:
        """
        Return a completed prediction with a fixed answer and termination reason.
        
        Parameters:
            history (dspy.History | None): Conversation history to preserve in the prediction.
        
        Returns:
            dspy.Prediction: A completed prediction containing the preserved or empty history.
        """
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
        program_factory=lambda: FleetAgent(tools=[tool], max_iters=3),
        lm=ScriptedLM(
            [
                [{"name": "lookup", "args": {"query": "x"}}],
                [submit_call(answer="Used the tool.")],
            ]
        ),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(use_native_function_calling=True),
    )

    result = await engine.run(user_request="look it up", history=None, context=CTX)

    assert result.status == "completed"
    assert result.answer == "Used the tool."
    assert result.termination_reason == "submit"
    assert len(result.history.messages) == 2


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
