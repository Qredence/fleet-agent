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
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from app.agui.cancel_token import RunCancelToken
from app.agui.event_bus import RunEventBus
from app.contracts.domain import (
    SourceDiscovered,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

_SENSITIVE_KEY_PARTS = ("key", "token", "secret", "password", "auth", "credential")
_MAX_VALUE_CHARS = 120
_MAX_PREVIEW_CHARS = 300
_MAX_RESULT_CHARS = 2000


def sanitize_args(args: dict[str, Any]) -> str:
    """JSON preview of arguments: secrets redacted, values and total capped."""
    safe: dict[str, str] = {}
    for key, value in args.items():
        if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
            safe[key] = "***"
        else:
            rendered_value = str(value)
            safe[key] = (
                rendered_value[:_MAX_VALUE_CHARS] + "…"
                if len(rendered_value) > _MAX_VALUE_CHARS
                else rendered_value
            )
    rendered = json.dumps(safe, ensure_ascii=False)
    return rendered[:400] + "…" if len(rendered) > 400 else rendered


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
    @functools.wraps(fn)
    def wrapper(**kwargs: Any) -> Any:
        if cancel_token:
            cancel_token.check()  # no new tool starts after cancellation
        tool_call_id = f"tool_{uuid.uuid4().hex[:12]}"
        bus.publish_from_worker(
            ToolStarted(
                tool_call_id=tool_call_id,
                name=fn.__name__,
                input_preview=sanitize_args(kwargs),
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
                    name=fn.__name__,
                    error_message=f"The {fn.__name__} tool call failed.",
                    duration_ms=duration_ms,
                )
            )
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        bus.publish_from_worker(
            ToolCompleted(
                tool_call_id=tool_call_id,
                name=fn.__name__,
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
        return value

    return wrapper
