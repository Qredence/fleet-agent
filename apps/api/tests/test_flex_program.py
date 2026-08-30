import dspy
import pytest

from app.agent.flex_program import (
    FlexFleetAgent,
    ensure_deno_runtime,
    sanitize_flex_history,
)
from app.agent.tooling import create_dspy_tool


def test_flex_history_projection_drops_private_react_fields():
    history = dspy.History(
        messages=[
            {"user_request": "Find the class.", "next_thought": "private"},
            {
                "user_request": "Find the class.",
                "tool_calls": {"tool_calls": [{"name": "grep"}]},
                "answer": "The class is in program.py.",
            },
            {"role": "user", "content": "Follow up."},
        ]
    )

    projected = sanitize_flex_history(history)

    assert projected.messages == [
        {"role": "user", "content": "Find the class."},
        {"role": "user", "content": "Find the class."},
        {"role": "assistant", "content": "The class is in program.py."},
        {"role": "user", "content": "Follow up."},
    ]
    assert "next_thought" not in str(projected.messages)
    assert "tool_calls" not in str(projected.messages)


def test_flex_candidate_is_a_dspy_module_with_explicit_tools():
    def lookup(query: str) -> str:
        """Look up a deterministic value."""
        return query

    tool = create_dspy_tool(lookup)
    program = FlexFleetAgent(tools=[tool], max_predictor_calls=3)

    assert isinstance(program, dspy.Module)
    assert program.tool_names == ("lookup",)
    assert program.flex is not None


def test_ensure_deno_runtime_fails_closed_without_deno(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(RuntimeError, match="Deno"):
        ensure_deno_runtime()


def test_ensure_deno_runtime_accepts_deno_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/deno")

    ensure_deno_runtime()
