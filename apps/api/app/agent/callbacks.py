"""Native DSPy callback bridging agent execution events to the AG-UI RunEventBus.

Replaces custom function wrappers with DSPy's built-in BaseCallback lifecycle.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from dspy.utils.callback import BaseCallback

from app.agent.instrumented import preview, public_tool_args, public_tool_args_json
from app.agui.cancel_token import RunCancelToken
from app.agui.event_bus import RunEventBus
from app.contracts.domain import (
    InlineDataEvent,
    SourceDiscovered,
    SourceResult,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)


class AgUiRunCallback(BaseCallback):  # type: ignore[misc]
    """Bridges DSPy tool and LM lifecycle events to AG-UI domain events."""

    def __init__(
        self,
        bus: RunEventBus,
        cancel_token: RunCancelToken | None = None,
        *,
        id_prefix: str = "",
        step_id: str | None = None,
        before_tool: Callable[[str], None] | None = None,
        before_model: Callable[[], None] | None = None,
    ) -> None:
        self._bus = bus
        self._cancel_token = cancel_token
        self._id_prefix = id_prefix
        self._step_id = step_id
        self._before_tool = before_tool
        self._before_model = before_model
        self.sources: list[SourceResult] = []
        self._tool_starts: dict[str, float] = {}
        self._tool_instances: dict[str, Any] = {}
        self._web_search_queries: dict[str, dict[str, object]] = {}
        self._web_search_cycle = 0

    def on_tool_start(
        self,
        call_id: str,
        instance: Any,
        inputs: dict[str, Any],
    ) -> None:
        name = getattr(instance, "name", getattr(instance, "__name__", "tool"))
        # The submit tool is ReActV2's internal completion mechanism.
        if name == "submit":
            return

        if self._cancel_token:
            self._cancel_token.check()
        if self._before_tool is not None:
            self._before_tool(name)

        event_call_id = f"{self._id_prefix}{call_id}"
        self._tool_starts[event_call_id] = time.monotonic()
        self._tool_instances[event_call_id] = instance

        kwargs = inputs.get("kwargs", inputs) if isinstance(inputs, dict) else {}
        if name == "web_search":
            self._web_search_cycle += 1
            query = public_tool_args(name, {"query": kwargs.get("query")}).get(
                "query", {"type": "string", "chars": 0}
            )
            query_metadata = (
                query if isinstance(query, dict) else {"type": type(query).__name__}
            )
            self._web_search_queries[event_call_id] = query_metadata
            self._bus.publish_from_worker(
                InlineDataEvent(
                    name="web-search",
                    value={
                        "schemaVersion": 1,
                        "query": query_metadata,
                        "results": [],
                        "visibleResults": 0,
                        "searching": True,
                        "cycle": self._web_search_cycle,
                    },
                )
            )
        arguments_json = public_tool_args_json(name, kwargs)
        self._bus.publish_from_worker(
            ToolStarted(
                tool_call_id=event_call_id,
                name=name,
                arguments_json=arguments_json,
                input_preview=preview(arguments_json),
                step_id=self._step_id,
            )
        )

    def on_tool_end(
        self,
        call_id: str,
        outputs: Any | None,
        exception: BaseException | None = None,
    ) -> None:
        event_call_id = f"{self._id_prefix}{call_id}"
        if event_call_id not in self._tool_starts:
            return

        if self._cancel_token is not None and self._cancel_token.cancelled:
            self._tool_starts.pop(event_call_id, None)
            self._tool_instances.pop(event_call_id, None)
            self._web_search_queries.pop(event_call_id, None)
            return

        started = self._tool_starts.pop(event_call_id, time.monotonic())
        instance = self._tool_instances.pop(event_call_id, None)
        name = (
            getattr(instance, "name", getattr(instance, "__name__", "tool"))
            if instance
            else "tool"
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        if exception is not None:
            self._bus.publish_from_worker(
                ToolFailed(
                    tool_call_id=event_call_id,
                    name=name,
                    error_message=f"The {name} tool call failed.",
                    duration_ms=duration_ms,
                )
            )
            self._publish_web_search_finished(event_call_id, [])
        else:
            self._bus.publish_from_worker(
                ToolCompleted(
                    tool_call_id=event_call_id,
                    name=name,
                    output_preview=preview(str(outputs)),
                    duration_ms=duration_ms,
                )
            )
            # Emit discovered sources from source-producing tools
            func = getattr(instance, "func", instance)
            produced = getattr(func, "last_sources", None)
            if produced:
                for source in produced:
                    self._bus.publish_from_worker(
                        SourceDiscovered(
                            tool_call_id=event_call_id,
                            source=source,
                            step_id=self._step_id,
                        )
                    )
                    self.sources.append(source)
                self._publish_sources()
            self._publish_web_search_finished(event_call_id, list(produced or []))

    def resume_tool_end(
        self,
        call_id: str,
        instance: Any,
        outputs: Any | None,
        exception: BaseException | None = None,
    ) -> None:
        """Publish a result for a tool started by an earlier SSE response.

        A resumed approval request gets a fresh callback instance, so the
        normal ``on_tool_end`` lookup has no in-process start record.  The
        tool-call id remains stable across the two responses; seed only the
        private timing/instance bookkeeping and emit the result, never a
        second TOOL_CALL_START event.
        """

        event_call_id = f"{self._id_prefix}{call_id}"
        self._tool_starts.setdefault(event_call_id, time.monotonic())
        self._tool_instances.setdefault(event_call_id, instance)
        self.on_tool_end(
            event_call_id.removeprefix(self._id_prefix), outputs, exception
        )

    def on_lm_start(
        self,
        call_id: str,
        instance: Any,
        inputs: dict[str, Any],
    ) -> None:
        if self._cancel_token:
            self._cancel_token.check()
        if self._before_model is not None:
            self._before_model()

    def _publish_web_search_finished(
        self, event_call_id: str, sources: list[SourceResult]
    ) -> None:
        query = self._web_search_queries.pop(event_call_id, None)
        if query is None:
            return
        self._bus.publish_from_worker(
            InlineDataEvent(
                name="web-search",
                value={
                    "schemaVersion": 1,
                    "query": query or {"type": "string", "chars": 0},
                    "results": [
                        {
                            "title": _safe_inline_text(source.title, limit=240)
                            or "Untitled source",
                            "domain": _inline_source(source)["domain"],
                        }
                        for source in sources[:8]
                    ],
                    "visibleResults": min(len(sources), 8),
                    "searching": False,
                    "cycle": self._web_search_cycle,
                },
            )
        )

    def _publish_sources(self) -> None:
        self._bus.publish_from_worker(
            InlineDataEvent(
                name="sources",
                value={
                    "schemaVersion": 1,
                    "sources": _inline_sources(self.sources),
                },
            )
        )


def _safe_inline_text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _inline_source(source: SourceResult) -> dict[str, str]:
    hostname = ""
    if source.uri:
        try:
            hostname = urlsplit(source.uri).hostname or ""
        except ValueError:
            hostname = ""
    return {
        "title": _safe_inline_text(source.title, limit=240) or "Untitled source",
        "domain": _safe_inline_text(hostname or source.source_type, limit=120)
        or "source",
    }


def _inline_sources(sources: list[SourceResult]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        key = (source.uri or "", source.id)
        if key in seen:
            continue
        seen.add(key)
        result.append(_inline_source(source))
    return result[-12:]
