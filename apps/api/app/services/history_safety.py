"""Validation for the browser-owned, user-visible assistant-ui envelope."""

import re
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

_MAX_NESTING_DEPTH = 64
_REASONING_VALUES = frozenset(
    {
        "reasoning",
        "thought",
        "thinking",
        "chain_of_thought",
        "analysis",
    }
)
_REASONING_DESCRIPTOR_KEYS = frozenset({"type", "kind", "parttype", "contenttype"})
_FORBIDDEN_KEYS = {
    "next_thought",
    "nextThought",
    "history",
    "dspy_history",
    "dspyHistory",
    "provider_prompt",
    "providerPrompt",
    "provider_prompts",
    "providerPrompts",
    "provider_content",
    "providerContent",
    "stack_trace",
    "stackTrace",
    "traceback",
    "exception",
    "raw_prompt",
    "rawPrompt",
    "raw_history",
    "rawHistory",
    "chain_of_thought",
    "chainOfThought",
    "reasoning",
    "thought",
    "thinking",
    # Artifact storage is server-owned.  A persisted assistant-ui message may
    # carry a safe download URL, but it must never carry a filesystem path or
    # the internal storage key used by ArtifactStorage.
    "storage_key",
    "storageKey",
    "storage_path",
    "storagePath",
    "filesystem_path",
    "filesystemPath",
    "absolute_path",
    "absolutePath",
    "local_path",
    "localPath",
    "server_path",
    "serverPath",
}
_FORBIDDEN_NORMALIZED = {
    re.sub(r"[^a-z0-9]", "", key.lower()) for key in _FORBIDDEN_KEYS
}
_SENSITIVE_KEYS = {
    "apikey",
    "accesskey",
    "auth",
    "authorization",
    "clientsecret",
    "secret",
    "password",
    "credential",
    "credentials",
    "bearertoken",
    "refreshtoken",
    "token",
}
_ALLOWED_FORMATS = {"aui/v0"}
_ALLOWED_ROLES = {"user", "assistant"}


class MessageWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parentId: str | None = None
    format: str
    content: dict[str, Any]
    runConfig: dict[str, Any] | None = None

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        if value not in _ALLOWED_FORMATS:
            raise ValueError("Unsupported message format.")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: dict[str, Any]) -> dict[str, Any]:
        role = value.get("role")
        if role not in _ALLOWED_ROLES:
            raise ValueError("Only user and assistant messages may be persisted.")
        _validate_nested(value)
        return value

    @field_validator("runConfig")
    @classmethod
    def validate_run_config(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None:
            _validate_nested(value)
        return value


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_forbidden_key(key: object) -> bool:
    normalized = _normalize(key)
    # Treat newly introduced reasoning-shaped names as server-only too, while
    # retaining the explicit allowlist for unrelated field names.
    return normalized in _FORBIDDEN_NORMALIZED or any(
        marker in normalized
        for marker in ("reasoning", "chainofthought", "nextthought")
    )


def _is_reasoning_descriptor(key: object, value: object) -> bool:
    return (
        _normalize(key) in _REASONING_DESCRIPTOR_KEYS
        and isinstance(value, str)
        and _normalize(value) in {_normalize(item) for item in _REASONING_VALUES}
    )


def _validate_nested(value: dict[str, Any]) -> None:
    for key, nested in _walk_dicts(value):
        normalized = _normalize(key)
        if _is_forbidden_key(key) or normalized in _SENSITIVE_KEYS:
            raise ValueError("Message contains server-only content.")
        if _is_reasoning_descriptor(key, nested):
            raise ValueError("Reasoning parts are not persistable.")


def _walk_dicts(value: Any) -> Iterator[tuple[str, Any]]:
    """Walk JSON-like values without recursion or unbounded cycles."""

    stack: list[tuple[Any, int]] = [(value, 0)]
    seen: set[int] = set()
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_NESTING_DEPTH:
            raise ValueError("Message content is too deeply nested.")
        if isinstance(current, dict):
            marker = id(current)
            if marker in seen:
                raise ValueError("Message content contains a cycle.")
            seen.add(marker)
            for key, nested in current.items():
                yield str(key), nested
                stack.append((nested, depth + 1))
        elif isinstance(current, list):
            marker = id(current)
            if marker in seen:
                raise ValueError("Message content contains a cycle.")
            seen.add(marker)
            stack.extend((nested, depth + 1) for nested in current)


def sanitize_message_content(value: dict[str, Any]) -> dict[str, Any]:
    """Remove legacy/internal parts before a message reaches the browser."""

    sanitized = _sanitize_value(value)
    return sanitized if isinstance(sanitized, dict) else {}


def _sanitize_value(
    value: Any, *, depth: int = 0, active: set[int] | None = None
) -> Any:
    """Best-effort sanitization bounded against deep/cyclic JSON values."""

    if depth > _MAX_NESTING_DEPTH:
        return None
    active = active if active is not None else set()
    if isinstance(value, dict):
        marker = id(value)
        if marker in active:
            return None
        active.add(marker)
        try:
            if any(
                _is_reasoning_descriptor(key, nested) for key, nested in value.items()
            ):
                return None
            result: dict[str, Any] = {}
            for key, nested in value.items():
                if _is_forbidden_key(key) or _normalize(key) in _SENSITIVE_KEYS:
                    continue
                clean = _sanitize_value(nested, depth=depth + 1, active=active)
                if clean is not None:
                    result[str(key)] = clean
            return result
        finally:
            active.remove(marker)
    if isinstance(value, list):
        marker = id(value)
        if marker in active:
            return None
        active.add(marker)
        try:
            return [
                clean
                for item in value
                if (clean := _sanitize_value(item, depth=depth + 1, active=active))
                is not None
            ]
        finally:
            active.remove(marker)
    return value
