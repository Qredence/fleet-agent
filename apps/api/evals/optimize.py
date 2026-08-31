"""Offline self-improvement: ``python -m evals.optimize``.

Evolves the tool router with GEPA over ``dspy.Flex``: the optimizer rewrites
the router's *source* (decomposed predictors plus plain Python) instead of
only tuning instructions, and the evolved code runs inside dspy's Deno
sandbox — never in this process either.

The loop is deliberately manual and offline:

1. Stratified train/val split of the routing eval set (fixed seed).
2. Score the baseline Flex router on the held-out val split.
3. GEPA-compile a candidate (``--auto light|medium|heavy`` budget) with the
   production LM as both candidate and reflection model.
4. Score the candidate on the same held-out split.
5. Gates: the candidate must beat the baseline *and* clear
   ``--min-accuracy``. On failure nothing is written and the exit code is 2.
6. On success, write a versioned artifact directory under
   ``evals/artifacts/``: the router state JSON, the evolved source for human
   review, a report, and a manifest.

Promotion is a separate, explicit step: ``--promote`` copies a chosen
artifact's state to ``evals/artifacts/flex_router_active.json``. Going live
still requires the operator to set ``FLEET_AGENT_ROUTER_STATE`` to that file
and restart the server; nothing here touches the database, the runtime, or
any remote system.

This runner needs a configured provider (``MODAL_*`` or ``FLEET_AGENT_LLM_*``
settings) and a local Deno runtime for the sandboxed interpreter.
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
from typing import Any

import dspy

from app.agent.flex_router import ROUTER_STATE_FORMAT, FlexToolRouter
from evals.agent_tool_routing import (
    ROUTING_EXAMPLES,
    compile_gepa_candidate,
    routing_metric,
    validate_routing_dataset,
)
from evals.mlflow_tracking import log_optimization_run
from evals.run import _resolve_lm

EVALS_DIR = Path(__file__).resolve().parent
ARTIFACTS_DIR = EVALS_DIR / "artifacts"
ACTIVE_POINTER = ARTIFACTS_DIR / "flex_router_active.json"

# Held-out fraction per route, stratified (fixed seed for reproducibility).
_VAL_FRACTION = 0.3
_SPLIT_SEED = 17


def stratified_split(
    examples: list[dspy.Example], *, seed: int = _SPLIT_SEED
) -> tuple[list[dspy.Example], list[dspy.Example]]:
    """Split examples per expected route so every route stays in both halves."""
    rng = random.Random(seed)
    by_route: dict[str, list[dspy.Example]] = {}
    for example in examples:
        by_route.setdefault(str(example.expected_route), []).append(example)

    train: list[dspy.Example] = []
    val: list[dspy.Example] = []
    for route in sorted(by_route):
        group = list(by_route[route])
        rng.shuffle(group)
        held_out = max(1, round(len(group) * _VAL_FRACTION))
        val.extend(group[:held_out])
        train.extend(group[held_out:])
    return train, val


def _score_router(
    router: dspy.Module,
    lm: dspy.BaseLM,
    examples: list[dspy.Example],
) -> tuple[float, list[tuple[str, str, str, float]], float]:
    """Score one router over examples; return (mean, misses, mean latency)."""
    import time

    misses: list[tuple[str, str, str, float]] = []
    scores: list[float] = []
    latencies: list[float] = []
    adapter = dspy.JSONAdapter(use_native_function_calling=True)
    with dspy.context(lm=lm, adapter=adapter):
        for example in examples:
            started = time.perf_counter()
            prediction = router(user_request=str(example.user_request))
            latencies.append(time.perf_counter() - started)
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
    mean = sum(scores) / len(scores) if scores else 0.0
    mean_latency = sum(latencies) / len(latencies) if latencies else 0.0
    return mean, misses, mean_latency


def _miss_summary(misses: list[tuple[str, str, str, float]]) -> str:
    if not misses:
        return "all routes selected exactly (least privilege held)"
    buckets: Counter[str] = Counter()
    for _request, _expected, _actual, score in misses:
        buckets["under-selected" if score == 0.0 else "over-selected"] += 1
    lines = [f"misses: {len(misses)} ({dict(buckets)})"]
    for request, expected, actual, score in misses:
        lines.append(f"  [{score:.2f}] expected={expected} actual={actual}: {request}")
    return "\n".join(lines)


def _extract_module_src(candidate: dspy.Module) -> str:
    """Pull the evolved Flex source out of a compiled candidate module."""
    flex = getattr(candidate, "flex", None)
    src = getattr(flex, "module_src", None) if flex is not None else None
    if not isinstance(src, str) or not src.strip():
        raise RuntimeError(
            "GEPA returned a candidate without an evolved Flex module_src"
        )
    return src


def _write_artifact(
    *,
    module_src: str,
    report: str,
    manifest: dict[str, Any],
    timestamp: str,
) -> Path:
    artifact_dir = ARTIFACTS_DIR / f"flex_router_gepa_{timestamp}"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    (artifact_dir / "state.json").write_text(
        json.dumps(
            {
                "format": ROUTER_STATE_FORMAT,
                "module_src": module_src,
                "lm": None,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "module_src.py").write_text(module_src + "\n", encoding="utf-8")
    (artifact_dir / "report.md").write_text(report, encoding="utf-8")
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return artifact_dir


def _promote(artifact: Path) -> int:
    state_file = artifact / "state.json"
    if not state_file.is_file():
        print(f"artifact {artifact} has no state.json", file=sys.stderr)
        return 1
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(state_file, ACTIVE_POINTER)
    print(f"promoted {state_file} -> {ACTIVE_POINTER}")
    print(
        "to go live: set FLEET_AGENT_ROUTER_STATE="
        f"{ACTIVE_POINTER} and restart the API server"
    )
    return 0


def _latest_artifact() -> Path | None:
    if not ARTIFACTS_DIR.is_dir():
        return None
    candidates = sorted(
        (p for p in ARTIFACTS_DIR.iterdir() if p.is_dir()), key=lambda p: p.name
    )
    return candidates[-1] if candidates else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.optimize",
        description=(
            "Offline GEPA self-improvement for the Flex tool router. "
            "Never touches the database, the runtime, or any remote system."
        ),
    )
    parser.add_argument(
        "--auto",
        choices=["light", "medium", "heavy"],
        default="light",
        help="GEPA budget preset (default: light)",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.9,
        help="minimum held-out mean score for the candidate (default: 0.9)",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="GEPA RNG seed (default: 0)"
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help=(
            "only copy a finished artifact's state to the active pointer "
            "(default: latest); does not run any optimization"
        ),
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=None,
        help="artifact directory to promote (with --promote)",
    )
    args = parser.parse_args(argv)

    if args.promote:
        artifact = args.artifact or _latest_artifact()
        if artifact is None:
            print("no artifacts under evals/artifacts to promote", file=sys.stderr)
            return 1
        return _promote(artifact)

    problems = validate_routing_dataset()
    if problems:
        print("routing dataset is structurally unsound:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if shutil.which("deno") is None:
        print(
            "the Flex sandbox needs a Deno runtime (>= 2.0.0, < 3.0.0) on PATH",
            file=sys.stderr,
        )
        return 1

    lm = _resolve_lm()
    if lm is None:
        print(
            "optimization needs a configured provider (MODAL_* or "
            "FLEET_AGENT_LLM_*); none found",
            file=sys.stderr,
        )
        return 1

    train, val = stratified_split(ROUTING_EXAMPLES)
    print(f"split: {len(train)} train / {len(val)} held-out val examples")

    baseline = FlexToolRouter()
    baseline_mean, baseline_misses, baseline_latency = _score_router(baseline, lm, val)
    print(
        f"baseline held-out mean: {baseline_mean:.3f} "
        f"({baseline_latency:.2f}s per routed request)"
    )
    print(_miss_summary(baseline_misses))

    print(f"compiling GEPA candidate (auto={args.auto}, seed={args.seed}) ...")
    gepa_log_dir = str(
        ARTIFACTS_DIR / "gepa_runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    adapter = dspy.JSONAdapter(use_native_function_calling=True)
    with dspy.context(lm=lm, adapter=adapter):
        candidate = compile_gepa_candidate(
            FlexToolRouter(),
            trainset=train,
            valset=val,
            reflection_lm=lm,  # type: ignore[arg-type]
            auto=args.auto,
            seed=args.seed,
            log_dir=gepa_log_dir,
        )
    module_src = _extract_module_src(candidate)

    candidate_mean, candidate_misses, candidate_latency = _score_router(
        load_candidate(module_src), lm, val
    )
    print(
        f"candidate held-out mean: {candidate_mean:.3f} "
        f"({candidate_latency:.2f}s per routed request)"
    )
    print(_miss_summary(candidate_misses))

    gates_passed = (
        candidate_mean >= baseline_mean and candidate_mean >= args.min_accuracy
    )
    report = _build_report(
        auto=args.auto,
        seed=args.seed,
        train_count=len(train),
        val_count=len(val),
        baseline_mean=baseline_mean,
        candidate_mean=candidate_mean,
        baseline_misses=baseline_misses,
        candidate_misses=candidate_misses,
        baseline_latency=baseline_latency,
        candidate_latency=candidate_latency,
        gates_passed=gates_passed,
        min_accuracy=args.min_accuracy,
        module_src=module_src,
    )
    print(report)

    def _log_mlflow_attempt(outcome: str, artifact_dir: Path | None) -> None:
        """Best-effort MLflow history of every attempt, pass or fail."""
        run_id = log_optimization_run(
            outcome=outcome,
            budget=args.auto,
            seed=args.seed,
            split_seed=_SPLIT_SEED,
            train_examples=len(train),
            val_examples=len(val),
            min_accuracy=args.min_accuracy,
            baseline_mean=baseline_mean,
            candidate_mean=candidate_mean,
            baseline_latency_s=baseline_latency,
            candidate_latency_s=candidate_latency,
            dspy_version=dspy.__version__,
            artifact_dir=artifact_dir,
        )
        if run_id:
            print(f"mlflow: optimization attempt logged as run {run_id}")

    if not gates_passed:
        print(
            "gates failed: candidate did not beat the baseline and/or clear "
            f"--min-accuracy {args.min_accuracy}; nothing written",
            file=sys.stderr,
        )
        _log_mlflow_attempt("gates-failed", None)
        return 2

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest = {
        "format": ROUTER_STATE_FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
        "dspy_version": dspy.__version__,
        "budget": args.auto,
        "seed": args.seed,
        "split_seed": _SPLIT_SEED,
        "train_examples": len(train),
        "val_examples": len(val),
        "baseline_mean": round(baseline_mean, 4),
        "candidate_mean": round(candidate_mean, 4),
        "baseline_mean_latency_s": round(baseline_latency, 3),
        "candidate_mean_latency_s": round(candidate_latency, 3),
        "min_accuracy": args.min_accuracy,
        "gepa_log_dir": gepa_log_dir,
    }
    artifact_dir = _write_artifact(
        module_src=module_src, report=report, manifest=manifest, timestamp=timestamp
    )
    print(f"artifact: {artifact_dir}")
    print(f"promote with: python -m evals.optimize --promote --artifact {artifact_dir}")
    _log_mlflow_attempt("artifact-written", artifact_dir)
    return 0


def load_candidate(module_src: str) -> FlexToolRouter:
    """Rebuild a router from evolved source (LM state is never honored)."""
    router = FlexToolRouter()
    router.flex.load_state({"module_src": module_src, "lm": None})
    return router


def _build_report(
    *,
    auto: str,
    seed: int,
    train_count: int,
    val_count: int,
    baseline_mean: float,
    candidate_mean: float,
    baseline_misses: list[tuple[str, str, str, float]],
    candidate_misses: list[tuple[str, str, str, float]],
    baseline_latency: float,
    candidate_latency: float,
    gates_passed: bool,
    min_accuracy: float,
    module_src: str,
) -> str:
    lines = [
        "# Flex Router GEPA Report",
        "",
        f"- budget: auto={auto}, seed={seed}",
        f"- split: {train_count} train / {val_count} held-out val (stratified)",
        f"- baseline held-out mean: {baseline_mean:.3f} "
        f"({baseline_latency:.2f}s per routed request, Deno sandbox)",
        f"- candidate held-out mean: {candidate_mean:.3f} "
        f"({candidate_latency:.2f}s per routed request, Deno sandbox)",
        f"- gates: candidate >= baseline AND candidate >= {min_accuracy}"
        f" -> {'PASSED' if gates_passed else 'FAILED'}",
        "",
        "## Baseline misses",
        _miss_summary(baseline_misses),
        "",
        "## Candidate misses",
        _miss_summary(candidate_misses),
        "",
        "## Evolved router source (module_src)",
        "Runs only inside dspy's Deno sandbox; output is coerced to a route",
        "downstream, so a degenerate candidate degrades to 'direct'.",
        "",
        "```python",
        module_src,
        "```",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
