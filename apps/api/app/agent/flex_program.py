"""Opt-in DSPy Flex candidate with a sanitized conversation boundary."""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from typing import Any

import dspy

from app.agent.tooling import create_dspy_tool, is_async_tool


def ensure_deno_runtime() -> None:
    """Fail fast when the Flex sandbox runtime is unavailable.

    ``dspy.Flex`` executes its predictors inside a Deno/Pyodide sandbox and
    requires a ``deno`` binary (>= 2.0.0, < 3.0.0) on the host PATH. Probing
    at engine-build time turns an opaque per-run interpreter failure into a
    clear configuration error.
    """
    if shutil.which("deno") is None:
        raise RuntimeError(
            "reasoning_program=flex requires a Deno runtime "
            "(>= 2.0.0, < 3.0.0) on PATH for dspy.Flex's sandboxed interpreter"
        )


class FlexAgentSignature(dspy.Signature):  # type: ignore[misc]
    """Resolve a request using only public conversation history and tools."""

    history: dspy.History = dspy.InputField(
        desc=(
            "Prior user requests and final assistant responses only. "
            "It contains no hidden reasoning, tool observations, or provider data."
        )
    )
    user_request: str = dspy.InputField(desc="The user's current request.")
    answer: str = dspy.OutputField(desc="Direct final answer to the user.")
    process_summary: str = dspy.OutputField(
        desc="Concise user-facing summary of the approach taken."
    )
    key_decisions: list[str] = dspy.OutputField(desc="Important decisions made.")
    caveats: list[str] = dspy.OutputField(
        desc="Remaining uncertainty, limitations, or risks."
    )


class FlexFleetAgent(dspy.Module):  # type: ignore[misc]
    """Experimental Flex program; production defaults to routed ReActV2."""

    def __init__(
        self,
        *,
        tools: Sequence[dspy.Tool],
        max_predictor_calls: int = 12,
    ) -> None:
        super().__init__()
        if max_predictor_calls < 1:
            raise ValueError("max_predictor_calls must be at least 1")
        validated = _validate_tools(tools)
        self.tool_names = tuple(str(tool.name) for tool in validated)
        self.flex = dspy.Flex(
            FlexAgentSignature,
            tools=list(validated),
            max_predictor_calls=max_predictor_calls,
        )

    def forward(
        self,
        *,
        user_request: str,
        history: dspy.History | Mapping[str, Any] | None = None,
    ) -> dspy.Prediction:
        """Run Flex with a public-only projection of prior conversation state."""
        if not user_request.strip():
            raise ValueError("user_request must not be empty")
        return self.flex(
            history=sanitize_flex_history(history),
            user_request=user_request,
        )


def sanitize_flex_history(history: object) -> dspy.History:
    """Keep only user text and final assistant text from an arbitrary history.

    ReActV2 histories contain private fields such as ``next_thought``, tool
    calls, and observations. This projection copies known public fields into a
    fresh ``dspy.History`` and drops everything else.
    """
    raw_messages: object
    if isinstance(history, dspy.History):
        raw_messages = history.messages
    elif isinstance(history, Mapping):
        raw_messages = history.get("messages", [])
    else:
        raw_messages = []

    if not isinstance(raw_messages, list):
        return dspy.History(messages=[])

    public: list[dict[str, str]] = []
    for message in raw_messages:
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            public.append({"role": str(role), "content": content})
            continue

        user_request = message.get("user_request")
        if isinstance(user_request, str) and user_request.strip():
            public.append({"role": "user", "content": user_request})
        answer = message.get("answer")
        if isinstance(answer, str) and answer.strip():
            public.append({"role": "assistant", "content": answer})

    return dspy.History(messages=public)


def _validate_tools(tools: Sequence[dspy.Tool]) -> list[dspy.Tool]:
    validated: list[dspy.Tool] = []
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dspy.Tool):
            raise TypeError("FlexFleetAgent requires explicit dspy.Tool objects")
        checked = create_dspy_tool(tool)
        name = str(checked.name)
        if name in names:
            raise ValueError(f"duplicate tool: {name}")
        if is_async_tool(checked):
            raise TypeError("FlexFleetAgent does not accept async tools")
        names.add(name)
        validated.append(checked)
    return validated
