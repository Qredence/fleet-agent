"""DSPy operational tracing that never supplies execution content to MLflow."""

from threading import Lock
from typing import Any

from dspy.utils.callback import BaseCallback


class MetadataTracingCallback(BaseCallback):  # type: ignore[misc]
    """Constant names/types and status only; independent spans avoid context leaks."""

    def __init__(self) -> None:
        self._spans: dict[str, Any] = {}
        self._lock = Lock()

    def _start(self, call_id: str, operation: str, span_type: str) -> None:
        try:
            import mlflow

            span = mlflow.start_span_no_context(
                name=operation,
                span_type=span_type,
                attributes={"capture": "metadata-only"},
            )
            with self._lock:
                self._spans[call_id] = span
        except Exception:  # noqa: BLE001 — telemetry must never fail execution
            return

    def _end(self, call_id: str, exception: Exception | None) -> None:
        with self._lock:
            span = self._spans.pop(call_id, None)
        if span is None:
            return
        try:
            span.end(status="ERROR" if exception is not None else "OK")
        except Exception:  # noqa: BLE001 — do not log secret-bearing export errors
            return

    def on_module_start(
        self, call_id: str, instance: Any, inputs: dict[str, Any]
    ) -> None:
        self._start(call_id, "dspy.module", "CHAIN")

    def on_module_end(
        self, call_id: str, outputs: Any, exception: Exception | None = None
    ) -> None:
        self._end(call_id, exception)

    def on_lm_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        self._start(call_id, "dspy.lm", "LLM")

    def on_lm_end(
        self, call_id: str, outputs: Any, exception: Exception | None = None
    ) -> None:
        self._end(call_id, exception)

    def on_tool_start(
        self, call_id: str, instance: Any, inputs: dict[str, Any]
    ) -> None:
        self._start(call_id, "dspy.tool", "TOOL")

    def on_tool_end(
        self, call_id: str, outputs: Any, exception: Exception | None = None
    ) -> None:
        self._end(call_id, exception)


_active_callback: MetadataTracingCallback | None = None


def set_metadata_tracing(enabled: bool) -> None:
    global _active_callback
    _active_callback = MetadataTracingCallback() if enabled else None


def get_metadata_callback() -> MetadataTracingCallback | None:
    return _active_callback
