import dspy
import pytest

from evals.agent_tool_routing import (
    ROUTING_EXAMPLES,
    compile_gepa_candidate,
    routing_metric,
)
from tests.helpers.scripted_lm import ScriptedLM


def test_routing_dataset_covers_least_privilege_examples():
    routes = {example.expected_route for example in ROUTING_EXAMPLES}
    assert routes == {
        "direct",
        "research",
        "workspace_read",
        "workspace_write",
        "workspace_shell",
    }


def test_routing_metric_rewards_exact_and_penalizes_over_privilege():
    example = ROUTING_EXAMPLES[3]
    exact = routing_metric(example, dspy.Prediction(route="workspace_read"))
    over = routing_metric(example, dspy.Prediction(route="workspace_shell"))

    assert exact.score == 1.0
    assert over.score == 0.35
    assert "more capability" in over.feedback


def test_routing_metric_satisfies_gepa_metric_contract():
    # dspy 3.3.1's GEPA binds its metric with five positional arguments
    # before optimization starts; the arity must stay compatible.
    optimizer = dspy.GEPA(
        metric=routing_metric,
        auto="light",
        reflection_lm=ScriptedLM([]),
    )

    assert optimizer is not None


def test_compile_gepa_candidate_requires_reflection_lm():
    program = dspy.Predict("user_request -> route")

    with pytest.raises(ValueError, match="reflection_lm"):
        compile_gepa_candidate(program)
