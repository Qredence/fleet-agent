"""MLflow genai scorers for the routing suite: deterministic first, judge opt-in.

Three deterministic scorers need no provider and no credentials: least-privilege
route correctness (the same metric GEPA optimizes), tool-call budget, and
latency budget. They are ``mlflow.genai.scorers.scorer``-decorated functions, so
``mlflow.genai.evaluate`` hands each row its ``inputs``, ``outputs``,
``expectations``, and ``trace`` and aggregates the returned floats.

The one LLM judge is OPT-IN: it needs a model identifier and a provider, so it
is never part of ``deterministic_scorers()`` and never runs in the default
(eval-runner, optimizer, test) path.

Verified against mlflow 3.16.0: ``mlflow.genai.evaluate(data=<dataset>,
scorers=[...], predict_fn=...)`` accepts an ``EvaluationDataset`` plus custom
scorers, logs a run, and skips a scorer that returns None.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import dspy
from mlflow.genai.scorers import Scorer, scorer

from app.agent.routing import coerce_route
from evals.agent_tool_routing import routing_metric

DEFAULT_TOOL_CALL_BUDGET = 8
DEFAULT_LATENCY_BUDGET_S = 120.0
JUDGE_MODEL_ENV = "FLEET_AGENT_MLFLOW_JUDGE_MODEL"


def _budget_score(observed: float, budget: float) -> float:
    """1.0 inside the budget, else the remaining fraction of it, floored at 0."""
    if observed <= budget:
        return 1.0
    if budget <= 0:
        return 0.0
    return max(0.0, 1.0 - (observed - budget) / budget)


def _reported(outputs: Any, key: str) -> float | None:
    """A numeric value the run itself reported, when it reported one."""
    if isinstance(outputs, Mapping):
        value = outputs.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _trace_tool_calls(trace: Any) -> int | None:
    """TOOL spans in an MLflow trace, or None when there is no trace."""
    spans = getattr(getattr(trace, "data", None), "spans", None)
    if spans is None:
        return None
    return sum(
        1 for span in spans if str(getattr(span, "span_type", "")).upper() == "TOOL"
    )


def _trace_seconds(trace: Any) -> float | None:
    """Execution duration of an MLflow trace in seconds (the entity is in ms)."""
    duration_ms = getattr(getattr(trace, "info", None), "execution_duration", None)
    if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
        return float(duration_ms) / 1000.0
    return None


@scorer(name="fleet_route_least_privilege")
def route_least_privilege(
    inputs: Any = None, outputs: Any = None, expectations: Any = None
) -> float:
    """Exact route scores 1.0, over-selection 0.35, under-selection 0.0.

    Delegates to ``routing_metric`` so the MLflow scorer, the eval runner, and
    the GEPA optimizer cannot drift apart on what least privilege means.
    """
    gold = dspy.Example(
        expected_route=(
            expectations.get("expected_route")
            if isinstance(expectations, Mapping)
            else None
        )
    )
    route_raw = outputs.get("route") if isinstance(outputs, Mapping) else outputs
    predicted = dspy.Prediction(route=coerce_route(route_raw))
    return float(routing_metric(gold, predicted).score)


@scorer(name="fleet_tool_call_budget")
def tool_call_budget(
    outputs: Any = None, expectations: Any = None, trace: Any = None
) -> float | None:
    """Tool calls spent against the row's budget.

    Prefers the count the run reported in ``outputs["tool_calls"]`` and falls
    back to counting the trace's TOOL spans. A row with neither is skipped
    (None) rather than scored 1.0, so an unobserved run cannot look efficient.
    """
    budget = float((expectations or {}).get("max_tool_calls", DEFAULT_TOOL_CALL_BUDGET))
    observed = _reported(outputs, "tool_calls")
    if observed is None:
        counted = _trace_tool_calls(trace)
        observed = None if counted is None else float(counted)
    return None if observed is None else _budget_score(observed, budget)


@scorer(name="fleet_latency_budget")
def latency_budget(
    outputs: Any = None, expectations: Any = None, trace: Any = None
) -> float | None:
    """Wall-clock seconds spent against the row's budget.

    Prefers ``outputs["latency_s"]`` and falls back to the trace's execution
    duration; a row with neither is skipped, like the tool-call budget.
    """
    budget = float((expectations or {}).get("max_latency_s", DEFAULT_LATENCY_BUDGET_S))
    observed = _reported(outputs, "latency_s")
    if observed is None:
        observed = _trace_seconds(trace)
    return None if observed is None else _budget_score(observed, budget)


def deterministic_scorers() -> list[Scorer]:
    """The provider-free scorer set: the default for every eval path."""
    return [route_least_privilege, tool_call_budget, latency_budget]


def answer_quality_judge(
    model: str | None = None,
    *,
    base_url: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Scorer:
    """Build the OPT-IN LLM judge of the final answer.

    Needs a judge model — ``model=`` or ``FLEET_AGENT_MLFLOW_JUDGE_MODEL`` — and
    a provider that serves it. The model must be a provider-prefixed URI
    (``openai:/gpt-4.1-mini``): mlflow validates the format at construction and
    rejects a bare model name, so a provider error is raised early.
    ``base_url``/``extra_headers`` route the judge through a gateway (mlflow's
    own ``make_judge`` knobs), which is how this project reaches its configured
    OpenAI-compatible endpoint. Raising instead of defaulting keeps the judge out
    of any path that must stay offline.
    """
    from mlflow.genai import make_judge

    resolved = model or os.environ.get(JUDGE_MODEL_ENV)
    if not resolved:
        raise ValueError(
            "the answer-quality judge needs a model: pass model=... or set "
            f"{JUDGE_MODEL_ENV}"
        )
    return make_judge(
        name="fleet_answer_quality",
        instructions=(
            "Score how well the final answer resolves the user request. "
            "Request: {{ inputs }}. Answer: {{ outputs }}. "
            "Expected capability profile: {{ expectations }}. "
            "1.0 complete and correct, 0.5 partially useful, 0.0 wrong or empty."
        ),
        model=resolved,
        base_url=base_url,
        extra_headers=extra_headers,
        feedback_value_type=float,
    )
