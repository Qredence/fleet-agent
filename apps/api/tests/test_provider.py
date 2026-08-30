import socket

import pytest
from pydantic import SecretStr

from app.agent.factory import _build_adapter, _build_lm
from app.agent.openai_compatible import OpenAICompatibleLM
from app.agent.provider import (
    OPENROUTER_API_BASE_URL,
    ProviderOverride,
    ProviderOverrideError,
    parse_provider_override,
)
from app.settings import Settings


def _resolve_publicly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend every host resolves to a public address.

    The SSRF guard resolves browser base URLs and fails closed on hosts it
    cannot resolve; unit tests use synthetic public hostnames, so they stub
    the resolver instead of depending on live DNS.
    """

    def fake_getaddrinfo(host, *args, **kwargs):  # noqa: ARG001
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_legacy_openrouter_headers_map_onto_the_canonical_endpoint() -> None:
    override = parse_provider_override(
        {
            "x-oPeNrOuTeR-kEy": "  sk-or-browser  ",
            "X-OPENROUTER-MODEL": "anthropic/claude-3.5-sonnet",
        }
    )

    assert override == ProviderOverride(
        api_key="sk-or-browser",
        model="anthropic/claude-3.5-sonnet",
        api_base=OPENROUTER_API_BASE_URL,
    )


def test_generic_headers_describe_a_custom_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolve_publicly(monkeypatch)
    override = parse_provider_override(
        {
            "X-LLM-Key": "sk-modal-browser",
            "X-LLM-Model": "openai/gpt-4o-mini",
            "X-LLM-Base-Url": "https://fleet-proxy.modal.run/v1",
            "X-LLM-Response-Format": "json_tool_calls",
            "X-LLM-Messages-Format": "developer_role",
        }
    )

    assert override == ProviderOverride(
        api_key="sk-modal-browser",
        model="openai/gpt-4o-mini",
        api_base="https://fleet-proxy.modal.run/v1",
        response_format="json_tool_calls",
        messages_format="developer_role",
    )


def test_generic_headers_leave_the_response_format_unpinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolve_publicly(monkeypatch)
    override = parse_provider_override(
        {
            "X-LLM-Key": "sk-gateway",
            "X-LLM-Base-Url": "https://gateway.example/v1",
        }
    )

    assert override is not None
    assert override.model is None
    # Unpinned formats inherit the operator's FLEET_AGENT_LLM_* selection.
    assert override.response_format is None
    assert override.messages_format == "system_role"


@pytest.mark.parametrize(
    "headers",
    [
        {"X-OpenRouter-Model": "vendor/model"},
        {"X-LLM-Model": "vendor/model"},
        {"X-LLM-Base-Url": "https://gateway.example/v1"},
        {"X-LLM-Key": "sk-gateway"},
        {"X-LLM-Key": "\nsecret", "X-LLM-Base-Url": "https://gateway.example/v1"},
        {"X-OpenRouter-Key": "\nsecret"},
        {
            "X-OpenRouter-Key": "sk-or-key",
            "X-OpenRouter-Model": "bad model",
        },
        {
            "X-OpenRouter-Key": "sk-or-key",
            "X-OpenRouter-Model": "x" * 257,
        },
        {
            "X-LLM-Key": "sk-gateway",
            "X-LLM-Base-Url": "https://gateway.example/v1",
            "X-LLM-Model": "bad model",
        },
        {
            "X-LLM-Key": "sk-gateway",
            "X-LLM-Base-Url": "ftp://gateway.example/v1",
        },
        {
            "X-LLM-Key": "sk-gateway",
            "X-LLM-Base-Url": "not a url",
        },
        {
            "X-LLM-Key": "sk-gateway",
            "X-LLM-Base-Url": "https://gateway.example/v1",
            "X-LLM-Response-Format": "xml",
        },
        {
            "X-LLM-Key": "sk-gateway",
            "X-LLM-Base-Url": "https://gateway.example/v1",
            "X-LLM-Messages-Format": "concatenated",
        },
        {
            "X-LLM-Key": "sk-gateway",
            "X-LLM-Base-Url": "https://gateway.example/v1",
            "X-OpenRouter-Key": "sk-or-key",
        },
    ],
)
def test_invalid_provider_headers_fail_closed(headers: dict[str, str]) -> None:
    with pytest.raises(ProviderOverrideError):
        parse_provider_override(headers)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:4000/v1",
        "https://127.0.0.1:4000/v1",
        "https://10.1.2.3/v1",
        "https://192.168.1.10/v1",
        "https://[::1]:4000/v1",
        "https://my-host.localhost/v1",
        # Non-dotted IPv4 numerics are not IP literals to ipaddress, but the
        # OS resolver maps them onto loopback, so the guard must resolve.
        "http://2130706433:4000/v1",
        "http://0x7f000001:4000/v1",
        "http://127.1:4000/v1",
    ],
)
def test_private_base_urls_are_rejected_unless_explicitly_allowed(
    base_url: str,
) -> None:
    headers = {"X-LLM-Key": "sk-local", "X-LLM-Base-Url": base_url}

    with pytest.raises(ProviderOverrideError):
        parse_provider_override(headers)

    override = parse_provider_override(headers, allow_private_base_urls=True)
    assert override is not None
    assert override.api_base == base_url


def test_override_builds_a_run_scoped_lm_with_fixed_openrouter_routing() -> None:
    settings = Settings(
        llm_model="server/model",
        llm_base_url="https://private-gateway.example/v1",
        llm_api_key=SecretStr("server-secret"),
        openrouter_http_referer="https://fleet.example",
    )

    browser_lm = _build_lm(
        settings,
        ProviderOverride(
            api_key="sk-or-browser",
            model="vendor/model",
            api_base=OPENROUTER_API_BASE_URL,
        ),
    )
    server_lm = _build_lm(settings)

    assert isinstance(browser_lm, OpenAICompatibleLM)
    assert browser_lm.api_key == "sk-or-browser"
    assert browser_lm.model == "vendor/model"
    assert browser_lm.api_base == OPENROUTER_API_BASE_URL
    assert browser_lm.use_developer_role is False
    assert browser_lm._extra_headers == {
        "HTTP-Referer": "https://fleet.example",
        "X-Title": "Fleet Agent",
    }
    assert isinstance(server_lm, OpenAICompatibleLM)
    assert server_lm.api_key == "server-secret"
    assert server_lm.model == "server/model"
    assert server_lm.api_base == "https://private-gateway.example/v1"
    assert "sk-or-browser" not in repr(browser_lm)


def test_override_formats_flow_into_lm_and_adapter() -> None:
    settings = Settings(llm_model="server/model")

    json_lm = _build_lm(
        settings,
        ProviderOverride(
            api_key="sk-browser",
            api_base="https://gateway.example/v1",
            response_format="json_tool_calls",
            messages_format="developer_role",
        ),
    )
    json_adapter = _build_adapter(
        settings,
        ProviderOverride(
            api_key="sk-browser",
            api_base="https://gateway.example/v1",
            response_format="json_tool_calls",
            messages_format="developer_role",
        ),
    )
    native_adapter = _build_adapter(
        settings,
        ProviderOverride(
            api_key="sk-browser",
            api_base="https://gateway.example/v1",
            response_format="native_function_calling",
        ),
    )

    assert json_lm.use_developer_role is True
    assert json_lm.supports_function_calling is False
    assert json_adapter.use_native_function_calling is False
    assert native_adapter.use_native_function_calling is True


def test_override_without_pinned_format_inherits_the_server_selection() -> None:
    # The operator disabled native function calling for a gateway that rejects
    # tool_choice + response_format; an unpinned override must not re-enable it.
    settings = Settings(llm_model="server/model", llm_native_function_calling=False)

    lm = _build_lm(
        settings,
        ProviderOverride(api_key="sk-browser", api_base="https://gateway.example/v1"),
    )
    adapter = _build_adapter(
        settings,
        ProviderOverride(api_key="sk-browser", api_base="https://gateway.example/v1"),
    )

    assert lm.supports_function_calling is False
    assert adapter.use_native_function_calling is False

    # ...but an explicit browser pin still wins over the server default.
    pinned = _build_lm(
        settings,
        ProviderOverride(
            api_key="sk-browser",
            api_base="https://gateway.example/v1",
            response_format="native_function_calling",
        ),
    )
    assert pinned.supports_function_calling is True


def test_override_without_custom_model_keeps_server_model() -> None:
    settings = Settings(llm_model="server/model", llm_api_key=None)

    lm = _build_lm(
        settings,
        ProviderOverride(api_key="sk-or-browser", api_base=OPENROUTER_API_BASE_URL),
    )

    assert lm.model == "server/model"
    assert lm.api_base == OPENROUTER_API_BASE_URL


def test_modal_env_trio_is_the_default_provider() -> None:
    settings = Settings(
        llm_model="openai/gpt-4o-mini",
        llm_api_key=SecretStr("server-secret"),
        modal_model_id="openai/gpt-4o",
        modal_base_url="https://fleet-proxy.modal.run/v1",
        modal_api_key=SecretStr("modal-secret"),
    )

    lm = _build_lm(settings)

    assert isinstance(lm, OpenAICompatibleLM)
    assert lm.model == "openai/gpt-4o"
    assert lm.api_key == "modal-secret"
    assert lm.api_base == "https://fleet-proxy.modal.run/v1"
    # The OpenAI-compatible client strips the LiteLLM-style routing prefix.
    assert lm._gateway_model_id == "gpt-4o"

    override_lm = _build_lm(
        settings,
        ProviderOverride(
            api_key="sk-browser",
            model="vendor/model",
            api_base="https://gateway.example/v1",
        ),
    )
    assert override_lm.model == "vendor/model"
    assert override_lm.api_key == "sk-browser"


def test_settings_reads_unprefixed_modal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_MODEL_ID", "openai/gpt-4o")
    monkeypatch.setenv("MODAL_BASE_URL", "https://fleet-proxy.modal.run/v1")
    monkeypatch.setenv("MODAL_API_KEY", "modal-secret")

    settings = Settings()

    assert settings.modal_model_id == "openai/gpt-4o"
    assert settings.modal_base_url == "https://fleet-proxy.modal.run/v1"
    assert settings.modal_api_key is not None
    assert settings.modal_api_key.get_secret_value() == "modal-secret"


def test_fingerprint_covers_every_override_field() -> None:
    base = ProviderOverride(
        api_key="sk-key",
        model="vendor/model",
        api_base="https://gateway.example/v1",
        response_format="json_tool_calls",
        messages_format="developer_role",
    )
    base_fingerprint = base.fingerprint

    variants = (
        ProviderOverride(
            api_key="sk-other",
            model="vendor/model",
            api_base="https://gateway.example/v1",
            response_format="json_tool_calls",
            messages_format="developer_role",
        ),
        ProviderOverride(
            api_key="sk-key",
            model="vendor/other",
            api_base="https://gateway.example/v1",
            response_format="json_tool_calls",
            messages_format="developer_role",
        ),
        ProviderOverride(
            api_key="sk-key",
            model="vendor/model",
            api_base="https://other.example/v1",
            response_format="json_tool_calls",
            messages_format="developer_role",
        ),
        ProviderOverride(
            api_key="sk-key",
            model="vendor/model",
            api_base="https://gateway.example/v1",
            response_format="native_function_calling",
            messages_format="developer_role",
        ),
        ProviderOverride(
            api_key="sk-key",
            model="vendor/model",
            api_base="https://gateway.example/v1",
            response_format="json_tool_calls",
            messages_format="system_role",
        ),
    )

    assert (
        len({base_fingerprint, *(v.fingerprint for v in variants)}) == len(variants) + 1
    )
    assert "sk-key" not in base_fingerprint
