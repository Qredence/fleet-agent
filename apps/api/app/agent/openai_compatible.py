"""An OpenAI-compatible chat LM that serves custom gateways without LiteLLM.

DSPy's ``BaseLM`` contract accepts any LM whose ``forward()`` returns an
OpenAI-shaped chat completion, which is exactly the boundary the typed LM API
migration describes (https://dspy.ai/community/normalized-lm-api-migration/).
Every provider configured with a base URL (browser BYOK overrides, the
``MODAL_*`` default trio, and ``FLEET_AGENT_LLM_BASE_URL``) is by definition
OpenAI-compatible, so this LM talks to those gateways with the OpenAI SDK
directly and never depends on LiteLLM's provider-prefix routing.

Model ids are sent to the gateway exactly as configured. A leading
``openai/`` is stripped for non-OpenRouter gateways because that prefix only
exists as a LiteLLM routing marker; OpenRouter ids such as
``openai/gpt-4o-mini`` are native and are never rewritten.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import dspy
import httpx
import openai
import pydantic
from openai import OpenAI

from app.agent.provider import OPENROUTER_API_BASE_URL

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 600.0

# Message keys the chat-completions wire format accepts. Everything else that
# might ride along in legacy LM kwargs is dropped before the request leaves.
_MESSAGE_KEYS = frozenset({"role", "content", "name", "tool_calls", "tool_call_id"})

# Request keys that are DSPy-internal and must never reach the gateway.
_INTERNAL_REQUEST_KEYS = frozenset(
    {"cache", "rollout_id", "stream_options", "send_stream"}
)

# Chat-completions parameters this LM is willing to forward. The JSON adapter
# consults ``supported_params`` before choosing a wire format.
_SUPPORTED_PARAMS = frozenset(
    {
        "temperature",
        "top_p",
        "n",
        "stop",
        "seed",
        "user",
        "max_tokens",
        "max_completion_tokens",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "metadata",
    }
)

# Mirrors the context-window phrases LiteLLM maps onto its own
# ContextWindowExceededError so adapter retry behavior stays identical.
_CONTEXT_WINDOW_PHRASES = (
    "context window",
    "context length",
    "context_length",
    "maximum context",
    "prompt is too long",
    "input length and",
)

_PROVIDER_NAME = "openai-compatible"


def _default_client(
    *,
    api_key: str | None,
    api_base: str,
    timeout_seconds: float,
    max_retries: int,
) -> OpenAI:
    """Build the OpenAI SDK client used for gateway requests.

    Redirects are never followed: the SSRF guard validated the original base
    URL, and a 3xx answer must not silently retarget gateway traffic at an
    internal address.
    """
    return OpenAI(
        api_key=api_key,
        base_url=api_base,
        timeout=timeout_seconds,
        max_retries=max_retries,
        default_headers={"User-Agent": f"DSPy/{dspy.__version__}"},
        http_client=httpx.Client(follow_redirects=False),
    )


def _is_context_window_error(exc: openai.APIStatusError) -> bool:
    message = str(exc).lower()
    return any(phrase in message for phrase in _CONTEXT_WINDOW_PHRASES)


def _wire_response_format(response_format: Any) -> Any:
    """Convert a pydantic structured-output model into its wire dict.

    DSPy's JSON adapter passes the response format as a pydantic BaseModel
    class (litellm serialized it transparently); the OpenAI SDK's create()
    only accepts the ``json_schema`` wire shape.
    """
    if isinstance(response_format, type) and issubclass(
        response_format, pydantic.BaseModel
    ):
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_format.__name__,
                "schema": response_format.model_json_schema(),
                "strict": True,
            },
        }
    return response_format


def _status_error_class(status: int) -> type[dspy.LMError]:
    # dspy ships without type information, so error classes arrive as Any;
    # the annotated local keeps the function's contract checkable.
    error_cls: type[dspy.LMError]
    if status in (401, 403):
        error_cls = dspy.LMAuthError
    elif status == 402:
        error_cls = dspy.LMBillingError
    elif status == 404:
        error_cls = dspy.LMUnsupportedModelError
    elif status == 408:
        error_cls = dspy.LMTimeoutError
    elif status == 429:
        error_cls = dspy.LMRateLimitError
    elif 400 <= status < 500:
        error_cls = dspy.LMInvalidRequestError
    elif status >= 500:
        error_cls = dspy.LMServerError
    else:
        error_cls = dspy.LMProviderError
    return error_cls


class OpenAICompatibleLM(dspy.BaseLM):  # type: ignore[misc]
    """Chat LM for OpenAI-compatible gateways, built on the OpenAI SDK.

    The model id is forwarded to the gateway verbatim (minus a LiteLLM-style
    ``openai/`` routing prefix on non-OpenRouter gateways), so gateway-native
    ids such as ``zai-org/GLM-5.3-Flash`` work without any provider prefix.
    """

    forward_contract = "legacy"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        api_base: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
        num_retries: int = 3,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        supports_native_function_calling: bool = True,
        use_developer_role: bool = False,
        extra_headers: dict[str, str] | None = None,
        client: OpenAI | None = None,
    ) -> None:
        super().__init__(
            model=model,
            model_type="chat",
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
            num_retries=num_retries,
        )
        # BaseLM ships untyped; re-assert the types our contract relies on.
        self.model: str = model
        self.api_key = api_key
        self.api_base = api_base
        self.use_developer_role = use_developer_role
        self._supports_native_function_calling = supports_native_function_calling
        self._extra_headers = dict(extra_headers) if extra_headers else None
        self._timeout_seconds = timeout_seconds
        # Built lazily on first use so credential-less state (dump/load) never
        # needs a live client, and configuration errors surface as LM errors.
        self._client: OpenAI | None = client

    # ------------------------------------------------------------------
    # Capability surface consulted by the JSON adapter.
    # ------------------------------------------------------------------

    @property
    def supports_function_calling(self) -> bool:
        """Whether the gateway serves native OpenAI function calling.

        Configured per run from the operator's or browser's response-format
        selection: custom gateways are not in LiteLLM's capability tables, so
        the explicit selection is the single source of truth.
        """
        return self._supports_native_function_calling

    @property
    def supports_reasoning(self) -> bool:
        return False

    @property
    def supports_response_schema(self) -> bool:
        """Structured outputs are attempted; gateways that reject them fail loud."""
        return True

    @property
    def supported_params(self) -> set[str]:
        return set(_SUPPORTED_PARAMS)

    # ------------------------------------------------------------------
    # Legacy forward contract.
    # ------------------------------------------------------------------

    def forward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call the gateway's chat-completions endpoint.

        When DSPy opens a stream (``dspy.settings.send_stream`` set by
        ``dspy.streamify`` for a listener-target predictor), the gateway
        response is streamed delta-by-delta into that stream as
        litellm-shaped chunks carrying the caller's predict id, and the full
        completion is still returned for the adapter to parse. OpenAI SDK
        exceptions are wrapped in DSPy's structured LM error hierarchy,
        mirroring ``dspy.LM``'s error boundary.
        """
        from dspy.dsp.utils.settings import settings as dspy_settings

        stream = dspy_settings.send_stream
        if stream is not None:
            return self._forward_streaming(
                stream,
                dspy_settings,
                prompt=prompt,
                messages=messages,
                **kwargs,
            )
        cache = kwargs.pop("cache", self.cache)
        request = self._build_request(prompt=prompt, messages=messages, **kwargs)
        completion_fn = self._get_completion_fn(cache)
        response = completion_fn(request=request)
        self._check_truncation(response)
        return response

    def _forward_streaming(
        self,
        stream: Any,
        dspy_settings: Any,
        *,
        prompt: str | None,
        messages: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> Any:
        """Serve one streamed completion into DSPy's open stream.

        Only content deltas are forwarded (StreamListener parses
        ``choices[0].delta.content``); tool-call deltas never appear here
        because non-target predictors run with ``send_stream`` disabled.
        The full response is rebuilt from the accumulated content so the
        adapter's parse path stays identical to a non-streamed call.
        """
        # Streaming responses are never served from the DSPy cache.
        kwargs.pop("cache", None)
        from dspy.streaming.messages import sync_send_to_stream
        from litellm import ModelResponse, ModelResponseStream
        from litellm.types.utils import (
            Choices,
            Delta,
            Message,
            StreamingChoices,
            Usage,
        )

        request = self._build_request(prompt=prompt, messages=messages, **kwargs)
        request["stream"] = True
        request["stream_options"] = {"include_usage": True}
        caller_predict_id = (
            id(dspy_settings.caller_predict) if dspy_settings.caller_predict else None
        )

        content_parts: list[str] = []
        finish_reason: str | None = None
        usage: Usage | None = None
        try:
            response = self._ensure_client().chat.completions.create(
                **request,
                extra_headers=self._extra_headers,
            )
            for chunk in response:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                choice = choices[0]
                reason = getattr(choice, "finish_reason", None)
                if reason:
                    finish_reason = str(reason)
                delta = getattr(choice, "delta", None)
                delta_content = getattr(delta, "content", None)
                if not delta_content:
                    continue
                content_parts.append(delta_content)
                wrapped = ModelResponseStream(
                    id="chatcmpl-stream",
                    object="chat.completion.chunk",
                    created=0,
                    model=self.model,
                    choices=[
                        StreamingChoices(
                            index=0,
                            delta=Delta(role="assistant", content=delta_content),
                            finish_reason=None,
                        )
                    ],
                )
                if caller_predict_id:
                    wrapped.predict_id = caller_predict_id
                sync_send_to_stream(stream, wrapped)
        except Exception as exc:
            if isinstance(exc, dspy.LMError):
                raise
            raise self._wrap_gateway_error(exc) from exc

        message = Message(role="assistant", content="".join(content_parts))
        full = ModelResponse(
            id="chatcmpl-stream",
            object="chat.completion",
            created=0,
            model=self.model,
            choices=[
                Choices(
                    index=0,
                    message=message,
                    finish_reason=finish_reason or "stop",
                )
            ],
            usage=usage,
        )
        self._check_truncation(full)
        return full

    async def aforward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Async alias; the sync client is thread-safe for requests."""
        return await asyncio.to_thread(
            self.forward, prompt=prompt, messages=messages, **kwargs
        )

    # ------------------------------------------------------------------
    # Request assembly.
    # ------------------------------------------------------------------

    @property
    def _gateway_model_id(self) -> str:
        """The model id sent to the gateway.

        ``openai/`` is a LiteLLM routing marker rather than part of a
        gateway-native id, so it is stripped for ordinary gateways exactly as
        LiteLLM would have stripped it. OpenRouter ids natively contain vendor
        prefixes and are forwarded untouched.
        """
        if self.api_base.rstrip("/") == OPENROUTER_API_BASE_URL:
            return self.model
        return self.model.removeprefix("openai/")

    def _build_request(
        self,
        *,
        prompt: str | None,
        messages: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not messages:
            if not prompt:
                raise dspy.LMInvalidRequestError(
                    "an LM call requires either messages or a prompt",
                    model=self.model,
                    provider=_PROVIDER_NAME,
                )
            messages = [{"role": "user", "content": prompt}]
        if self.use_developer_role:
            messages = [
                (
                    {**message, "role": "developer"}
                    if message.get("role") == "system"
                    else message
                )
                for message in messages
            ]

        request = {**self.kwargs, **kwargs}
        if request.get("rollout_id") is None:
            request.pop("rollout_id", None)
        for key in _INTERNAL_REQUEST_KEYS:
            request.pop(key, None)
        request["model"] = self._gateway_model_id
        request["messages"] = [
            {key: value for key, value in message.items() if key in _MESSAGE_KEYS}
            for message in messages
        ]
        # ``extra_headers`` is an OpenAI SDK keyword argument, not a body
        # parameter; it is applied in ``_create`` instead.
        request.pop("extra_headers", None)
        if "response_format" in request:
            request["response_format"] = _wire_response_format(
                request["response_format"]
            )
        return {key: value for key, value in request.items() if value is not None}

    def _get_completion_fn(self, cache: bool) -> Callable[..., Any]:
        """Return the completion callable, DSPy-cache wrapped when enabled."""
        if not cache:
            return self._create
        from dspy.clients.cache import request_cache

        cached: Callable[..., Any] = request_cache(cache_arg_name="request")(
            self._create
        )
        return cached

    def _ensure_client(self) -> OpenAI:
        """Build the gateway client on first use (never at construction)."""
        if self._client is None:
            try:
                self._client = _default_client(
                    api_key=self.api_key,
                    api_base=self.api_base,
                    timeout_seconds=self._timeout_seconds,
                    max_retries=self.num_retries,
                )
            except openai.OpenAIError as exc:
                raise dspy.LMNotConfiguredError(
                    str(exc), model=self.model, provider=_PROVIDER_NAME
                ) from exc
        return self._client

    def _create(self, *, request: dict[str, Any]) -> Any:
        extra_headers = self._extra_headers
        try:
            return self._ensure_client().chat.completions.create(
                **request,
                extra_headers=extra_headers,
            )
        except Exception as exc:
            if isinstance(exc, dspy.LMError):
                raise
            raise self._wrap_gateway_error(exc) from exc

    def _wrap_gateway_error(self, exc: Exception) -> dspy.LMError:
        """Convert OpenAI SDK exceptions into DSPy's LM error hierarchy."""
        # dspy ships without type information; the annotated local keeps this
        # function's return contract checkable under strict mypy.
        error: dspy.LMError
        if isinstance(exc, openai.APITimeoutError):
            error = dspy.LMTimeoutError(
                str(exc), model=self.model, provider=_PROVIDER_NAME
            )
        elif isinstance(exc, openai.APIConnectionError):
            error = dspy.LMTransportError(
                str(exc), model=self.model, provider=_PROVIDER_NAME
            )
        elif isinstance(exc, openai.APIStatusError):
            status = int(exc.status_code)
            message = str(exc)
            if _is_context_window_error(exc):
                # Keyword-only constructor (message is not positional).
                error = dspy.ContextWindowExceededError(
                    model=self.model,
                    message=message,
                    provider=_PROVIDER_NAME,
                    status=status,
                )
            else:
                error = _status_error_class(status)(
                    message,
                    model=self.model,
                    provider=_PROVIDER_NAME,
                    status=status,
                )
        elif isinstance(exc, openai.OpenAIError):
            error = dspy.LMError(str(exc), model=self.model, provider=_PROVIDER_NAME)
        else:
            error = dspy.LMUnexpectedError(
                str(exc), model=self.model, provider=_PROVIDER_NAME
            )
        return error

    def _check_truncation(self, response: Any) -> None:
        if any(
            getattr(choice, "finish_reason", None) == "length"
            for choice in response.choices
        ):
            logger.warning(
                "LM response was truncated (finish_reason=length, model=%s, "
                "max_tokens=%r). Raise max_tokens if outputs look cut short.",
                self.model,
                self.kwargs.get("max_tokens"),
            )

    # ------------------------------------------------------------------
    # Serialization (never includes the API key).
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(model={self.model!r}, "
            f"api_base={self.api_base!r}, "
            f"native_function_calling={self._supports_native_function_calling!r}, "
            f"use_developer_role={self.use_developer_role!r}, api_key=<redacted>)"
        )

    def dump_state(self) -> dict[str, Any]:
        native_function_calling = self._supports_native_function_calling
        state: dict[str, Any] = super().dump_state()
        state.update(
            {
                "api_base": self.api_base,
                "supports_native_function_calling": native_function_calling,
                "use_developer_role": self.use_developer_role,
            }
        )
        if self._extra_headers:
            state["extra_headers"] = dict(self._extra_headers)
        return state

    @classmethod
    def load_state(cls, state: dict[str, Any]) -> OpenAICompatibleLM:
        init = dict(state)
        init.pop("_dspy_lm_class", None)
        init.pop("model_type", None)
        # Credentials are never serialized; a restored LM runs credential-less
        # until the caller supplies a key.
        init.setdefault("api_key", None)
        init["supports_native_function_calling"] = init.pop(
            "supports_native_function_calling", True
        )
        return cls(**init)
