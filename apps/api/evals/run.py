"""Offline eval runner: ``python -m evals.run --suite routing``.

Two modes:

* **Validate** (default without provider credentials): run the dataset's
  structural invariants and exit nonzero if the suite is unsound.  This is
  what CI runs.
* **Score** (when a provider is configured via the same ``MODAL_*`` /
  ``FLEET_AGENT_LLM_*`` settings the server uses): route every example with
  the production ``ToolRoutingSignature`` predictor under the production LM
  builder, score it with the least-privilege metric, and print a per-route
  breakdown plus every miss.  Exits nonzero below ``--min-accuracy``.

The runner never talks to the database, never persists anything, and never
optimizes anything; GEPA compilation stays an explicit, separate step
(``compile_gepa_candidate``).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import dspy

from evals.agent_tool_routing import (
    ROUTING_EXAMPLES,
    routing_metric,
    validate_routing_dataset,
)
from evals.mlflow_tracking import log_routing_score


def _resolve_lm() -> dspy.BaseLM | None:
    """Build the production LM from server settings, or None if unconfigured."""
    from app.agent.factory import _build_lm
    from app.settings import get_settings

    settings = get_settings()
    has_credentials = (
        settings.modal_model_id is not None
        or settings.llm_api_key is not None
        or settings.llm_base_url is not None
    )
    if not has_credentials:
        return None
    return _build_lm(settings)


def _score_routing(lm: dspy.BaseLM) -> tuple[float, list[tuple[str, str, str, float]]]:
    """Route every example with the production router; return (mean, misses).

    Scores the real ``ToolRoutingSignature`` (least-privilege instructions,
    the six-route vocabulary) rather than a bare string signature: a bare
    ``"user_request -> route"`` has no vocabulary and lets the model invent
    values like ``web_search``, which measures nothing the app ships.
    """
    from app.agent.routing import ToolRoutingSignature

    router = dspy.Predict(ToolRoutingSignature)
    misses: list[tuple[str, str, str, float]] = []
    scores: list[float] = []
    adapter = dspy.JSONAdapter(use_native_function_calling=True)
    with dspy.context(lm=lm, adapter=adapter):
        for example in ROUTING_EXAMPLES:
            prediction = router(user_request=str(example.user_request))
            verdict = routing_metric(example, prediction)
            score = float(verdict.score)  # type: ignore[attr-defined]
            scores.append(score)
            if score < 1.0:
                misses.append(
                    (
                        str(example.user_request),
                        str(example.expected_route),
                        str(getattr(prediction, "route", "<missing>")),
                        score,
                    )
                )
    return (sum(scores) / len(scores) if scores else 0.0), misses


def _print_routing_report(
    mean: float, misses: list[tuple[str, str, str, float]]
) -> None:
    per_route: Counter[str] = Counter()
    for _request, expected, _actual, score in misses:
        bucket = "under-selected" if score == 0.0 else "over-selected"
        per_route[f"{expected} ({bucket})"] += 1

    print(f"routing suite: {len(ROUTING_EXAMPLES)} examples, mean score {mean:.3f}")
    if per_route:
        print("miss breakdown:")
        for bucket, count in sorted(per_route.items()):
            print(f"  {bucket}: {count}")
        print("misses:")
        for request, expected, actual, score in misses:
            print(f"  [{score:.2f}] expected={expected} actual={actual}: {request}")
    else:
        print("all routes selected exactly (least privilege held)")


def _run_routing(validate_only: bool, min_accuracy: float) -> int:
    problems = validate_routing_dataset()
    if problems:
        print("routing dataset is structurally unsound:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"routing dataset: {len(ROUTING_EXAMPLES)} examples validated")

    if validate_only:
        return 0

    lm = _resolve_lm()
    if lm is None:
        print(
            "no provider configured (MODAL_* or FLEET_AGENT_LLM_*); "
            "dataset validated without scoring"
        )
        return 0

    mean, misses = _score_routing(lm)
    _print_routing_report(mean, misses)
    run_id = log_routing_score(
        mean=mean,
        misses=misses,
        total=len(ROUTING_EXAMPLES),
        min_accuracy=min_accuracy,
    )
    if run_id:
        print(f"mlflow: routing eval logged as run {run_id}")
    return 0 if mean >= min_accuracy else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description="Offline evaluation runner (no database, no persistence).",
    )
    parser.add_argument(
        "--suite",
        choices=["routing"],
        default="routing",
        help="evaluation suite to run",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="only validate the dataset structure; do not call any provider",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.9,
        help="minimum mean score for a scored run to exit 0 (default 0.9)",
    )
    args = parser.parse_args(argv)

    if args.suite == "routing":
        return _run_routing(validate_only=args.validate, min_accuracy=args.min_accuracy)
    parser.error(f"unknown suite {args.suite!r}")


if __name__ == "__main__":
    sys.exit(main())
