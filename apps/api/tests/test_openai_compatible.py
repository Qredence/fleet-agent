"""Tests for the OpenAI-compatible LM that serves custom gateways.

These tests never touch the network: the OpenAI SDK client is replaced by a
recording stub, and every assertion runs against the request it captured.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import dspy
import httpx
import openai
import pydantic
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.completion_usage import CompletionUsage

from app.agent.openai_compatible import OpenAICompatibleLM

_GATEWAY = "https://gateway.example/v1"
_MODEL = "zai-org/GLM-5.3-Flash"


def _make_client(
    response: Any = None, error: Exception | None = None
) -> tuple[Any, list[dict[str, Any]]]:
    """A stand-in openai.OpenAI client that records create() calls."""
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if error is not None:
            raise error
        assert response is not None
        return response

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return client, calls


def _completion(
    content: str | None = "hello",
    *,
    finish_reason: str = "stop",
    usage: CompletionUsage | None = None,
) -> ChatCompletion:
    return ChatCompletion(
        id="cmpl-test",
        created=1,
        model="gateway-model",
        object="chat.completion",
        choices=[
            Choice(
                index=0,
                finish_reason=finish_reason,  # type: ignore[arg-type]
                message=ChatCompletionMessage(role="assistant", content=content),
            )
        ],
        usage=usage,
    )


def _make_lm(
    *,
    model: str = _MODEL,
    api_base: str = _GATEWAY,
    client: Any = None,
    use_developer_role: bool = False,
    supports_native_function_calling: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> OpenAICompatibleLM:
    return OpenAICompatibleLM(
        model=model,
        api_key="sk-test",
        api_base=api_base,
        temperature=0.2,
        cache=False,
        supports_native_function_calling=supports_native_function_calling,
        use_developer_role=use_developer_role,
        extra_headers=extra_headers,
        client=client,
    )


def _status_error(status: int, message: str = "boom") -> openai.APIStatusError:
    request = httpx.Request("POST", f"{_GATEWAY}/chat/completions")
    response = httpx.Response(
        status, request=request, json={"error": {"message": message}}
    )
    body: dict[str, Any] = {"error": {"message": message}}
    error_cls: type[openai.APIStatusError]
    if status == 401:
        error_cls = openai.AuthenticationError
    elif status == 400:
        error_cls = openai.BadRequestError
    elif status == 429:
        error_cls = openai.RateLimitError
    elif status == 500:
        error_cls = openai.InternalServerError
    else:
        error_cls = openai.APIStatusError
    return error_cls(message, response=response, body=body)


_USER_MESSAGE = [{"role": "user", "content": "hi"}]


class TestModelIdRouting:
    def test_bare_gateway_model_ids_are_sent_verbatim(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(client=client)(messages=_USER_MESSAGE)

        assert calls[0]["model"] == _MODEL

    def test_litellm_style_openai_prefix_is_stripped_for_custom_gateways(
        self,
    ) -> None:
        client, calls = _make_client(_completion())
        lm = _make_lm(model="openai/zai-org/GLM-5.3-Flash", client=client)
        lm(messages=_USER_MESSAGE)

        assert calls[0]["model"] == _MODEL
        assert lm.model == "openai/zai-org/GLM-5.3-Flash"

    def test_openrouter_model_ids_keep_their_vendor_prefix(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(
            model="openai/gpt-4o-mini",
            api_base="https://openrouter.ai/api/v1",
            client=client,
        )(messages=_USER_MESSAGE)

        assert calls[0]["model"] == "openai/gpt-4o-mini"


class TestRequestAssembly:
    def test_prompt_only_call_builds_a_user_message(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(client=client)(prompt="Reply with exactly: OK")

        assert calls[0]["messages"] == [
            {"role": "user", "content": "Reply with exactly: OK"}
        ]

    def test_neither_prompt_nor_messages_fails_closed(self) -> None:
        lm = _make_lm(client=_make_client(_completion())[0])
        with pytest.raises(dspy.LMInvalidRequestError):
            lm()

    def test_tool_and_format_parameters_pass_through(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(client=client)(
            messages=_USER_MESSAGE,
            tools=[{"type": "function", "function": {"name": "submit"}}],
            tool_choice={"type": "function", "function": {"name": "submit"}},
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=512,
        )

        call = calls[0]
        assert call["tools"] == [{"type": "function", "function": {"name": "submit"}}]
        assert call["tool_choice"] == {
            "type": "function",
            "function": {"name": "submit"},
        }
        assert call["response_format"] == {"type": "json_object"}
        assert call["temperature"] == 0.7
        assert call["max_tokens"] == 512
        assert call["extra_headers"] is None

    def test_none_valued_parameters_are_dropped(self) -> None:
        client, calls = _make_client(_completion())
        OpenAICompatibleLM(
            model="m",
            api_key="sk-test",
            api_base=_GATEWAY,
            temperature=None,
            max_tokens=None,
            client=client,
        )(messages=_USER_MESSAGE)

        assert "temperature" not in calls[0]
        assert "max_tokens" not in calls[0]

    def test_unknown_message_keys_are_sanitized(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(client=client)(
            messages=[
                {
                    "role": "user",
                    "content": "hi",
                    "internal_meta": {"must": "not leak"},
                    "name": "caller",
                }
            ]
        )

        assert calls[0]["messages"] == [
            {"role": "user", "content": "hi", "name": "caller"}
        ]

    def test_system_role_is_sent_by_default(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(client=client)(
            messages=[
                {"role": "system", "content": "be brief"},
                *_USER_MESSAGE,
            ]
        )

        assert calls[0]["messages"][0]["role"] == "system"

    def test_developer_role_rewrites_system_messages(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(use_developer_role=True, client=client)(
            messages=[
                {"role": "system", "content": "be brief"},
                *_USER_MESSAGE,
            ]
        )

        assert calls[0]["messages"][0]["role"] == "developer"
        assert calls[0]["messages"][1]["role"] == "user"

    def test_extra_headers_are_applied_per_request(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(
            extra_headers={
                "HTTP-Referer": "https://fleet.example",
                "X-Title": "Fleet Agent",
            },
            client=client,
        )(messages=_USER_MESSAGE)

        assert calls[0]["extra_headers"] == {
            "HTTP-Referer": "https://fleet.example",
            "X-Title": "Fleet Agent",
        }

    def test_pydantic_response_formats_become_json_schema_wire_dicts(self) -> None:
        class _Outputs(pydantic.BaseModel):
            answer: str

        client, calls = _make_client(_completion())
        _make_lm(client=client)(
            messages=_USER_MESSAGE,
            response_format=_Outputs,
            temperature=0.2,
        )

        assert calls[0]["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "_Outputs",
                "schema": _Outputs.model_json_schema(),
                "strict": True,
            },
        }

    def test_internal_dspy_keys_never_reach_the_gateway(self) -> None:
        client, calls = _make_client(_completion())
        _make_lm(client=client)(
            messages=_USER_MESSAGE,
            rollout_id=7,
            cache=False,
        )

        assert "rollout_id" not in calls[0]
        assert "cache" not in calls[0]


class TestResponseProcessing:
    def test_forward_returns_the_completion_object(self) -> None:
        response = _completion(
            "The answer",
            usage=CompletionUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )
        client, calls = _make_client(response)
        lm = _make_lm(client=client)

        # The legacy forward contract returns the provider response itself...
        assert lm.forward(messages=_USER_MESSAGE) is response
        # ...while BaseLM.__call__ post-processes it into legacy outputs.
        assert lm(messages=_USER_MESSAGE) == ["The answer"]
        assert calls[-1]["model"] == _MODEL

    def test_truncated_responses_log_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client, _calls = _make_client(_completion(finish_reason="length"))
        lm = _make_lm(client=client)

        with caplog.at_level(logging.WARNING, logger="app.agent.openai_compatible"):
            lm(messages=_USER_MESSAGE)

        assert "truncated" in caplog.text


class TestCapabilitySurface:
    def test_native_function_calling_is_the_configured_selection(self) -> None:
        assert _make_lm().supports_function_calling is True
        json_calls = _make_lm(supports_native_function_calling=False)
        assert json_calls.supports_function_calling is False

    def test_structured_outputs_and_wire_params_are_advertised(self) -> None:
        lm = _make_lm()

        assert lm.supports_response_schema is True
        assert lm.supports_reasoning is False
        assert "response_format" in lm.supported_params
        assert "tools" in lm.supported_params
        assert "tool_choice" in lm.supported_params


class TestErrorBoundary:
    @pytest.mark.parametrize(
        ("status", "error_cls"),
        [
            (401, dspy.LMAuthError),
            (403, dspy.LMAuthError),
            (404, dspy.LMUnsupportedModelError),
            (429, dspy.LMRateLimitError),
            (500, dspy.LMServerError),
            (422, dspy.LMInvalidRequestError),
        ],
    )
    def test_status_errors_map_to_dspy_hierarchy(
        self, status: int, error_cls: type[Exception]
    ) -> None:
        client, _calls = _make_client(error=_status_error(status))
        lm = _make_lm(client=client)

        with pytest.raises(error_cls) as excinfo:
            lm(messages=_USER_MESSAGE)

        assert excinfo.value.model == _MODEL  # type: ignore[attr-defined]

    def test_context_window_errors_are_detected(self) -> None:
        client, _calls = _make_client(
            error=_status_error(400, "maximum context length is 8192 tokens")
        )
        lm = _make_lm(client=client)

        with pytest.raises(dspy.ContextWindowExceededError):
            lm(messages=_USER_MESSAGE)

    def test_connection_errors_map_to_transport(self) -> None:
        request = httpx.Request("POST", f"{_GATEWAY}/chat/completions")
        error = openai.APIConnectionError(message="Connection error.", request=request)
        client, _calls = _make_client(error=error)
        lm = _make_lm(client=client)

        with pytest.raises(dspy.LMTransportError):
            lm(messages=_USER_MESSAGE)

    def test_timeout_errors_map_to_timeout(self) -> None:
        request = httpx.Request("POST", f"{_GATEWAY}/chat/completions")
        error = openai.APITimeoutError(request=request)
        client, _calls = _make_client(error=error)
        lm = _make_lm(client=client)

        with pytest.raises(dspy.LMTimeoutError):
            lm(messages=_USER_MESSAGE)

    def test_provider_errors_carry_status_and_model_metadata(self) -> None:
        client, _calls = _make_client(error=_status_error(400, "bad request"))
        lm = _make_lm(client=client)

        with pytest.raises(dspy.LMInvalidRequestError) as excinfo:
            lm(messages=_USER_MESSAGE)

        assert excinfo.value.status == 400
        assert excinfo.value.model == _MODEL  # type: ignore[attr-defined]
        assert "sk-test" not in str(excinfo.value)


class TestSerialization:
    def test_repr_and_dump_state_exclude_the_api_key(self) -> None:
        lm = _make_lm()

        assert "sk-test" not in repr(lm)
        state = lm.dump_state()
        assert "sk-test" not in str(state)
        assert state["api_base"] == _GATEWAY
        assert state["supports_native_function_calling"] is True
        assert state["use_developer_role"] is False

    def test_dump_state_round_trips_without_credentials(self) -> None:
        lm = _make_lm(client=_make_client(_completion())[0])
        state = lm.dump_state()

        restored = OpenAICompatibleLM.load_state(state)

        assert restored.model == lm.model
        assert restored.api_base == lm.api_base
        assert restored.supports_function_calling == lm.supports_function_calling
        assert restored.use_developer_role == lm.use_developer_role
        # Credentials are never serialized; the client is built lazily so a
        # credential-less restore still constructs.
        assert restored.api_key is None
        assert restored._client is None
