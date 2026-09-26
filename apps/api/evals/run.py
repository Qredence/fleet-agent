"""Offline eval runner: ``python -m evals.run --suite routing``.

Two modes:

* **Validate** (default without provider credentials): run the dataset's
  structural invariants and exit nonzero if the suite is unsound.  This is
  what CI runs.
* **Seeded** (``--seeded``): provider-free thin eval — coerce edge fixtures
  plus a ScriptedLM ``Predict`` pass over the canonical set. Runs fully on
  local SSD; no live API.
* **Score** (when a provider is configured via the same ``MODAL_*`` /
  ``FLEET_AGENT_LLM_*`` settings the server uses): route every example with
  the production ``ToolRoutingSignature`` predictor under the production LM
  builder, score it with the least-privilege metric, and print a per-route
  breakdown plus every miss.  Exits nonzero below ``--min-accuracy``.

The runner never talks to the database, never persists anything, and never
optimizes anything; GEPA compilation stays an explicit, separate step
(``compile_gepa_candidate``).

Three MLflow steps hang off it. The dataset is registered (and a scored run is
tagged with its version and digest) so a score can be traced back to the exact
eval set behind it; ``--register-dataset`` does that without a provider.
``--mlflow-eval`` additionally scores the same dataset through
``mlflow.genai.evaluate`` with the deterministic scorers, and ``--judge-model``
adds the opt-in LLM judge. Every MLflow step is best-effort: losing the store
warns and continues, it never changes the exit code.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

import dspy

from evals.agent_tool_routing import (
    CANONICAL_ROUTING_EXAMPLES,
    COERCE_EDGE_CASES,
    ROUTING_EXAMPLES,
    score_seeded_router,
    validate_coerce_edge_cases,
    validate_routing_dataset,
)
from evals.mlflow_tracking import (
    ROUTING_EVAL_EXPERIMENT,
    log_routing_score,
    use_experiment,
)
from evals.scoring import RoutingScore, score_router

logger = logging.getLogger(__name__)


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


def _score_routing(lm: dspy.BaseLM) -> RoutingScore:
    """Route every example with the production router.

    Scores the real ``ToolRoutingSignature`` (least-privilege instructions,
    the six-route vocabulary) rather than a bare string signature: a bare
    ``"user_request -> route"`` has no vocabulary and lets the model invent
    values like ``web_search``, which measures nothing the app ships. The
    scoring loop itself is shared with the optimizer (``evals.scoring``).
    """
    from app.agent.routing import ToolRoutingSignature

    router = dspy.Predict(ToolRoutingSignature)
    return score_router(router, lm, ROUTING_EXAMPLES)


def _register_dataset() -> dict[str, Any] | None:
    """Build/refresh the versioned MLflow dataset and describe it for tagging.

    Best effort: the routing score is the product, MLflow is observability, so
    an unreachable store warns and returns None instead of failing the run.
    """
    try:
        from evals.datasets import build_dataset, dataset_reference

        reference = dataset_reference(build_dataset())
    except Exception:  # noqa: BLE001 — observability must never break the run
        print("WARNING: could not register the MLflow dataset; continuing untagged")
        logger.warning("MLflow dataset registration failed", exc_info=True)
        return None
    print(
        f"mlflow dataset: {reference['dataset_name']} "
        f"v{reference['dataset_version']} ({reference['dataset_digest']})"
    )
    return reference


def _mlflow_predict_fn(lm: dspy.BaseLM) -> Callable[..., dict[str, Any]]:
    """Adapt the production router to the callable ``mlflow.genai.evaluate`` wants.

    It passes each row's ``inputs`` as keyword arguments and feeds the returned
    mapping to the scorers, so the router runs through the same predictor and
    adapter the app ships and reports its own latency for the latency budget.
    """
    from app.agent.routing import ToolRoutingSignature

    router = dspy.Predict(ToolRoutingSignature)
    adapter = dspy.JSONAdapter(use_native_function_calling=True)

    def predict(**inputs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        with dspy.context(lm=lm, adapter=adapter):
            prediction = router(**inputs)
        return {
            "route": str(getattr(prediction, "route", "")),
            "latency_s": time.perf_counter() - started,
        }

    return predict


def _run_mlflow_eval(lm: dspy.BaseLM, judge_model: str | None) -> None:
    """Score the versioned dataset through ``mlflow.genai.evaluate``.

    The genai run carries per-row assessments (the deterministic scorers, plus
    the judge when one is named) that the dspy mean cannot show. Selecting the
    experiment first keeps the run and its traces beside the dataset instead of
    in the store's Default experiment.
    """
    import mlflow

    from evals.datasets import build_dataset
    from evals.scorers import answer_quality_judge, deterministic_scorers

    scorers = deterministic_scorers()
    if judge_model:
        scorers.append(answer_quality_judge(judge_model))
        print(f"mlflow judge: {judge_model} (opt-in)")
    use_experiment(ROUTING_EVAL_EXPERIMENT)
    result = mlflow.genai.evaluate(
        data=build_dataset(), scorers=scorers, predict_fn=_mlflow_predict_fn(lm)
    )
    print("mlflow genai metrics:")
    for name, value in sorted(result.metrics.items()):
        print(f"  {name}: {value:.3f}")


def _print_routing_report(scored: RoutingScore) -> None:
    per_route: Counter[str] = Counter()
    for _request, expected, _actual, score in scored.misses:
        bucket = "under-selected" if score == 0.0 else "over-selected"
        per_route[f"{expected} ({bucket})"] += 1

    total = len(ROUTING_EXAMPLES)
    print(f"routing suite: {total} examples, mean score {scored.mean:.3f}")
    if scored.failures:
        # dspy.Evaluate scores a raised example 0 and keeps going, so a gateway
        # error looks like a wrong route in the mean. Say which it was.
        print(
            f"WARNING: {scored.failures} of {total} routing calls raised "
            "(scored 0 by dspy.Evaluate); the mean mixes provider errors with "
            "routing misses"
        )
    if per_route:
        print("miss breakdown:")
        for bucket, count in sorted(per_route.items()):
            print(f"  {bucket}: {count}")
        print("misses:")
        for request, expected, actual, score in scored.misses:
            print(f"  [{score:.2f}] expected={expected} actual={actual}: {request}")
    else:
        print("all routes selected exactly (least privilege held)")


def _run_seeded_routing(min_accuracy: float) -> int:
    """Provider-free thin eval: coerce fixtures + ScriptedLM Predict path.

    Runs entirely on the SSD with no live API. Exit 0 when coerce fixtures
    match and the seeded router mean clears ``min_accuracy`` (default 1.0
    for exact gold responses).
    """
    problems = validate_routing_dataset()
    problems.extend(validate_coerce_edge_cases())
    if problems:
        print("seeded routing eval is unsound:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(
        f"coerce fixtures: {len(COERCE_EDGE_CASES)} cases ok; "
        f"routing dataset: {len(ROUTING_EXAMPLES)} examples validated"
    )

    mean, misses, failures = score_seeded_router()
    total = len(CANONICAL_ROUTING_EXAMPLES)
    print(f"seeded router: {total} canonical examples, mean score {mean:.3f}")
    if failures:
        print(
            f"WARNING: {failures} of {total} seeded calls raised "
            "(scored 0 by dspy.Evaluate)"
        )
    if misses:
        print("seeded misses:")
        for request, expected, actual, score in misses:
            print(f"  [{score:.2f}] expected={expected} actual={actual}: {request}")
    else:
        print("all seeded routes exact (Predict + coerce held)")
    return 0 if mean >= min_accuracy and not failures else 2


def _run_routing(
    validate_only: bool,
    min_accuracy: float,
    *,
    register_dataset: bool = False,
    mlflow_eval: bool = False,
    judge_model: str | None = None,
) -> int:
    problems = validate_routing_dataset()
    if problems:
        print("routing dataset is structurally unsound:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"routing dataset: {len(ROUTING_EXAMPLES)} examples validated")

    if validate_only:
        if not register_dataset:
            return 0
        return 0 if _register_dataset() else 1

    lm = _resolve_lm()
    if lm is None:
        print(
            "no provider configured (MODAL_* or FLEET_AGENT_LLM_*); "
            "dataset validated without scoring"
        )
        if not register_dataset:
            return 0
        return 0 if _register_dataset() else 1

    # Registered before scoring so the run is tagged with the eval set it
    # measured; the build is idempotent by content digest.
    reference = _register_dataset()
    scored = _score_routing(lm)
    _print_routing_report(scored)
    run_id = log_routing_score(
        mean=scored.mean,
        misses=scored.misses,
        total=len(ROUTING_EXAMPLES),
        min_accuracy=min_accuracy,
        failures=scored.failures,
        **(reference or {}),
    )
    if run_id:
        print(f"mlflow: routing eval logged as run {run_id}")
    if mlflow_eval:
        _run_mlflow_eval(lm, judge_model)
    return 0 if scored.mean >= min_accuracy else 2


def _run_code(validate_only: bool, min_accuracy: float) -> int:
    """Run the code-agent fixture task end to end."""
    from evals.code import TASK, run_code_task, validate_code_fixture

    problems = validate_code_fixture()
    if problems:
        print("code fixture is unsound:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"code fixture: {TASK} (suite fails pre-fix)")

    if validate_only:
        return 0

    lm = _resolve_lm()
    if lm is None:
        print(
            "no provider configured (MODAL_* or FLEET_AGENT_LLM_*); "
            "fixture validated without running the agent"
        )
        return 0
    score = run_code_task(lm=lm)
    print(f"code suite: {'PASS' if score.passed else 'FAIL'}")
    print(score.summary)
    return 0 if (score.passed and 1.0 >= min_accuracy) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description="Offline evaluation runner (no database, no persistence).",
    )
    parser.add_argument(
        "--suite",
        choices=["routing", "code"],
        default="routing",
        help="evaluation suite to run",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="only validate the dataset structure; do not call any provider",
    )
    parser.add_argument(
        "--seeded",
        action="store_true",
        help=(
            "provider-free thin eval: coerce edge fixtures + ScriptedLM "
            "Predict over the canonical routing set"
        ),
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=None,
        help="minimum mean score to exit 0 (default 0.9; 1.0 with --seeded)",
    )
    parser.add_argument(
        "--register-dataset",
        action="store_true",
        help="write/refresh the versioned MLflow dataset (no provider needed)",
    )
    parser.add_argument(
        "--mlflow-eval",
        action="store_true",
        help="also score through mlflow.genai.evaluate with the scorers",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        metavar="MODEL",
        help="opt-in LLM judge for --mlflow-eval, e.g. openai:/gpt-4o-mini",
    )
    args = parser.parse_args(argv)

    if args.judge_model and not args.mlflow_eval:
        parser.error("--judge-model requires --mlflow-eval")
    if args.seeded and args.suite != "routing":
        parser.error("--seeded only applies to --suite routing")
    if args.seeded and args.validate:
        parser.error("--seeded and --validate are mutually exclusive")
    if args.suite == "routing":
        if args.seeded:
            if args.register_dataset or args.mlflow_eval:
                parser.error(
                    "--seeded cannot be combined with "
                    "--register-dataset or --mlflow-eval"
                )
            # Seeded path is exact gold responses; default floor is 1.0 unless
            # the caller overrides --min-accuracy.
            min_accuracy = 1.0 if args.min_accuracy is None else args.min_accuracy
            return _run_seeded_routing(min_accuracy)
        return _run_routing(
            args.validate,
            0.9 if args.min_accuracy is None else args.min_accuracy,
            register_dataset=args.register_dataset,
            mlflow_eval=args.mlflow_eval,
            judge_model=args.judge_model,
        )
    if args.suite == "code":
        return _run_code(
            args.validate, 0.9 if args.min_accuracy is None else args.min_accuracy
        )
    parser.error(f"unknown suite {args.suite!r}")


if __name__ == "__main__":
    sys.exit(main())
