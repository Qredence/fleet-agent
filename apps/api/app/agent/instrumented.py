"""Redaction helpers for the public AG-UI event surface.

Tool lifecycle events are published by ``app.agent.callbacks.AgUiRunCallback``,
which drives DSPy's own ``BaseCallback`` seam. This module holds the pure
functions that seam needs: turning raw tool arguments and results into bounded,
secret-free text that is safe to put on the wire.
"""

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.kernel.content_safety import scrub_public_text

_SENSITIVE_KEY_PARTS = ("key", "token", "secret", "password", "auth", "credential")
_MAX_PREVIEW_CHARS = 300
_MAX_RESULT_CHARS = 2000
_MAX_PUBLIC_COLLECTION_ITEMS = 20


def public_tool_args(tool_name: str, args: Mapping[str, Any]) -> dict[str, object]:
    """Return bounded, redacted, JSON-compatible tool arguments.

    The returned object is intentionally not truncated as a serialized string:
    ``TOOL_CALL_ARGS`` must remain valid JSON after it is sent to assistant-ui.
    Large values are summarized before serialization instead.
    """
    return {
        str(key): _public_value(tool_name, str(key), value, depth=0)
        for key, value in list(args.items())[:_MAX_PUBLIC_COLLECTION_ITEMS]
    }


def public_tool_args_json(tool_name: str, args: Mapping[str, Any]) -> str:
    """Serialize public tool arguments without ever emitting invalid JSON."""
    return json.dumps(
        public_tool_args(tool_name, args),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def bounded_public_tool_args_json(
    tool_name: str,
    args: Mapping[str, Any],
    *,
    max_chars: int = _MAX_PREVIEW_CHARS,
) -> str:
    """Serialize scrubbed public tool arguments as valid JSON within max_chars."""
    public = public_tool_args(tool_name, args)
    serialized = scrub_public_text(
        json.dumps(public, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    )
    if len(serialized) <= max_chars:
        return serialized

    prioritized_keys = (["query"] if "query" in public else []) + [
        key for key in public if key != "query"
    ]
    bounded: dict[str, object] = {}
    omitted = False
    for key in prioritized_keys:
        candidate = {**bounded, key: public[key]}
        candidate_json = scrub_public_text(
            json.dumps(
                {**candidate, "truncated": True},
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        if len(candidate_json) <= max_chars:
            bounded = candidate
        else:
            omitted = True
    if omitted:
        bounded["truncated"] = True
    result = scrub_public_text(
        json.dumps(bounded, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    )
    if len(result) <= max_chars:
        return result
    return '{"truncated":true}' if max_chars >= 18 else "{}"[:max_chars]


def _public_value(_tool_name: str, key: str, value: Any, *, depth: int) -> object:
    lowered = key.lower()
    if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        return "***"

    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"type": "number", "finite": False}
    if isinstance(value, str):
        return {"type": "string", "chars": len(value)}

    if depth >= 2:
        if isinstance(value, (bytes, bytearray)):
            return {"type": "bytes", "bytes": len(value)}
        return {"type": type(value).__name__}
    if isinstance(value, Mapping):
        return {
            str(nested_key): _public_value(
                _tool_name,
                str(nested_key),
                nested_value,
                depth=depth + 1,
            )
            for nested_key, nested_value in list(value.items())[
                :_MAX_PUBLIC_COLLECTION_ITEMS
            ]
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [
            _public_value(_tool_name, key, item, depth=depth + 1)
            for item in list(value)[:_MAX_PUBLIC_COLLECTION_ITEMS]
        ]
    if isinstance(value, (bytes, bytearray)):
        return {"type": "bytes", "bytes": len(value)}
    return {"type": type(value).__name__}


def preview(text: str, limit: int = _MAX_PREVIEW_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def truncate_result(text: str, limit: int = _MAX_RESULT_CHARS) -> str:
    """Preview with the larger bound used for tool result content."""
    return preview(text, limit=limit)
