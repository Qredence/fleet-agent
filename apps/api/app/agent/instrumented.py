"""Instrumented tool wrappers: AG-UI observability around plain DSPy tools.

Each wrapped call:
- gets a stable tool-call id,
- publishes ToolStarted / ToolCompleted / ToolFailed to the run's event bus,
- redacts and size-limits argument and result previews,
- preserves the real return value for ReActV2,
- re-raises real exceptions (ReActV2 converts them to error observations)
  while the public event only carries a safe message.
"""

import functools
import inspect
import json
import math
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, get_type_hints
from urllib.parse import urlsplit

from app.agui.cancel_token import RunCancelToken
from app.agui.event_bus import RunEventBus
from app.contracts.domain import (
    InlineDataEvent,
    SourceDiscovered,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

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


def sanitize_args(args: dict[str, Any]) -> str:
    """JSON preview of arguments: secrets redacted and total text capped.

    This legacy helper remains a presentation preview. Callers that emit
    protocol argument chunks must use :func:`public_tool_args_json` instead.
    """
    return preview(public_tool_args_json("", args), limit=400)


def preview(text: str, limit: int = _MAX_PREVIEW_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def truncate_result(text: str, limit: int = _MAX_RESULT_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def instrument_tool(
    fn: Callable[..., Any],
    bus: RunEventBus,
    cancel_token: RunCancelToken | None = None,
) -> Callable[..., Any]:
    # DSPy's Tool schema inference reads the wrapper, not fn: functools.wraps
    # copies __name__/__doc__ but NOT __annotations__, so wrapping a callable
    # OBJECT (SearchDocsTool/WriteReportTool) would degrade every argument to
    # Any — untyped JSON schema for the model and no Tool arg validation.
    hints_target: Callable[..., Any] = (
        fn if inspect.isfunction(fn) or inspect.ismethod(fn) else type(fn).__call__
    )

    @functools.wraps(fn)
    def wrapper(**kwargs: Any) -> Any:
        if cancel_token:
            cancel_token.check()  # no new tool starts after cancellation
        tool_call_id = f"tool_{uuid.uuid4().hex[:12]}"
        tool_name = getattr(fn, "__name__", type(fn).__name__)
        arguments_json = public_tool_args_json(tool_name, kwargs)
        bus.publish_from_worker(
            ToolStarted(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments_json=arguments_json,
                input_preview=preview(arguments_json),
            )
        )
        started = time.monotonic()
        try:
            value = fn(**kwargs)
        except Exception:
            duration_ms = int((time.monotonic() - started) * 1000)
            bus.publish_from_worker(
                ToolFailed(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    error_message=f"The {tool_name} tool call failed.",
                    duration_ms=duration_ms,
                )
            )
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        bus.publish_from_worker(
            ToolCompleted(
                tool_call_id=tool_call_id,
                name=tool_name,
                output_preview=preview(str(value)),
                duration_ms=duration_ms,
            )
        )
        # Source-producing tools (e.g. SearchDocsTool) publish the sources
        # they discovered with this call — one entry per canonical source.
        produced = getattr(fn, "last_sources", None)
        if produced:
            for source in produced:
                bus.publish_from_worker(
                    SourceDiscovered(tool_call_id=tool_call_id, source=source)
                )
            bus.publish_from_worker(
                InlineDataEvent(
                    name="sources",
                    value={
                        "schemaVersion": 1,
                        "sources": _inline_sources(produced),
                    },
                )
            )
        return value

    # Propagate the real type hints so dspy.Tool infers the true JSON schema
    # ({"query": {"type": "string"}}, not Any) — for plain functions this is
    # what functools.wraps already copies; callable objects need it explicitly.
    wrapper.__annotations__ = dict(get_type_hints(hints_target))
    return wrapper


def _inline_sources(sources: list[Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        uri = str(getattr(source, "uri", "") or "")
        source_id = str(getattr(source, "id", "") or "")
        key = (uri, source_id)
        if key in seen:
            continue
        seen.add(key)
        hostname = ""
        if uri:
            try:
                hostname = urlsplit(uri).hostname or ""
            except ValueError:
                hostname = ""
        title = str(getattr(source, "title", "") or "Untitled source").strip()[:240]
        domain = str(
            hostname or getattr(source, "source_type", "") or "source"
        ).strip()[:120]
        result.append(
            {"title": title or "Untitled source", "domain": domain or "source"}
        )
    return result[-12:]
