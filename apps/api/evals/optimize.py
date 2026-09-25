"""Offline self-improvement: ``python -m evals.optimize``.

GEPA rewrites the capability router's instructions against the labelled routing
set. The router is the one component with both a labelled dataset and a
deterministic metric, so it is the honest optimization target: the run costs one
LM call per example instead of a full agent turn.

The loop is manual and offline, and it never touches the database or the runtime:

1. Stratified train/test split of the routing set (fixed seed).
2. Score the baseline router on the held-out test split.
3. GEPA-compile a candidate over the TRAIN split only.
4. Score the candidate on the same held-out test split.
5. Gates: the candidate must beat the baseline AND clear ``--min-accuracy``.
   On failure nothing is written and the exit code is 2.
6. On success, write a versioned artifact directory holding the promoted
   instructions, a report, and a manifest.

Promotion is a separate, explicit step (``--promote``). Going live still requires
the operator to point ``FLEET_AGENT_ROUTER_STATE_PATH`` at the artifact and
restart the server, which the startup log confirms.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import dspy

from app.agent.routing import (
    ROUTER_STATE_FORMAT,
    ToolRoutingSignature,
    coerce_route,
)
from evals.agent_tool_routing import (
    ROUTING_EXAMPLES,
    compile_gepa_candidate,
    validate_routing_dataset,
)
from evals.mlflow_tracking import log_optimization_run
from evals.run import _resolve_lm
from evals.scoring import RoutingScore, score_router

EVALS_DIR = Path(__file__).resolve().parent
ARTIFACTS_DIR = EVALS_DIR / "artifacts"
ACTIVE_POINTER = ARTIFACTS_DIR / "router_active.json"

# Held-out fraction per route, stratified (fixed seed for reproducibility).
_VAL_FRACTION = 0.3


class RouterProgram(dspy.Module):  # type: ignore[misc]  # dspy is untyped
    """The capability router alone, with the live program's predictor path.

    Named ``router`` so a GEPA write-back targets the same predictor the
    production program builds, which is what makes the promoted instructions
    apply unchanged at runtime.
    """

    def __init__(self) -> None:
        super().__init__()
        self.router = dspy.Predict(ToolRoutingSignature)

    def forward(self, user_request: str) -> dspy.Prediction:
        return self.router(user_request=user_request)


def _route_of(example: dspy.Example) -> str:
    return coerce_route(getattr(example, "expected_route", None))


def split_examples(
    examples: list[dspy.Example], *, val_fraction: float = _VAL_FRACTION, seed: int = 17
) -> tuple[list[dspy.Example], list[dspy.Example]]:
    """Return a stratified ``(train, held_out)`` split.

    Stratified by route so a small held-out set still covers every profile;
    without that, a route with two examples could vanish from the test split.
    """
    by_route: dict[str, list[dspy.Example]] = {}
    for example in examples:
        by_route.setdefault(_route_of(example), []).append(example)

    rng = random.Random(seed)
    train: list[dspy.Example] = []
    held_out: list[dspy.Example] = []
    for route in sorted(by_route):
        group = sorted(by_route[route], key=lambda item: item.user_request)
        rng.shuffle(group)
        take = max(1, round(len(group) * val_fraction))
        held_out.extend(group[:take])
        train.extend(group[take:])
    rng.shuffle(train)
    rng.shuffle(held_out)
    return train, held_out


def _instructions(program: dspy.Module) -> str:
    return str(getattr(program.router.signature, "instructions", "") or "")


def _report(
    *,
    outcome: str,
    baseline: RoutingScore,
    candidate: RoutingScore,
    min_accuracy: float,
    budget: str,
    split: tuple[int, int],
    seed: int,
) -> str:
    lines = [
        "# Router GEPA report",
        "",
        f"- outcome: **{outcome}**",
        f"- budget: auto={budget}, seed={seed}",
        f"- split: {split[0]} train / {split[1]} held out (stratified)",
        f"- baseline held-out mean: {baseline.mean:.3f}"
        f" ({baseline.failures} raised calls)",
        f"- candidate held-out mean: {candidate.mean:.3f}"
        f" ({candidate.failures} raised calls)",
        f"- gate: candidate > baseline AND candidate >= {min_accuracy:.2f}",
        "",
        "## Baseline misses",
    ]
    lines += [f"- {miss}" for miss in baseline.misses] or ["- (none)"]
    lines += ["", "## Candidate misses"]
    lines += [f"- {miss}" for miss in candidate.misses] or ["- (none)"]
    return "\n".join(lines) + "\n"


def _miss_lines(score: RoutingScore) -> list[str]:
    return [str(miss) for miss in score.misses]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto", choices=("light", "medium", "heavy"), default="light")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--split-seed", type=int, default=17)
    parser.add_argument("--min-accuracy", type=float, default=0.9)
    parser.add_argument(
        "--promote",
        action="store_true",
        help="copy a passing candidate's state to the active pointer",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="check the dataset and exit without needing a provider",
    )
    parser.add_argument("--log-dir", default=None, help="GEPA trial log directory")
    args = parser.parse_args(argv)

    problems = validate_routing_dataset()
    if problems:
        for problem in problems:
            print(f"dataset problem: {problem}", file=sys.stderr)
        return 2
    if args.validate:
        print(f"dataset OK: {len(ROUTING_EXAMPLES)} examples")
        return 0

    lm = _resolve_lm()
    if lm is None:
        print(
            "no provider configured: set MODAL_* or FLEET_AGENT_LLM_* to run "
            "optimization (use --validate for an offline dataset check)",
            file=sys.stderr,
        )
        return 2

    train, held_out = split_examples(ROUTING_EXAMPLES, seed=args.split_seed)
    try:
        baseline_program = RouterProgram()
        baseline = score_router(baseline_program.router, lm, held_out)
        print(
            f"baseline held-out mean {baseline.mean:.3f} over {len(held_out)} examples"
        )

        candidate_program = compile_gepa_candidate(
            RouterProgram(),
            # GEPA selects its Pareto candidates on the TRAIN split only. Handing it
            # the held-out set would tune the candidate against the very examples the
            # gate is measured on, which makes the pass meaningless.
            trainset=train,
            valset=train,
            reflection_lm=lm,
            auto=args.auto,
            seed=args.seed,
            log_dir=args.log_dir,
        )
        candidate = score_router(candidate_program.router, lm, held_out)
        print(
            f"candidate held-out mean {candidate.mean:.3f} "
            f"over {len(held_out)} examples"
        )
    except Exception as error:  # noqa: BLE001 - provider failures are expected operations
        print(f"optimization failed: {error}", file=sys.stderr)
        log_optimization_run(
            outcome="error",
            budget=args.auto,
            seed=args.seed,
            split_seed=args.split_seed,
            train_examples=len(train),
            val_examples=len(held_out),
            min_accuracy=args.min_accuracy,
            baseline_mean=0.0,
            candidate_mean=0.0,
            baseline_latency_s=0.0,
            candidate_latency_s=0.0,
            dspy_version=dspy.__version__,
        )
        return 2

    # Byte-identical instructions mean GEPA converged without rewriting anything:
    # there is no improvement to promote, even if the numbers differ (a depressed
    # baseline from transient provider failures would otherwise pass a "better"
    # candidate that changed nothing).
    baseline_text = _instructions(baseline_program).strip()
    candidate_text = _instructions(candidate_program).strip()
    if candidate_text == baseline_text:
        print(
            "rejected: GEPA converged without rewriting the router instructions",
            file=sys.stderr,
        )
        log_optimization_run(
            outcome="gates-failed",
            budget=args.auto,
            seed=args.seed,
            split_seed=args.split_seed,
            train_examples=len(train),
            val_examples=len(held_out),
            min_accuracy=args.min_accuracy,
            baseline_mean=baseline.mean,
            candidate_mean=candidate.mean,
            baseline_latency_s=baseline.mean_latency_s,
            candidate_latency_s=candidate.mean_latency_s,
            dspy_version=dspy.__version__,
            baseline_failures=baseline.failures,
            candidate_failures=candidate.failures,
        )
        return 2

    passed = candidate.mean > baseline.mean and candidate.mean >= args.min_accuracy
    outcome = "artifact-written" if passed else "gates-failed"
    train_counts = Counter(_route_of(example) for example in train)

    artifact_dir: Path | None = None
    if passed:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        artifact_dir = ARTIFACTS_DIR / f"router_gepa_{stamp}"
        artifact_dir.mkdir(parents=True, exist_ok=False)
        state = {
            "format": ROUTER_STATE_FORMAT,
            "created_at": datetime.now(UTC).isoformat(),
            "dspy_version": dspy.__version__,
            "router_instructions": _instructions(candidate_program),
            "metrics": {
                "baseline_mean": baseline.mean,
                "candidate_mean": candidate.mean,
                "min_accuracy": args.min_accuracy,
            },
        }
        (artifact_dir / "router_state.json").write_text(
            json.dumps(state, indent=2) + "\n", encoding="utf-8"
        )
        (artifact_dir / "report.md").write_text(
            _report(
                outcome=outcome,
                baseline=baseline,
                candidate=candidate,
                min_accuracy=args.min_accuracy,
                budget=args.auto,
                split=(len(train), len(held_out)),
                seed=args.seed,
            ),
            encoding="utf-8",
        )
        (artifact_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "format": ROUTER_STATE_FORMAT,
                    "created_at": state["created_at"],
                    "dspy_version": dspy.__version__,
                    "budget": args.auto,
                    "seed": args.seed,
                    "split_seed": args.split_seed,
                    "train_examples": len(train),
                    "val_examples": len(held_out),
                    "train_routes": dict(sorted(train_counts.items())),
                    "baseline_mean": baseline.mean,
                    "candidate_mean": candidate.mean,
                    "baseline_failures": baseline.failures,
                    "candidate_failures": candidate.failures,
                    "min_accuracy": args.min_accuracy,
                    "baseline_misses": _miss_lines(baseline),
                    "candidate_misses": _miss_lines(candidate),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    log_optimization_run(
        outcome=outcome,
        budget=args.auto,
        seed=args.seed,
        split_seed=args.split_seed,
        train_examples=len(train),
        val_examples=len(held_out),
        min_accuracy=args.min_accuracy,
        baseline_mean=baseline.mean,
        candidate_mean=candidate.mean,
        baseline_latency_s=baseline.mean_latency_s,
        candidate_latency_s=candidate.mean_latency_s,
        dspy_version=dspy.__version__,
        baseline_failures=baseline.failures,
        candidate_failures=candidate.failures,
        artifact_dir=artifact_dir,
    )

    if not passed:
        print(
            f"rejected: candidate {candidate.mean:.3f} did not clear "
            f"baseline {baseline.mean:.3f} and min-accuracy {args.min_accuracy:.2f}",
            file=sys.stderr,
        )
        return 2

    assert artifact_dir is not None
    print(f"wrote {artifact_dir}")
    if args.promote:
        ACTIVE_POINTER.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(artifact_dir / "router_state.json", ACTIVE_POINTER)
        print(
            f"promoted to {ACTIVE_POINTER}\n"
            f"go live: FLEET_AGENT_ROUTER_STATE_PATH={ACTIVE_POINTER}, then restart"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
