"""First-class, capability-routed DSPy program for Fleet Agent."""

from __future__ import annotations

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
from app.agent.signature import AgentSignature
from app.agent.tooling import RESERVED_TOOL_NAMES, create_dspy_tool, is_async_tool

logger = logging.getLogger(__name__)


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
        self.router = dspy.Predict(ToolRoutingSignature)
        self.direct_agent = _build_react(
            profiles["direct"], max_iters, "direct", self._approval_policy
        )
        self.research_agent = _build_react(
            profiles["research"], max_iters, "research", self._approval_policy
        )
        self.artifact_agent = _build_react(
            profiles["artifact"], max_iters, "artifact", self._approval_policy
        )
        self.workspace_read_agent = _build_react(
            profiles["workspace_read"],
            max_iters,
            "workspace_read",
            self._approval_policy,
        )
        self.workspace_write_agent = _build_react(
            profiles["workspace_write"],
            max_iters,
            "workspace_write",
            self._approval_policy,
        )
        self.workspace_shell_agent = _build_react(
            profiles["workspace_shell"],
            max_iters,
            "workspace_shell",
            self._approval_policy,
        )
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
        """Run the legacy program or route into the selected ReAct profile."""
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
        result = agent(user_request=user_request, history=history)
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
) -> Any:
    if approval_policy:
        return ApprovalAwareReActV2(
            AgentSignature,
            tools=list(tools),
            max_iters=max_iters,
            profile_name=profile_name,
            approval_policy=approval_policy,
        )
    return dspy.ReActV2(AgentSignature, tools=list(tools), max_iters=max_iters)


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
