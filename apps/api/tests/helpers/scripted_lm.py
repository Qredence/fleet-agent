"""Scripted LM for provider-free engine tests.

Drives ``dspy.ReAct``'s native tool-calling loop by returning provider-format
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
from collections.abc import Callable
from typing import Any, cast

import dspy
from dspy.lm15 import (
    Message,
    Request,
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


def message_text(message: Message) -> str:
    """Flatten one message's text parts; the rendered field values live here."""
    return "\n\n".join(
        part.text for part in message.parts if isinstance(part, TextPart)
    )


def request_text(prompt: Request | str | None) -> str:
    """Render a DSPy 3.5 ``Request`` as the plain text the model reads.

    ``BaseLM.__call__`` takes a native ``Request`` (or a bare string): the
    instructions live on ``request.system`` and each message carries typed
    parts. Tests that inspect what reached the model flatten it here instead of
    each reimplementing the part walk. The 3.4 OpenAI-dict ``messages=`` form is
    gone, so there is no second shape to support.
    """
    if isinstance(prompt, str):
        return prompt
    if prompt is None:
        return ""

    texts: list[str] = []
    system = prompt.system
    if isinstance(system, str):
        texts.append(system)
    elif system:
        texts.extend(part.text for part in system if isinstance(part, TextPart))
    texts.extend(message_text(message) for message in prompt.messages)
    return "\n\n".join(texts)


class RecordingScriptedLM(ScriptedLM):
    """A ``ScriptedLM`` that records every request and can act per response.

    ``requests`` holds the flattened text of each model call (instructions plus
    messages); ``messages`` holds each individual message's text, which is where
    a predictor's *rendered* fields live (the instructions only carry the
    field template). ``after_response`` runs once per model call, after the
    scripted response is produced: the seam cancellation tests use to trip a
    cancel token between turns without overriding ``__call__`` themselves.
    """

    def __init__(
        self,
        steps: list[Any],
        *,
        after_response: Callable[[], None] | None = None,
    ):
        super().__init__(steps)
        self.requests: list[str] = []
        self.messages: list[str] = []
        self._after_response = after_response

    def __call__(self, prompt: Request | str | None = None, **options: Any) -> Any:
        self.requests.append(request_text(prompt))
        if isinstance(prompt, Request):
            self.messages.extend(message_text(message) for message in prompt.messages)
        response = super().__call__(prompt, **options)
        if self._after_response is not None:
            self._after_response()
        return response

    def requests_mentioning(self, needle: str) -> list[str]:
        """Rendered requests containing ``needle``, oldest first."""
        return [text for text in self.requests if needle in text]

    def messages_mentioning(self, needle: str) -> list[str]:
        """Rendered messages containing ``needle``, oldest first."""
        return [text for text in self.messages if needle in text]


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
    return {
        "calls": [],
        "content": json.dumps({"route": route, "output_intent": "none"}),
    }


def evidence_end() -> dict[str, Any]:
    """A step that ends an evidence-gathering ``dspy.ReAct`` loop.

    ``EvidenceSignature`` declares no output fields, so the model ends the loop by
    calling ``submit`` with no arguments - a real DSPy terminal condition. Ending
    with an empty tool-call list instead makes vanilla ``dspy.ReAct`` spend one
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
