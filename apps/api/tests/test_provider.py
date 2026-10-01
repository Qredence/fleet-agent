import socket

import pytest
from pydantic import SecretStr

from app.agent.factory import _build_adapter, _build_lm
from app.agent.gateway import GatewayEngine, close_lm
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


def test_legacy_openrouter_headers_require_migration() -> None:
    with pytest.raises(ProviderOverrideError, match="use X-LLM"):
        parse_provider_override({"X-OpenRouter-Key": "test-key"})


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


def test_override_has_run_scoped_native_routing() -> None:
    settings = Settings(
        llm_model="server/model",
        llm_base_url="https://server.example/v1",
        llm_api_key=SecretStr("server-secret"),
    )
    override = ProviderOverride(
        api_key="browser-key", model="vendor/model", api_base=OPENROUTER_API_BASE_URL
    )
    lm = _build_lm(settings, override)
    server = _build_lm(settings)
    try:
        assert isinstance(lm.engine, GatewayEngine)
        assert lm.engine is not server.engine
        assert lm.model == "fleet-gateway/vendor/model"
        assert server.model == "fleet-gateway/server/model"
        assert "browser-key" not in repr(lm)
        assert "browser-key" not in repr(override)
        assert "browser-key" not in override.model_dump_json()
    finally:
        close_lm(lm)
        close_lm(server)


@pytest.mark.parametrize(
    "mode,expected",
    [(None, False), ("json_tool_calls", False), ("native_function_calling", True)],
)
def test_response_selection_applies_to_lm_and_adapter(mode, expected) -> None:
    settings = Settings(llm_model="server/model", llm_native_function_calling=False)
    override = ProviderOverride(
        api_key="browser-key",
        api_base="https://gateway.example/v1",
        response_format=mode,
    )
    lm = _build_lm(settings, override)
    try:
        assert lm.supports_function_calling is expected
        assert (
            _build_adapter(settings, override).use_native_function_calling is expected
        )
    finally:
        close_lm(lm)


def test_explicit_native_header_overrides_server_selection(monkeypatch):
    _resolve_publicly(monkeypatch)
    override = parse_provider_override(
        {
            "X-LLM-Key": "test-key",
            "X-LLM-Base-Url": "https://gateway.example/v1",
            "X-LLM-Response-Format": "native_function_calling",
        }
    )
    assert override.response_format == "native_function_calling"
    assert _build_adapter(
        Settings(llm_native_function_calling=False), override
    ).use_native_function_calling


def test_settings_ignores_legacy_provider_environment(monkeypatch):
    monkeypatch.setenv("MODAL_MODEL_ID", "legacy/model")
    monkeypatch.setenv("MODAL_API_KEY", "legacy-key")
    monkeypatch.setenv("DATABRICKS_TOKEN", "legacy-token")
    monkeypatch.setenv("FLEET_AGENT_LLM_MODEL", "canonical/model")
    settings = Settings()
    assert settings.llm_model == "canonical/model"
    assert settings.llm_api_key is None
