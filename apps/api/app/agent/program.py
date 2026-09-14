"""First-class, capability-routed DSPy program for Fleet Agent."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import dspy
from dspy.utils.exceptions import AdapterParseError

from app.agent.approval import (
    ApprovalAwareReActV2,
    ToolLifecycle,
    current_approval_context,
)
from app.agent.evidence import DEFAULT_MAX_CHARS, bounded_json
from app.agent.routing import ROUTES, ToolRoute, ToolRoutingSignature, coerce_route
from app.agent.signature import EvidenceSignature, SynthesisSignature
from app.agent.tooling import RESERVED_TOOL_NAMES, create_dspy_tool, is_async_tool

logger = logging.getLogger(__name__)

# Streaming contract: the synthesis predictor's public text fields.  The
# engine streams exactly these fields with dspy.streamify listeners.
SYNTHESIS_STREAM_FIELDS = ("answer", "process_summary")
_MAX_EVIDENCE_CHARS = DEFAULT_MAX_CHARS


class FleetAgent(dspy.Module):  # type: ignore[misc]  # DSPy is untyped
    """Route each request into a least-privileged evidence-gathering profile.

    ``tool_profiles`` is the capability lattice: one entry per route holding
    exactly the ``dspy.Tool`` objects that route may call. The program builds
    one ``ApprovalAwareReActV2`` per route, so a run can never reach a tool
    outside the profile the router selected.

    Those agents gather evidence only. The ``synthesizer`` writes the public
    fields from that evidence, and that split is what makes DSPy-native
    streaming possible: ``answer`` and ``process_summary`` are predictor
    output fields, so ``dspy.streamify`` can stream them, which is not true
    of values carried inside a ``submit`` tool call.
    """

    def __init__(
        self,
        *,
        tool_profiles: Mapping[ToolRoute, Sequence[dspy.Tool]],
        max_iters: int = 20,
        approval_policy: Mapping[str, Any] | None = None,
        lifecycle: ToolLifecycle | None = None,
        router: dspy.Module | None = None,
    ) -> None:
        super().__init__()
        if max_iters < 1:
            raise ValueError("max_iters must be at least 1")
        self.application_tool_lifecycle = lifecycle is not None
        # The router slot accepts the promoted Flex program (loaded from a
        # GEPA-optimized state); the default stays the plain Predict over the
        # routing signature. Either way the output is coerced downstream.
        self.router = (
            router if router is not None else dspy.Predict(ToolRoutingSignature)
        )
        policy = dict(approval_policy or {})
        profiles = {
            route: _validate_tools(tool_profiles.get(route, ())) for route in ROUTES
        }
        self.tool_names = {
            route: tuple(str(tool.name) for tool in tools)
            for route, tools in profiles.items()
        }
        self.evidence_agents = {
            route: ApprovalAwareReActV2(
                EvidenceSignature,
                tools=tools,
                max_iters=max_iters,
                profile_name=route,
                approval_policy=policy,
                evidence_only=True,
            )
            for route, tools in profiles.items()
        }
        self.synthesizer = dspy.Predict(SynthesisSignature)
        self.synthesis_stream_fields = SYNTHESIS_STREAM_FIELDS

    def forward(
        self,
        *,
        user_request: str,
        history: dspy.History | dict[str, Any] | None = None,
    ) -> dspy.Prediction:
        """Gather evidence in the selected profile, then write public fields."""
        if not user_request.strip():
            raise ValueError("user_request must not be empty")
        route = self._select_route(user_request)
        evidence = self.evidence_agents[route](
            user_request=user_request, history=history
        )
        evidence_history = getattr(evidence, "history", None)
        synthesis = self._synthesize(
            user_request=user_request, history=evidence_history
        )
        result = dspy.Prediction(
            answer=getattr(synthesis, "answer", None),
            process_summary=getattr(synthesis, "process_summary", None),
            key_decisions=list(getattr(synthesis, "key_decisions", None) or []),
            caveats=list(getattr(synthesis, "caveats", None) or []),
            history=evidence_history,
            termination_reason="synthesis",
        )
        # Diagnostic metadata stays on the server-side Prediction and is not
        # included in AgentRunResult or any AG-UI event.
        result.agent_route = route
        logger.info(
            "agent routed",
            extra={"route": route, "tool_names": list(self.tool_names[route])},
        )
        return result

    def _select_route(self, user_request: str) -> ToolRoute:
        """Pick the least-privileged profile, or the resumed run's profile.

        A paused run already belongs to a profile: re-routing it would let a
        second router call widen the capability the approver saw, so the
        checkpoint's profile wins.
        """
        context = current_approval_context()
        resumed_route = (
            context.resumed.checkpoint.profile_name
            if context is not None and context.resumed is not None
            else None
        )
        if resumed_route in ROUTES:
            return resumed_route
        try:
            routing = self.router(user_request=user_request)
        except AdapterParseError:
            # A router answer outside the route vocabulary degrades to the
            # least-privileged profile instead of failing the run.
            return "direct"
        return coerce_route(getattr(routing, "route", None))

    def _synthesize(
        self,
        *,
        user_request: str,
        history: dspy.History | None,
    ) -> dspy.Prediction:
        """Write the public fields from the evidence the loop gathered.

        The synthesis call runs under ChatAdapter: its section markers give
        StreamListener exact, boilerplate-free field boundaries, while the
        evidence loop keeps the caller-configured JSONAdapter for tool
        calling.  This local adapter scope is invisible to the stream
        consumer task, so the engine's listeners pin the same adapter when
        parsing chunks.
        """
        with dspy.context(adapter=dspy.ChatAdapter()):
            return self.synthesizer(
                user_request=user_request,
                evidence_json=_evidence_json(history),
            )


def _evidence_json(
    history: dspy.History | None, *, max_chars: int = _MAX_EVIDENCE_CHARS
) -> str:
    """Render bounded, user-safe evidence from the loop's tool observations.

    History events appear in two shapes: live in-process events carry
    ``ToolCalls``/``ToolCallResult`` pydantic objects, while histories restored
    from persistence carry plain dicts with the same keys. Only tool names
    and their (already-instrumented, bounded) results are exposed to the
    synthesizer; ``next_thought`` reasoning stays out.

    The result is always parseable JSON: the synthesizer's ``evidence_json``
    input is a document, so an over-budget payload drops whole entries from
    the end rather than slicing the serialized text (see
    ``app.agent.evidence``).
    """
    if history is None:
        return "[]"
    items: list[dict[str, Any]] = []
    for message in getattr(history, "messages", None) or []:
        for name, value, is_error in _message_tool_results(message):
            items.append(
                {
                    "tool": name,
                    "result": value
                    if isinstance(value, (str, int, float, bool))
                    else json.dumps(value, default=str),
                    "is_error": is_error,
                }
            )
    return bounded_json(items, max_chars=max_chars)


def _message_tool_results(message: Any) -> list[tuple[Any, Any, bool]]:
    """Extract ``(name, value, is_error)`` triples from one history event.

    Accepts both the pydantic event objects a live loop appends and the plain
    dict form a JSON round-trip produces; anything without tool results
    (user turns, evidence breaks) yields nothing.
    """
    if isinstance(message, dict):
        calls = message.get("tool_calls")
    else:
        calls = getattr(message, "tool_calls", None)
    if calls is None:
        return []
    if isinstance(calls, dict):
        container = calls.get("tool_call_results")
    else:
        container = getattr(calls, "tool_call_results", None)
    results: list[tuple[Any, Any, bool]] = []
    for item in _tool_result_entries(container):
        if isinstance(item, dict):
            results.append(
                (item.get("name"), item.get("value"), bool(item.get("is_error", False)))
            )
            continue
        results.append(
            (
                getattr(item, "name", None),
                getattr(item, "value", None),
                bool(getattr(item, "is_error", False)),
            )
        )
    return results


def _tool_result_entries(container: Any) -> list[Any]:
    """Normalize a ``tool_call_results`` carrier to its list of entries.

    The live event stores a ``ToolCallResults`` pydantic model (iterating one
    yields ``("tool_call_results", [...])`` field pairs, not entries), a
    persisted round-trip stores ``{"tool_call_results": [...]}``, and some
    paths already carry the bare list. All three must reach the synthesizer.
    """
    if container is None:
        return []
    if isinstance(container, list):
        return container
    if isinstance(container, dict):
        return _tool_result_entries(container.get("tool_call_results"))
    return _tool_result_entries(getattr(container, "tool_call_results", None))


def _validate_tools(tools: Sequence[dspy.Tool]) -> list[dspy.Tool]:
    validated: list[dspy.Tool] = []
    seen: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dspy.Tool):
            raise TypeError(
                "FleetAgent profiles require explicit dspy.Tool objects; "
                "create them through ToolRegistry or create_dspy_tool()."
            )
        tool = create_dspy_tool(tool)
        name = str(tool.name or "")
        if not name:
            raise ValueError("every tool must have a non-empty name")
        if name in RESERVED_TOOL_NAMES:
            raise ValueError(f"tool name {name!r} is reserved by ReActV2")
        if name in seen:
            raise ValueError(f"duplicate tool: {name}")
        if not str(tool.desc or "").strip():
            raise ValueError(f"tool {name!r} must have a description or docstring")
        if is_async_tool(tool):
            raise TypeError(
                f"tool {name!r} is async, but DSPy 3.3.1 ReActV2 executes "
                "tools synchronously. Use a synchronous adapter or a future "
                "async agent program instead of enabling implicit sync conversion."
            )
        seen.add(name)
        validated.append(tool)
    return validated
