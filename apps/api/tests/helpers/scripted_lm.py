"""Scripted LM for provider-free engine tests.

Drives ReActV2's native tool-calling loop by returning provider-format
tool_calls blocks; raises step entries in-loop so loop-recovery paths
(e.g. context window) can be exercised.

A step is either:
  list[call]          — {"name": ..., "args": {...}} tool calls for that turn
  dict                — {"calls": [...], "content": "..."} to also set content
                        (needed to reach empty_tool_calls: content parses the
                        next_thought field while tool_calls stays empty)
  Exception           — raised from forward()
"""

import json
from typing import Any

from dspy.utils.dummies import DummyLM, dotdict


class ScriptedLM(DummyLM):
    def __init__(self, steps: list[Any]):
        super().__init__([{"answer": "unused"}])
        self._steps = iter(steps)

    def forward(self, prompt=None, messages=None, **kwargs):  # noqa: ANN001, ANN201
        step = next(self._steps, [])
        if isinstance(step, Exception):
            raise step

        if isinstance(step, dict):
            calls = step.get("calls", [])
            content = step.get("content", "")
        else:
            calls = step
            content = json.dumps({"next_thought": "working"})

        tool_calls = [
            dotdict(
                id=f"call_{i}",
                type="function",
                function=dotdict(name=call["name"], arguments=json.dumps(call["args"])),
            )
            for i, call in enumerate(calls)
        ]
        message = dotdict(content=content, tool_calls=tool_calls or None)
        return dotdict(
            choices=[dotdict(message=message, finish_reason="tool_calls")],
            usage=dotdict(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="scripted",
        )


def submit_call(
    answer: str | None = "Done.",
    summary: str = "Looked things up.",
    decisions: list[str] | None = None,
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    """A submit tool call with every AgentSignature output field."""
    return {
        "name": "submit",
        "args": {
            "answer": answer,
            "process_summary": summary,
            "key_decisions": decisions or ["kept scope tight"],
            "caveats": caveats or [],
        },
    }
