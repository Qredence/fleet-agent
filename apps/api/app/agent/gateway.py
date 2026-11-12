"""Run-owned native DSPy configuration for OpenAI-compatible gateways.

DSPy owns request conversion, streaming, retries, errors and usage. This module
declares the wire policy and retains run-local tool continuation data that
DSPy's public ReAct history omits.

A custom engine owns its connection by design: ``dspy.LM(engine=...)`` refuses
``api_key``/``api_base`` and the other client settings, so keys and addresses
live here in ``ProviderConfig``, never on the LM. DSPy documents
``dspy.lm15.register_provider`` as the alternative for OpenAI-compatible HTTP
services, but that registration is process-global while browser provider
overrides are per-request values — so the router stays run-owned.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import dspy
from dspy.clients.engines import LM15Engine
from dspy.lm15 import (
    AccessPolicy,
    OpenAIChatCompat,
    ProviderDefinition,
    Request,
    Response,
    ResponseStream,
    RouterConfig,
    StreamDeltaEvent,
    StreamEndEvent,
    StreamErrorEvent,
    StreamStartEvent,
    ThinkingPart,
    ToolCallPart,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    model: str
    api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    base_url: str | None = None
    native_function_calling: bool = True
    developer_role: bool = False


class GatewayEngine(LM15Engine):  # type: ignore[misc]
    """A private router for one run; never register browser keys globally."""

    supports_response_schema = True
    supports_reasoning = False
    supported_params = frozenset(
        {
            "temperature",
            "max_tokens",
            "max_completion_tokens",
            "top_p",
            "stop",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "response_format",
        }
    )

    def __init__(
        self, config: ProviderConfig, *, headers: tuple[tuple[str, str], ...] = ()
    ) -> None:
        self._resources_closed = False
        self.supports_function_calling = config.native_function_calling
        self._replay_thinking = (
            config.model.lower().rsplit("/", 1)[-1].startswith("deepseek-")
        )
        # DSPy's ReAct history retains tool calls but not provider thinking.
        # Keep that opaque continuation data only in this run-owned engine;
        # never publish it as answer text or persist it in browser history.
        self._tool_thinking: dict[tuple[str, ...], tuple[ThinkingPart, ...]] = {}
        access = AccessPolicy(
            provider="fleet-gateway",
            base_url=config.base_url,
            headers=headers,
        )
        compat = replace(
            OpenAIChatCompat.preset("openai"),
            instruction_role="developer" if config.developer_role else "system",
        )
        if self._replay_thinking:
            compat = replace(
                compat,
                thinking_replay="native",
                assistant_reasoning_content="include_empty",
            )
        definition = ProviderDefinition.chat(access, compat=compat)
        super().__init__(
            RouterConfig(
                env={},
                providers=(definition,),
                api_keys={"fleet-gateway": config.api_key.get_secret_value()}
                if config.api_key
                else {},
            )
        )

    def _restore_thinking(self, request: Request) -> Request:
        if not self._replay_thinking:
            return request
        messages = []
        for message in request.messages:
            ids = tuple(part.id for part in message.parts_of(ToolCallPart))
            thinking = self._tool_thinking.get(ids)
            if (
                message.role == "assistant"
                and thinking
                and not message.parts_of(ThinkingPart)
            ):
                message = replace(message, parts=(*thinking, *message.parts))
            messages.append(message)
        return replace(request, messages=tuple(messages))

    def _remember_thinking(self, response: Response) -> None:
        if not self._replay_thinking:
            return
        ids = tuple(part.id for part in response.message.parts_of(ToolCallPart))
        thinking = tuple(response.message.parts_of(ThinkingPart))
        if ids and thinking:
            self._tool_thinking[ids] = thinking

    def complete(self, request: Request) -> Response:
        restored = self._restore_thinking(request)
        response = super().complete(restored)
        self._remember_thinking(response)
        return response

    def stream(
        self, request: Request
    ) -> Iterator[
        StreamStartEvent | StreamDeltaEvent | StreamEndEvent | StreamErrorEvent
    ]:
        if not self._replay_thinking:
            yield from super().stream(request)
            return
        restored = self._restore_thinking(request)
        with ResponseStream(super().stream(restored), restored) as stream:
            yield from stream.events()
            self._remember_thinking(stream.response)

    def close(self) -> None:
        if self._resources_closed:
            return
        self._resources_closed = True
        try:
            super().close()
        finally:
            self._tool_thinking.clear()


def close_lm(lm: dspy.LM) -> None:
    """Close both DSPy's owned clients and our explicitly borrowed router."""
    try:
        lm.close()
    finally:
        if isinstance(lm.engine, GatewayEngine):
            lm.engine.close()
