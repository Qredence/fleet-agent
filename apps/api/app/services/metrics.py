"""Minimal in-process metrics registry (plan.md Phase 9 list, JSON /metrics).

Thread-safe counters/gauges/durations — no external metrics daemon required
in dev; Prometheus/OpenTelemetry can replace the read-side later.
"""

import threading
from dataclasses import asdict, dataclass


@dataclass
class DurationSummary:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0


@dataclass
class MetricsSnapshot:
    counters: dict[str, int]
    gauges: dict[str, int]
    durations: dict[str, dict[str, float]]


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, int] = {}
        self._durations: dict[str, DurationSummary] = {}

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def gauge_delta(self, name: str, delta: int) -> None:
        with self._lock:
            self._gauges[name] = self._gauges.get(name, 0) + delta

    def observe(self, name: str, duration_ms: float) -> None:
        with self._lock:
            summary = self._durations.setdefault(name, DurationSummary())
            summary.count += 1
            summary.total_ms += duration_ms
            summary.max_ms = max(summary.max_ms, duration_ms)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "durations": {
                    name: asdict(summary) for name, summary in self._durations.items()
                },
            }
