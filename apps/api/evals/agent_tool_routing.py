"""Small, provider-independent routing evaluation set for ReAct/Flex work."""

from __future__ import annotations

from typing import Any, Literal

import dspy

from app.agent.routing import ROUTES, ToolRoute, coerce_route

ROUTING_EXAMPLES = [
    dspy.Example(
        user_request="Explain what ReActV2 does.", expected_route="direct"
    ).with_inputs("user_request"),
    dspy.Example(
        user_request="What time is it in UTC?", expected_route="research"
    ).with_inputs("user_request"),
    dspy.Example(
        user_request="Search our documentation for AG-UI state sync.",
        expected_route="research",
    ).with_inputs("user_request"),
    dspy.Example(
        user_request="Find where FleetAgent is defined in this repository.",
        expected_route="workspace_read",
    ).with_inputs("user_request"),
    dspy.Example(
        user_request="Read apps/api/app/agent/program.py and explain it.",
        expected_route="workspace_read",
    ).with_inputs("user_request"),
    dspy.Example(
        user_request="Change the FleetAgent docstring to mention routing.",
        expected_route="workspace_write",
    ).with_inputs("user_request"),
    dspy.Example(
        user_request="Run the backend tests and tell me which ones fail.",
        expected_route="workspace_shell",
    ).with_inputs("user_request"),
    dspy.Example(
        user_request="Explain how I could run pytest locally.",
        expected_route="direct",
    ).with_inputs("user_request"),
]

_ROUTE_RANK: dict[ToolRoute, int] = {
    "direct": 0,
    "research": 1,
    "artifact": 1,
    "workspace_read": 2,
    "workspace_write": 3,
    "workspace_shell": 4,
}


def routing_metric(
    gold: dspy.Example,
    pred: dspy.Prediction,
    trace: Any = None,
    pred_name: str | None = None,
    pred_trace: Any = None,
    program_trace: Any = None,
) -> dspy.Prediction:
    """Score exact route and provide feedback that GEPA can use.

    The parameter list matches dspy 3.3.1's ``GEPAFeedbackMetric`` contract:
    GEPA binds the metric with five positional arguments and calls it with
    the target predictor's name and sub-trace during optimization.
    """
    del trace, pred_name, pred_trace, program_trace
    expected = coerce_route(getattr(gold, "expected_route", None))
    actual_value = getattr(pred, "route", None)
    actual = coerce_route(actual_value)
    if actual == expected:
        return dspy.Prediction(
            score=1.0,
            feedback="Correctly selected the minimum required capability profile.",
        )

    expected_rank = _ROUTE_RANK[expected]
    actual_rank = _ROUTE_RANK[actual]
    if actual_rank > expected_rank:
        score = 0.35
        feedback = (
            f"Selected {actual}, which grants more capability than necessary. "
            f"The request only requires {expected}."
        )
    else:
        score = 0.0
        feedback = (
            f"Selected {actual}, which cannot complete the requested operation. "
            f"At least {expected} is required."
        )
    return dspy.Prediction(score=score, feedback=feedback)


def compile_gepa_candidate(
    program: dspy.Module,
    *,
    trainset: list[dspy.Example] | None = None,
    valset: list[dspy.Example] | None = None,
    reflection_lm: dspy.LM | None = None,
    auto: Literal["light", "medium", "heavy"] = "light",
) -> dspy.Module:
    """Run GEPA only when explicitly called by an offline evaluator.

    This helper performs no persistence or promotion. The returned candidate
    remains local to the caller, which must compare it with the ReAct baseline
    before making any runtime decision.
    """
    if reflection_lm is None:
        raise ValueError(
            "GEPA requires a reflection_lm; pass a strong reflection model"
        )
    optimizer = dspy.GEPA(
        metric=routing_metric,
        auto=auto,
        reflection_lm=reflection_lm,
    )
    return optimizer.compile(
        program,
        trainset=trainset or ROUTING_EXAMPLES,
        valset=valset or ROUTING_EXAMPLES,
    )


def public_routes() -> tuple[ToolRoute, ...]:
    """Expose the route vocabulary to offline evaluation/reporting only."""
    return ROUTES
