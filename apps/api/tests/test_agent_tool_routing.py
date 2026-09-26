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
from evals.run import _print_routing_report
from evals.run import main as eval_run_main
from evals.scoring import RoutingScore
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


def test_routing_report_warns_about_raised_calls(capsys):
    """A provider error has to be visible next to the mean.

    ``dspy.Evaluate`` scores a raised example 0 and continues, so the mean on
    its own cannot tell a broken gateway from a wrong route.
    """
    _print_routing_report(
        RoutingScore(
            mean=0.5,
            misses=[("a request", "direct", "<missing>", 0.0)],
            mean_latency_s=0.1,
            failures=2,
        )
    )

    out = capsys.readouterr().out
    assert "mean score 0.500" in out
    assert "WARNING: 2 of" in out
    assert "routing misses" in out


def test_routing_report_stays_quiet_when_nothing_raised(capsys):
    _print_routing_report(
        RoutingScore(mean=1.0, misses=[], mean_latency_s=0.1, failures=0)
    )

    assert "WARNING" not in capsys.readouterr().out


def test_routing_metric_satisfies_gepa_metric_contract():
    # dspy 3.4.0's GEPA binds its metric with five positional arguments
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


def test_coerce_edge_cases_fixtures_match_live_coerce():
    from evals.agent_tool_routing import validate_coerce_edge_cases

    assert validate_coerce_edge_cases() == []


def test_eval_runner_seeded_exits_zero_without_a_provider(capsys):
    exit_code = eval_run_main(["--suite", "routing", "--seeded"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "coerce fixtures:" in out
    assert "seeded router:" in out
    assert "all seeded routes exact" in out


def test_score_seeded_router_is_exact_on_canonical_gold():
    from evals.agent_tool_routing import (
        CANONICAL_ROUTING_EXAMPLES,
        score_seeded_router,
    )

    mean, misses, failures = score_seeded_router()
    assert failures == 0
    assert misses == []
    assert mean == 1.0
    assert len(CANONICAL_ROUTING_EXAMPLES) >= len(
        {
            "direct",
            "research",
            "artifact",
            "workspace_read",
            "workspace_write",
            "workspace_shell",
        }
    )
