"""Native DSPy callback bridging agent execution events to the AG-UI RunEventBus.

Replaces custom function wrappers with DSPy's built-in BaseCallback lifecycle.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from dspy.utils.callback import BaseCallback

from app.agent.instrumented import preview, sanitize_args
from app.agui.cancel_token import RunCancelToken
from app.agui.event_bus import RunEventBus
from app.contracts.domain import (
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
        self._bus.publish_from_worker(
            ToolStarted(
                tool_call_id=event_call_id,
                name=name,
                input_preview=sanitize_args(kwargs),
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
