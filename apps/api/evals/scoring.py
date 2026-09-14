"""Shared router scoring for the offline harness, on ``dspy.Evaluate``.

The eval runner and the GEPA optimizer both need the same three things: the
mean least-privilege score of a router over the routing example set, the
individual misses behind that mean, and the mean per-request latency. Both
used to hand-roll that loop — including the ``dspy.context``, the adapter
choice, and the miss extraction — and the two copies could drift apart.

They now share one ``dspy.Evaluate`` call, which is DSPy's own evaluation
entry point: it runs the program through ``ParallelExecutor`` (so DSPy
settings and callback ancestry reach every call), isolates per-example
failures instead of aborting the run, and returns results in devset order.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import dspy

from evals.agent_tool_routing import routing_score

Miss = tuple[str, str, str, float]
"""One non-exact route as ``(request, expected_route, actual_route, score)``."""


@dataclass(frozen=True)
class RoutingScore:
    """One router's held-out score over a routing example set."""

    mean: float
    misses: list[Miss]
    mean_latency_s: float
    failures: int = 0
    """Examples whose program call raised.

    ``dspy.Evaluate`` scores a raised example 0 and continues, which is
    indistinguishable from a wrong route in the mean alone. Kept out of
    ``as_tuple`` so the optimizer's unpacking contract is unchanged.
    """

    def as_tuple(self) -> tuple[float, list[Miss], float]:
        """Return the ``(mean, misses, mean latency)`` shape callers unpack."""
        return (self.mean, self.misses, self.mean_latency_s)


class _TimedProgram(dspy.Module):  # type: ignore[misc]  # DSPy is untyped
    """Wrap a router to record per-call wall time and per-call failures.

    ``dspy.Evaluate`` returns scores, not timings, and the optimizer's report
    and MLflow history both carry mean per-request latency — it is the cost
    side of the sandboxed Flex router — so timing stays on the call path.
    """

    def __init__(self, program: dspy.Module) -> None:
        super().__init__()
        self.program = program
        self.latencies: list[float] = []
        self.failures = 0

    def forward(self, **inputs: Any) -> Any:
        started = time.perf_counter()
        try:
            return self.program(**inputs)
        except Exception:
            # Count before re-raising: Evaluate swallows this into a 0 score,
            # so a broken provider would otherwise read as a bad router.
            self.failures += 1
            raise
        finally:
            self.latencies.append(time.perf_counter() - started)

    @property
    def mean_latency_s(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)


def score_router(
    router: dspy.Module,
    lm: dspy.BaseLM,
    examples: Sequence[dspy.Example],
    *,
    num_threads: int = 1,
) -> RoutingScore:
    """Score ``router`` over ``examples`` through ``dspy.Evaluate``.

    ``num_threads`` defaults to 1: the harness runs against operator gateways,
    where unbounded fan-out is a real risk, so callers opt into parallelism.
    """
    if not examples:
        return RoutingScore(mean=0.0, misses=[], mean_latency_s=0.0)

    timed = _TimedProgram(router)
    adapter = dspy.JSONAdapter(use_native_function_calling=True)
    evaluate = dspy.Evaluate(
        devset=list(examples),
        metric=routing_score,
        num_threads=num_threads,
        display_progress=False,
        display_table=False,
        failure_score=0.0,
    )
    with dspy.context(lm=lm, adapter=adapter):
        evaluation = evaluate(timed)

    scores: list[float] = []
    misses: list[Miss] = []
    for example, prediction, score in evaluation.results:
        value = float(score)
        scores.append(value)
        if value < 1.0:
            misses.append(
                (
                    str(example.user_request),
                    str(example.expected_route),
                    str(getattr(prediction, "route", "<missing>")),
                    value,
                )
            )
    # Mean the raw per-example metric values rather than ``evaluation.score``:
    # that field is a percentage rounded to two decimals, so it quantizes the
    # mean (a third of the examples passing would read as 0.3333).
    return RoutingScore(
        mean=sum(scores) / len(scores),
        misses=misses,
        mean_latency_s=timed.mean_latency_s,
        failures=timed.failures,
    )
