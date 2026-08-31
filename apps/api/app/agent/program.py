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
from app.agent.routing import ROUTES, ToolRoute, ToolRoutingSignature, coerce_route
from app.agent.signature import (
    AgentSignature,
    EvidenceSignature,
    SynthesisSignature,
)
from app.agent.tooling import RESERVED_TOOL_NAMES, create_dspy_tool, is_async_tool

logger = logging.getLogger(__name__)

# Streaming contract: the synthesis predictor's public text fields.  The
# engine streams exactly these fields with dspy.streamify listeners.
SYNTHESIS_STREAM_FIELDS = ("answer", "process_summary")
_MAX_EVIDENCE_CHARS = 8000


class FleetAgent(dspy.Module):  # type: ignore[misc]  # DSPy is untyped
    """Route each request into a least-privileged persistent ReActV2 profile.

    ``tool_profiles`` is the production interface. The legacy ``tools``
    argument remains supported for small callers and tests that intentionally
    construct one un-routed ReAct program.
    """

    def __init__(
        self,
        *,
        tool_profiles: Mapping[ToolRoute, Sequence[dspy.Tool]] | None = None,
        tools: Sequence[dspy.Tool] | None = None,
        max_iters: int = 20,
        approval_policy: Mapping[str, Any] | None = None,
        lifecycle: ToolLifecycle | None = None,
        router: dspy.Module | None = None,
    ) -> None:
        super().__init__()
        if max_iters < 1:
            raise ValueError("max_iters must be at least 1")
        if tool_profiles is not None and tools is not None:
            raise ValueError("provide tool_profiles or tools, not both")

        self.max_iters = max_iters
        self._approval_policy = dict(approval_policy or {})
        self.application_tool_lifecycle = lifecycle is not None
        if tool_profiles is None:
            self._init_legacy(tools or (), max_iters)
            return

        profiles = {
            route: _validate_tools(tool_profiles.get(route, ())) for route in ROUTES
        }
        # The router slot accepts the promoted Flex program (loaded from a
        # GEPA-optimized state); the default stays the plain Predict over the
        # routing signature. Either way the output is coerced downstream.
        self.router = (
            router if router is not None else dspy.Predict(ToolRoutingSignature)
        )
        self.direct_agent = _build_react(
            profiles["direct"],
            max_iters,
            "direct",
            self._approval_policy,
            evidence_only=True,
        )
        self.research_agent = _build_react(
            profiles["research"],
            max_iters,
            "research",
            self._approval_policy,
            evidence_only=True,
        )
        self.artifact_agent = _build_react(
            profiles["artifact"],
            max_iters,
            "artifact",
            self._approval_policy,
            evidence_only=True,
        )
        self.workspace_read_agent = _build_react(
            profiles["workspace_read"],
            max_iters,
            "workspace_read",
            self._approval_policy,
            evidence_only=True,
        )
        self.workspace_write_agent = _build_react(
            profiles["workspace_write"],
            max_iters,
            "workspace_write",
            self._approval_policy,
            evidence_only=True,
        )
        self.workspace_shell_agent = _build_react(
            profiles["workspace_shell"],
            max_iters,
            "workspace_shell",
            self._approval_policy,
            evidence_only=True,
        )
        # The synthesis predictor writes the public fields from the gathered
        # evidence; its answer/process_summary outputs are the fields the
        # engine streams with dspy.streamify + StreamListener.
        self.synthesizer = dspy.Predict(SynthesisSignature)
        self.synthesis_stream_fields = SYNTHESIS_STREAM_FIELDS
        self.tool_profiles = {
            route: tuple(str(tool.name) for tool in profile)
            for route, profile in profiles.items()
        }
        self._profile_tools = {
            route: tuple(profile) for route, profile in profiles.items()
        }
        self.tool_names = tuple(tool.name for tool in self.tools)

    def _init_legacy(self, tools: Sequence[dspy.Tool], max_iters: int) -> None:
        validated = _validate_tools(tools)
        self._legacy_react = _build_react(
            validated,
            max_iters,
            "legacy",
            self._approval_policy,
        )
        self.tool_names = tuple(str(tool.name) for tool in validated)

    def forward(
        self,
        *,
        user_request: str,
        history: dspy.History | dict[str, Any] | None = None,
    ) -> dspy.Prediction:
        """Run the legacy program or route into evidence gathering + synthesis."""
        if not user_request.strip():
            raise ValueError("user_request must not be empty")
        if hasattr(self, "_legacy_react"):
            return self._legacy_react(user_request=user_request, history=history)

        context = current_approval_context()
        resumed_route = (
            context.resumed.checkpoint.profile_name
            if context is not None and context.resumed is not None
            else None
        )
        if resumed_route in ROUTES:
            route = resumed_route
        else:
            try:
                routing = self.router(user_request=user_request)
                route = coerce_route(getattr(routing, "route", None))
            except AdapterParseError:
                # A router answer outside the route vocabulary degrades to
                # the least-privileged profile instead of failing the run.
                route = "direct"
        agent = {
            "direct": self.direct_agent,
            "research": self.research_agent,
            "artifact": self.artifact_agent,
            "workspace_read": self.workspace_read_agent,
            "workspace_write": self.workspace_write_agent,
            "workspace_shell": self.workspace_shell_agent,
        }[route]
        evidence = agent(user_request=user_request, history=history)
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
        selected_tools = self._profile_tools[route]
        logger.info(
            "agent routed",
            extra={
                "route": route,
                "tool_count": len(selected_tools),
                "tool_names": [str(tool.name) for tool in selected_tools],
            },
        )
        return result

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
        evidence_json = _evidence_json(history)
        with dspy.context(adapter=dspy.ChatAdapter()):
            return self.synthesizer(
                user_request=user_request,
                evidence_json=evidence_json,
                critique="",
            )

    @property
    def react(self) -> Any:
        """Backward-compatible access to the single legacy ReAct module."""
        if not hasattr(self, "_legacy_react"):
            raise AttributeError("routed FleetAgent has named profile agents")
        return self._legacy_react

    @property
    def tools(self) -> tuple[dspy.Tool, ...]:
        """Return the user tools visible across the configured profiles."""
        if hasattr(self, "_legacy_react"):
            return tuple(self._legacy_react.tools[name] for name in self.tool_names)
        seen: set[str] = set()
        result: list[dspy.Tool] = []
        for profile in ROUTES:
            for tool in self._profile_tools[profile]:
                if tool.name not in seen:
                    seen.add(tool.name)
                    result.append(tool)
        return tuple(result)

    def get_tool(self, name: str) -> dspy.Tool:
        """Return one registered user tool without exposing ReAct internals."""
        for tool in self.tools:
            if tool.name == name:
                return tool
        raise KeyError(f"unknown tool: {name}")


def _build_react(
    tools: Sequence[dspy.Tool],
    max_iters: int,
    profile_name: str,
    approval_policy: Mapping[str, Any],
    *,
    evidence_only: bool = False,
) -> Any:
    # The routed program always uses the application-owned loop: the
    # evidence ending (no forced submit) exists only there.
    if approval_policy or evidence_only:
        return ApprovalAwareReActV2(
            EvidenceSignature if evidence_only else AgentSignature,
            tools=list(tools),
            max_iters=max_iters,
            profile_name=profile_name,
            approval_policy=approval_policy,
            evidence_only=evidence_only,
        )
    return dspy.ReActV2(AgentSignature, tools=list(tools), max_iters=max_iters)


def _evidence_json(
    history: dspy.History | None, *, max_chars: int = _MAX_EVIDENCE_CHARS
) -> str:
    """Render bounded, user-safe evidence from the loop's tool observations.

    History events appear in two shapes: live in-process events carry
    ``ToolCalls``/``ToolCallResult`` pydantic objects, while histories restored
    from persistence carry plain dicts with the same keys. Only tool names
    and their (already-instrumented, bounded) results are exposed to the
    synthesizer; ``next_thought`` reasoning stays out.
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
    text = json.dumps(items, ensure_ascii=False)
    if len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


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
