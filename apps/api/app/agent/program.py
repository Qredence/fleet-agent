"""First-class DSPy program for Fleet Agent.

The application engine owns runtime concerns (LM selection, callbacks, cleanup,
and public result mapping). ``FleetAgent`` owns the DSPy program tree. Keeping
that boundary explicit makes the agent inspectable, testable, state-saveable,
and visible to DSPy optimizers without exposing ReActV2 internals to FastAPI.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import dspy

from app.agent.signature import AgentSignature
from app.agent.tooling import RESERVED_TOOL_NAMES, create_dspy_tool, is_async_tool


class FleetAgent(dspy.Module):  # type: ignore[misc]  # DSPy is untyped
    """Fleet Agent's DSPy program.

    DSPy 3.3.1's experimental ``ReActV2`` supplies native tool-calling history,
    structured ``dspy.ToolCalls``, and typed final submission. This module keeps
    that experimental dependency behind one stable application-owned class.

    Tools must be explicit ``dspy.Tool`` objects. The registry is responsible
    for creating them from trusted, typed Python callables. ReActV2 then chooses
    whether and when each registered tool is needed.
    """

    def __init__(
        self,
        *,
        tools: Sequence[dspy.Tool],
        max_iters: int = 20,
    ) -> None:
        super().__init__()
        if max_iters < 1:
            raise ValueError("max_iters must be at least 1")

        validated = _validate_tools(tools)
        self.max_iters = max_iters
        self.tool_names = tuple(str(tool.name) for tool in validated)

        # Assignment makes the sub-module visible to DSPy's module tree,
        # named_predictors(), state save/load, and optimizers.
        self.react = dspy.ReActV2(
            AgentSignature,
            tools=list(validated),
            max_iters=max_iters,
        )

    def forward(
        self,
        *,
        user_request: str,
        history: dspy.History | dict[str, Any] | None = None,
    ) -> dspy.Prediction:
        """Run the agent for one user turn and optional serialized history."""
        if not user_request.strip():
            raise ValueError("user_request must not be empty")
        return self.react(user_request=user_request, history=history)

    @property
    def tools(self) -> tuple[dspy.Tool, ...]:
        """Return user tools through an application-owned read-only view."""
        return tuple(self.react.tools[name] for name in self.tool_names)

    def get_tool(self, name: str) -> dspy.Tool:
        """Return one registered user tool without exposing ReActV2 internals."""
        if name not in self.tool_names:
            raise KeyError(f"unknown tool: {name}")
        return self.react.tools[name]


def _validate_tools(tools: Sequence[dspy.Tool]) -> list[dspy.Tool]:
    validated: list[dspy.Tool] = []
    seen: set[str] = set()

    for tool in tools:
        if not isinstance(tool, dspy.Tool):
            raise TypeError(
                "FleetAgent requires explicit dspy.Tool objects; "
                "create them through ToolRegistry or create_dspy_tool()."
            )

        # Reuse the application-owned Tool validation without rewrapping a
        # prebuilt Tool. This keeps direct FleetAgent construction as strict as
        # ToolRegistry-backed construction.
        tool = create_dspy_tool(tool)
        name = str(tool.name or "")
        if not name:
            raise ValueError("every tool must have a non-empty name")
        if name in RESERVED_TOOL_NAMES:
            raise ValueError(f"tool name {name!r} is reserved by ReActV2")
        if name in seen:
            raise ValueError(f"duplicate tool: {name}")

        description = str(tool.desc or "").strip()
        if not description:
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
