"""Request-scoped provider overrides for browser-owned LLM runs.

The browser owns provider credentials (BYOK) and sends them per run on the
agent endpoint only. Two header families are accepted:

- ``X-LLM-*`` headers describe a generic OpenAI-compatible provider (key,
  model, base URL, and the wire-format selections from the settings UI).
- ``X-OpenRouter-*`` headers are the legacy OpenRouter-only form; they map
  onto the canonical OpenRouter endpoint so existing clients keep working.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_APP_TITLE = "Fleet Agent"
_MAX_API_KEY_CHARS = 4096
_MAX_MODEL_CHARS = 256
_MAX_BASE_URL_CHARS = 2048
_MODEL_PATTERN = re.compile(
    rf"^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,{_MAX_MODEL_CHARS - 1}}}$"
)

ResponseFormat = Literal["native_function_calling", "json_tool_calls"]
MessagesFormat = Literal["system_role", "developer_role"]


class ProviderOverrideError(ValueError):
    """Raised when untrusted browser provider headers are invalid."""


@dataclass(frozen=True)
class ProviderOverride:
    """Ephemeral provider settings for one agent request.

    The key is intentionally never serialized, logged, or included in a
    public result. ``fingerprint`` is only used to bind an approval resume to
    the provider context that created its hidden continuation.
    """

    api_key: str
    model: str | None = None
    api_base: str | None = None
    # ``None`` means "not pinned by the browser": the run then inherits the
    # operator's FLEET_AGENT_LLM_NATIVE_FUNCTION_CALLING selection, which
    # exists precisely for gateways that reject native tool calls.
    response_format: ResponseFormat | None = None
    messages_format: MessagesFormat = "system_role"

    @property
    def fingerprint(self) -> str:
        material = "\0".join(
            (
                self.api_key,
                self.model or "",
                self.api_base or "",
                self.response_format or "",
                self.messages_format,
            )
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def __repr__(self) -> str:
        return (
            f"ProviderOverride(model={self.model!r}, api_base={self.api_base!r}, "
            f"response_format={self.response_format!r}, "
            f"messages_format={self.messages_format!r}, api_key=<redacted>)"
        )


def _validate_api_key(raw_key: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in raw_key):
        raise ProviderOverrideError("the provider key is invalid")
    api_key = raw_key.strip()
    if not api_key or len(api_key) > _MAX_API_KEY_CHARS:
        raise ProviderOverrideError("the provider key is invalid")
    return api_key


def _validate_model(raw_model: str) -> str:
    model = raw_model.strip()
    if not _MODEL_PATTERN.fullmatch(model):
        raise ProviderOverrideError("the provider model is invalid")
    return model


def _is_private_host(hostname: str) -> bool:
    """Syntactic private/loopback host check (no DNS resolution)."""
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_reserved
        or ip.is_link_local
        or ip.is_unspecified
    )


def _resolves_to_private_address(hostname: str) -> bool:
    """Resolve the hostname and fail closed when it is not publicly routable.

    The syntactic check alone misses resolver aliases: non-dotted IPv4
    numerics (``2130706433``) and hostnames whose DNS answers point into
    private or loopback ranges both bypass it. Unresolvable hosts are also
    treated as private so a flaky or hostile resolver cannot smuggle a
    ``None`` into an allow decision.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, OSError):
        return True
    addresses = set()
    for info in infos:
        address = info[4][0]
        if not isinstance(address, str):
            # Unexpected address family; refuse to validate it.
            return True
        addresses.add(address)
    if not addresses:
        return True
    for address in addresses:
        # Strip the zone id from scoped IPv6 literals ("fe80::1%en0").
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_reserved
            or ip.is_link_local
            or ip.is_unspecified
        ):
            return True
    return False


def _validate_base_url(raw_base_url: str, *, allow_private: bool) -> str:
    """Validate a browser-supplied OpenAI-compatible endpoint (SSRF guard)."""
    base_url = raw_base_url.strip()
    if not base_url or len(base_url) > _MAX_BASE_URL_CHARS:
        raise ProviderOverrideError("the provider base URL is invalid")
    try:
        parsed = urlsplit(base_url)
    except ValueError:
        raise ProviderOverrideError("the provider base URL is invalid") from None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ProviderOverrideError("the provider base URL is invalid")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ProviderOverrideError("the provider base URL is invalid")
    if not allow_private:
        if _is_private_host(hostname.lower()):
            raise ProviderOverrideError(
                "private provider base URLs are not allowed on this server"
            )
        if _resolves_to_private_address(hostname):
            raise ProviderOverrideError(
                "the provider base URL is not a publicly routable endpoint"
            )
    return base_url


def parse_provider_override(
    headers: Mapping[str, str],
    *,
    allow_private_base_urls: bool = False,
) -> ProviderOverride | None:
    """Parse the agent-only provider headers without accepting injection.

    Parameters:
        headers: Request headers (case-insensitive).
        allow_private_base_urls: Permit loopback/private endpoints for local
            LLM servers. Off by default; the browser cannot otherwise direct
            the server at internal addresses.

    Returns:
        The parsed override, or ``None`` when no provider headers are present.

    Raises:
        ProviderOverrideError: When any provider header is invalid.
    """
    normalized_headers = {name.lower(): value for name, value in headers.items()}
    raw_key = normalized_headers.get("x-llm-key")
    raw_model = normalized_headers.get("x-llm-model")
    raw_base_url = normalized_headers.get("x-llm-base-url")
    raw_response_format = normalized_headers.get("x-llm-response-format")
    raw_messages_format = normalized_headers.get("x-llm-messages-format")
    legacy_key = normalized_headers.get("x-openrouter-key")
    legacy_model = normalized_headers.get("x-openrouter-model")

    has_generic_headers = any(
        value is not None
        for value in (
            raw_key,
            raw_model,
            raw_base_url,
            raw_response_format,
            raw_messages_format,
        )
    )
    if not has_generic_headers and raw_key is None and legacy_key is None:
        if legacy_model is None:
            return None
        raise ProviderOverrideError(
            "an API key is required for a provider model override"
        )

    if raw_key is not None and legacy_key is not None:
        raise ProviderOverrideError("conflicting provider headers")

    if raw_key is not None:
        if raw_base_url is None:
            raise ProviderOverrideError(
                "a base URL is required for a provider key override"
            )
        api_key = _validate_api_key(raw_key)
        api_base = _validate_base_url(
            raw_base_url, allow_private=allow_private_base_urls
        )
    elif legacy_key is not None:
        api_key = _validate_api_key(legacy_key)
        # Legacy browser BYOK is deliberately restricted to the canonical
        # OpenRouter endpoint; the browser cannot select an arbitrary proxy.
        api_base = OPENROUTER_API_BASE_URL
        if raw_model is None:
            raw_model = legacy_model
    else:
        raise ProviderOverrideError("an API key is required for a provider override")

    model: str | None = None
    if raw_model is not None:
        model = _validate_model(raw_model)

    response_format: ResponseFormat | None = None
    if raw_response_format is not None:
        if raw_response_format == "json_tool_calls":
            response_format = "json_tool_calls"
        elif raw_response_format != "native_function_calling":
            raise ProviderOverrideError("the provider response format is invalid")

    messages_format: MessagesFormat = "system_role"
    if raw_messages_format is not None:
        if raw_messages_format == "developer_role":
            messages_format = "developer_role"
        elif raw_messages_format != "system_role":
            raise ProviderOverrideError("the provider messages format is invalid")

    return ProviderOverride(
        api_key=api_key,
        model=model,
        api_base=api_base,
        response_format=response_format,
        messages_format=messages_format,
    )
