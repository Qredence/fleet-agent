"""Shared offline scoring: ``dspy.Evaluate``-backed router scoring.

The eval runner and the GEPA optimizer read the same numbers from
``evals.scoring.score_router``: the mean least-privilege score, the misses
behind it in devset order, and the mean per-request latency.
"""

from __future__ import annotations

import dspy

from evals.agent_tool_routing import ROUTING_EXAMPLES, routing_metric, routing_score
from evals.scoring import RoutingScore, score_router
from tests.helpers.scripted_lm import ScriptedLM, router_call


def _examples(*routes: str) -> list[dspy.Example]:
    return [
        next(e for e in ROUTING_EXAMPLES if e.expected_route == route)
        for route in routes
    ]


def test_routing_score_matches_the_gepa_metric() -> None:
    example = next(e for e in ROUTING_EXAMPLES if e.expected_route == "workspace_read")

    assert routing_score(example, dspy.Prediction(route="workspace_read")) == 1.0
    assert routing_score(example, dspy.Prediction(route="workspace_shell")) == 0.35
    assert routing_score(example, dspy.Prediction(route="direct")) == 0.0
    assert routing_score(example, dspy.Prediction(route="workspace_read")) == float(
        routing_metric(example, dspy.Prediction(route="workspace_read")).score
    )


def test_exact_routes_score_one_with_no_misses() -> None:
    examples = _examples("direct", "research", "artifact")
    lm = ScriptedLM([router_call(e.expected_route) for e in examples])

    scored = score_router(dspy.Predict("user_request -> route"), lm, examples)

    assert scored.mean == 1.0
    assert scored.misses == []
    assert scored.mean_latency_s > 0.0


def test_under_selection_is_reported_as_a_miss_in_devset_order() -> None:
    examples = _examples("direct", "workspace_read", "workspace_shell")
    lm = ScriptedLM([router_call("direct") for _ in examples])

    scored = score_router(dspy.Predict("user_request -> route"), lm, examples)

    # One exact route, two under-selections scored as total failures. The mean
    # is the exact fraction, not dspy.Evaluate's two-decimal percentage.
    assert scored.mean == 1 / 3
    assert [miss[1] for miss in scored.misses] == ["workspace_read", "workspace_shell"]
    assert [miss[2] for miss in scored.misses] == ["direct", "direct"]
    assert [miss[3] for miss in scored.misses] == [0.0, 0.0]
    assert scored.failures == 0


class _RaisingRouter(dspy.Module):  # type: ignore[misc]  # DSPy is untyped
    """A router whose provider is down: every call raises."""

    def forward(self, user_request: str) -> dspy.Prediction:
        raise RuntimeError(f"gateway down for {user_request!r}")


def test_a_raised_example_is_counted_apart_from_a_wrong_route() -> None:
    """A provider error must not read as a routing miss.

    ``dspy.Evaluate`` scores a raised example 0 and keeps going, so the mean
    alone cannot distinguish "the gateway failed" from "the router chose
    wrong". The failure count is what makes that visible.
    """
    examples = _examples("direct", "research", "artifact")

    scored = score_router(_RaisingRouter(), ScriptedLM([]), examples)

    assert scored.failures == len(examples)
    assert scored.mean == 0.0
    assert [miss[2] for miss in scored.misses] == ["<missing>"] * len(examples)


def test_empty_example_set_scores_zero_without_calling_the_program() -> None:
    scored = score_router(dspy.Predict("user_request -> route"), ScriptedLM([]), [])

    assert scored == RoutingScore(mean=0.0, misses=[], mean_latency_s=0.0)


def test_as_tuple_keeps_the_optimizer_harness_shape() -> None:
    miss = ("q", "direct", "research", 0.35)
    scored = RoutingScore(mean=0.5, misses=[miss], mean_latency_s=0.25)

    assert scored.as_tuple() == (0.5, [miss], 0.25)


def test_production_router_signature_scores_through_the_shared_harness() -> None:
    """The eval runner's router (``ToolRoutingSignature``) is what gets scored."""
    from app.agent.routing import ToolRoutingSignature

    examples = _examples("direct", "research")
    lm = ScriptedLM([router_call(e.expected_route) for e in examples])

    scored = score_router(dspy.Predict(ToolRoutingSignature), lm, examples)

    assert scored.mean == 1.0
    assert scored.misses == []


def test_optimizer_scorer_returns_the_shared_routing_score() -> None:
    """``evals.optimize._score_router`` hands back the whole RoutingScore.

    The optimizer prints the failure count next to the means, so it needs more
    than the ``(mean, misses, latency)`` tuple it used to unpack.
    """
    from evals.optimize import _score_router

    examples = _examples("direct", "research")
    lm = ScriptedLM([router_call(e.expected_route) for e in examples])

    scored = _score_router(dspy.Predict("user_request -> route"), lm, examples)

    assert isinstance(scored, RoutingScore)
    assert (scored.mean, scored.misses) == (1.0, [])
    assert scored.mean_latency_s > 0.0
    assert scored.failures == 0
