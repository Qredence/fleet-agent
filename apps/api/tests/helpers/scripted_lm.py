"""Scripted LM for provider-free engine tests.

Drives ReActV2's native tool-calling loop by returning provider-format
tool_calls blocks; raises step entries in-loop so loop-recovery paths
(e.g. context window) can be exercised.

A step is either:
  list[call]          — {"name": ..., "args": {...}} tool calls for that turn
  dict                — {"calls": [...], "content": "..."} to also set content
                        (needed to reach empty_tool_calls: content parses the
                        next_thought field while tool_calls stays empty)
  Exception           — raised from complete()
"""

import json
from typing import Any, cast

import dspy
from dspy.lm15 import (
    Message,
    Response,
    StreamDeltaEvent,
    StreamEndEvent,
    StreamStartEvent,
    TextDelta,
    TextPart,
    ToolCallPart,
    Usage,
    response_to_events,
)

_SYNTHESIS_SECTION_ORDER = ("answer", "process_summary", "key_decisions", "caveats")


class ScriptedEngine:
    """Deterministic canonical engine, including native stream events."""

    supports_function_calling = True
    supports_response_schema = True
    supports_reasoning = False
    supported_params = {"tools", "tool_choice", "response_format", "temperature"}

    def __init__(self, steps: list[Any]):
        self._steps = iter(steps)

    def complete(self, request):
        step = next(self._steps, [])
        if isinstance(step, Exception):
            raise step
        calls = step.get("calls", []) if isinstance(step, dict) else step
        content = (
            step.get("content", "")
            if isinstance(step, dict)
            else json.dumps({"next_thought": "working"})
        )
        parts = tuple(
            ToolCallPart(id=f"call_{i}", name=c["name"], input=c["args"])
            for i, c in enumerate(calls)
        )
        return Response(
            id="scripted",
            model="scripted",
            message=Message(role="assistant", parts=(TextPart(content), *parts)),
            finish_reason="tool_call" if calls else "stop",
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

    def stream(self, request):
        return response_to_events(self.complete(request))

    def close(self):
        pass


class StreamingScriptedEngine(ScriptedEngine):
    def stream(self, request):
        response = self.complete(request)
        yield StreamStartEvent(id=response.id, model=response.model)
        for event in response_to_events(response):
            if isinstance(event, StreamDeltaEvent) and isinstance(
                event.delta, TextDelta
            ):
                text = event.delta.text
                for i in range(0, len(text), 5):
                    yield StreamDeltaEvent(
                        TextDelta(text[i : i + 5], part_index=event.delta.part_index)
                    )
            elif isinstance(event, StreamDeltaEvent):
                yield event
        yield StreamEndEvent(finish_reason=response.finish_reason, usage=response.usage)

    def close(self):
        pass


class ScriptedLM(dspy.LM):
    def __init__(self, steps: list[Any], *, engine_type=ScriptedEngine):
        super().__init__("scripted", engine=engine_type(steps), cache=False)


class StreamingScriptedLM(ScriptedLM):
    """DSPy selects native streaming when listeners exist."""

    def __init__(self, steps: list[Any]):
        super().__init__(steps, engine_type=StreamingScriptedEngine)


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


def evidence_end() -> dict[str, Any]:
    """A step that ends an evidence-gathering ReActV2 loop.

    ``EvidenceSignature`` declares no output fields, so the model ends the loop by
    calling ``submit`` with no arguments - a real DSPy terminal condition. Ending
    with an empty tool-call list instead makes vanilla ``dspy.ReActV2`` spend one
    extra LM call on a forced submit, which no scripted sequence here accounts for.
    """
    return {"calls": [{"name": "submit", "args": {}}], "content": ""}


def fixed_route_agent(route: str, **kwargs: Any) -> Any:
    """A ``FleetAgent`` whose route is pinned, so tests spend no LM step on routing.

    Tests that pin gated-tool, persistence, or streaming behavior are not about
    routing. The route is pinned by subclassing ``_select_route`` rather than by
    keeping a router-injection hole on ``FleetAgent`` — the production class stays
    free of test-only knobs.
    """
    from app.agent.program import FleetAgent
    from app.agent.routing import ToolRoute

    pinned = cast("ToolRoute", route)

    class _FixedRouteAgent(FleetAgent):
        def _select_route(self, user_request: str) -> ToolRoute:
            del user_request
            return pinned

    return _FixedRouteAgent(**kwargs)
