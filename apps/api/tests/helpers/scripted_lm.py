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

# The synthesis predictor runs under ChatAdapter (exact stream boundaries),
# so a scripted synthesis step must answer in ChatAdapter sections.
_SYNTHESIS_SECTION_ORDER = (
    "answer",
    "process_summary",
    "key_decisions",
    "caveats",
)


class ScriptedLM(DummyLM):
    def __init__(self, steps: list[Any]):
        super().__init__([{"answer": "unused"}])
        self._steps = iter(steps)

    def forward(self, prompt=None, messages=None, **kwargs):  # noqa: ANN001, ANN201
        calls, content = self._next_step()
        return _scripted_completion(calls, content)

    def _next_step(self) -> tuple[list[Any], str]:
        """Advance to the next step, returning (tool_calls, content)."""
        step = next(self._steps, [])
        if isinstance(step, Exception):
            raise step
        if isinstance(step, dict):
            return step.get("calls", []), step.get("content", "")
        return step, json.dumps({"next_thought": "working"})


class StreamingScriptedLM(ScriptedLM):
    """ScriptedLM that honors dspy's send_stream with litellm-shaped chunks.

    When the caller's predict is a stream-listener target (dspy sets
    ``settings.send_stream``), the scripted content is chunked into
    ``ModelResponseStream`` deltas carrying the caller's predict_id — the same
    contract dspy's litellm path produces — so StreamListener boundaries fire
    exactly as they would against a live streaming gateway.
    """

    _CHUNK_CHARS = 5

    def forward(self, prompt=None, messages=None, **kwargs):  # noqa: ANN001, ANN201
        from dspy.dsp.utils.settings import settings as dspy_settings
        from dspy.streaming.messages import sync_send_to_stream
        from litellm import ModelResponseStream
        from litellm.types.utils import Delta, StreamingChoices

        calls, content = self._next_step()

        stream = dspy_settings.send_stream
        caller_predict_id = (
            id(dspy_settings.caller_predict) if dspy_settings.caller_predict else None
        )
        if stream is not None:
            for i in range(0, len(content), self._CHUNK_CHARS):
                chunk = ModelResponseStream(
                    id="chatcmpl-scripted",
                    object="chat.completion.chunk",
                    created=0,
                    model="scripted",
                    choices=[
                        StreamingChoices(
                            index=0,
                            delta=Delta(
                                role="assistant",
                                content=content[i : i + self._CHUNK_CHARS],
                            ),
                            finish_reason=None,
                        )
                    ],
                )
                if caller_predict_id:
                    chunk.predict_id = caller_predict_id
                sync_send_to_stream(stream, chunk)

        return _scripted_completion(calls, content)


def _scripted_completion(calls: list[Any], content: str) -> dotdict:
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


def synthesis_call(
    answer: str | None = "Done.",
    summary: str = "Routed, gathered evidence, synthesized.",
    decisions: list[str] | None = None,
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    """A ChatAdapter-formatted synthesis step for the routed program.

    The routed program ends with a synthesis Predict under ChatAdapter; its
    response is plain sectioned text, not a tool call.
    """
    values = {
        "answer": answer or "",
        "process_summary": summary,
        "key_decisions": json.dumps(decisions or ["kept scope tight"]),
        "caveats": json.dumps(caveats or []),
    }
    sections = [
        f"[[ ## {name} ## ]]\n{values[name]}" for name in _SYNTHESIS_SECTION_ORDER
    ]
    sections.append("[[ ## completed ## ]]")
    return {"calls": [], "content": "\n\n".join(sections)}


def router_call(route: str) -> dict[str, Any]:
    """A router step selecting one capability route."""
    return {"calls": [], "content": json.dumps({"route": route})}
