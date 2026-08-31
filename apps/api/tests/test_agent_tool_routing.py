import dspy
import pytest

from evals.agent_tool_routing import (
    ADVERSARIAL_ROUTING_EXAMPLES,
    CANONICAL_ROUTING_EXAMPLES,
    ROUTING_EXAMPLES,
    compile_gepa_candidate,
    routing_metric,
    validate_routing_dataset,
)
from evals.run import main as eval_run_main
from tests.helpers.scripted_lm import ScriptedLM


def test_routing_dataset_covers_least_privilege_examples():
    routes = {example.expected_route for example in ROUTING_EXAMPLES}
    assert routes == {
        "direct",
        "research",
        "artifact",
        "workspace_read",
        "workspace_write",
        "workspace_shell",
    }
    # The canonical core pins every route; the adversarial set attacks it.
    assert {e.expected_route for e in CANONICAL_ROUTING_EXAMPLES} == routes
    assert len(ADVERSARIAL_ROUTING_EXAMPLES) >= 10


def test_routing_dataset_is_structurally_sound():
    assert validate_routing_dataset() == []


def test_routing_metric_rewards_exact_and_penalizes_over_privilege():
    example = next(e for e in ROUTING_EXAMPLES if e.expected_route == "workspace_read")
    exact = routing_metric(example, dspy.Prediction(route="workspace_read"))
    over = routing_metric(example, dspy.Prediction(route="workspace_shell"))

    assert exact.score == 1.0
    assert over.score == 0.35
    assert "more capability" in over.feedback


def test_routing_metric_scores_under_selection_as_failure():
    example = next(e for e in ROUTING_EXAMPLES if e.expected_route == "workspace_write")
    verdict = routing_metric(example, dspy.Prediction(route="direct"))

    assert verdict.score == 0.0
    assert "cannot complete" in verdict.feedback


def test_eval_runner_validates_and_exits_zero_without_a_provider(capsys):
    exit_code = eval_run_main(["--suite", "routing", "--validate"])

    assert exit_code == 0
    assert "validated" in capsys.readouterr().out


def test_eval_runner_reports_structural_failure(capsys, monkeypatch):
    monkeypatch.setattr(
        "evals.agent_tool_routing.CANONICAL_ROUTING_EXAMPLES",
        CANONICAL_ROUTING_EXAMPLES[:2],
    )
    exit_code = eval_run_main(["--suite", "routing", "--validate"])

    assert exit_code == 1
    assert "unsound" in capsys.readouterr().out


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
