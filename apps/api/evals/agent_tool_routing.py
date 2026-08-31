"""Provider-independent routing evaluation set for ReAct/Flex work.

Two populations: canonical examples pin the unambiguous core of each route,
and adversarial examples attack the two failure modes that matter —
over-selection (granting mutation when discussion was enough) and
under-selection (phrasing a mutation as a question or a read).  The metric
rewards least privilege, tolerates over-selection at reduced score, and
scores under-selection as total failure because the run cannot succeed.
"""

from __future__ import annotations

from typing import Any, Literal

import dspy

from app.agent.routing import ROUTES, ToolRoute, coerce_route


def _example(request: str, route: ToolRoute) -> dspy.Example:
    return dspy.Example(user_request=request, expected_route=route).with_inputs(
        "user_request"
    )


CANONICAL_ROUTING_EXAMPLES: list[dspy.Example] = [
    # direct: answerable without external information or action.
    _example("Explain what ReActV2 does.", "direct"),
    _example("Explain how I could run pytest locally.", "direct"),
    _example("Summarize the difference between ReAct and ReActV2.", "direct"),
    _example("Draft a haiku about autonomous agents.", "direct"),
    _example("Translate 'least privilege' into plain French.", "direct"),
    # research: read-only external evidence.
    _example("What time is it in UTC?", "research"),
    _example("Search our documentation for AG-UI state sync.", "research"),
    _example("Look up how FastAPI middleware ordering works.", "research"),
    _example("Find recent articles about DSPy streaming support.", "research"),
    _example("Fetch the pydantic docs page about model_config.", "research"),
    # artifact: a managed, persisted report is explicitly requested.
    _example("Write a deployment report artifact summarizing the release.", "artifact"),
    _example("Create a managed report of today's findings.", "artifact"),
    _example("Produce a persisted report artifact titled 'Sprint Review'.", "artifact"),
    # workspace_read: repository inspection without modification.
    _example("Find where FleetAgent is defined in this repository.", "workspace_read"),
    _example("Read apps/api/app/agent/program.py and explain it.", "workspace_read"),
    _example("Search the repository for usages of coerce_route.", "workspace_read"),
    _example("List the files under apps/api/tests.", "workspace_read"),
    _example("Show me the first 40 lines of pyproject.toml.", "workspace_read"),
    # workspace_write: repository files must change.
    _example("Change the FleetAgent docstring to mention routing.", "workspace_write"),
    _example(
        "Create a new file scratch/notes.md with today's date.", "workspace_write"
    ),
    _example(
        "Fix the typo in README.md: 'recieve' should be 'receive'.",
        "workspace_write",
    ),
    _example("Remove the stale draft section from docs/plan.md.", "workspace_write"),
    # workspace_shell: command execution is explicitly required.
    _example("Run the backend tests and tell me which ones fail.", "workspace_shell"),
    _example(
        "Start the linter over apps/api and report violations.", "workspace_shell"
    ),
    _example("Run the e2e fixtures script end to end.", "workspace_shell"),
    _example("Install the package dependencies with uv sync.", "workspace_shell"),
    _example("Count the repository's Python lines with wc.", "workspace_shell"),
]

ADVERSARIAL_ROUTING_EXAMPLES: list[dspy.Example] = [
    # Over-selection traps: discussion, not action.
    _example(
        "Can you tell me what the bash tool does? Explain only, run nothing.",
        "direct",
    ),
    _example(
        "I'm curious how one would safely edit a file — walk me through it.",
        "direct",
    ),
    _example("If I wanted to run pytest someday, what would that look like?", "direct"),
    _example(
        "Don't modify anything, just look around: where is routing.py?",
        "workspace_read",
    ),
    _example("Read the failing tests but do not touch them.", "workspace_read"),
    _example("Search the web for how to delete a file, then tell me.", "research"),
    _example("What time is it in Tokyo right now?", "research"),
    _example("grep the codebase for TODO markers; no changes.", "workspace_read"),
    _example("Run a web search for 'uv pytest' and cite the sources.", "research"),
    # Under-selection traps: polite or small phrasing still needs mutation.
    _example(
        "Quickly fix the typo in that file, it's just one word.", "workspace_write"
    ),
    _example(
        "Just a tiny cleanup: drop the commented-out line in utils.py.",
        "workspace_write",
    ),
    _example("Empty out notes.txt so it is completely blank.", "workspace_write"),
    # artifact vs write disambiguation.
    _example("Write a report about the migration.", "artifact"),
    _example("Create a file reports/migration.md with a summary.", "workspace_write"),
    # Deletion needs the shell: there is no delete tool.
    _example("Remove the generated file scratch/old-notes.md.", "workspace_shell"),
    # Compound requests need the union of capabilities.
    _example(
        "Make the failing test pass by adjusting the fixture file.",
        "workspace_write",
    ),
    _example(
        "Get the repo green again: run the suite and patch whatever breaks.",
        "workspace_shell",
    ),
    _example(
        "Run the test suite... actually, first just show me which test files exist.",
        "workspace_read",
    ),
]

ROUTING_EXAMPLES: list[dspy.Example] = [
    *CANONICAL_ROUTING_EXAMPLES,
    *ADVERSARIAL_ROUTING_EXAMPLES,
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
    seed: int | None = 0,
    log_dir: str | None = None,
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
        seed=seed,
        log_dir=log_dir,
    )
    return optimizer.compile(
        program,
        trainset=trainset or ROUTING_EXAMPLES,
        valset=valset or ROUTING_EXAMPLES,
    )


def public_routes() -> tuple[ToolRoute, ...]:
    """Expose the route vocabulary to offline evaluation/reporting only."""
    return ROUTES


def validate_routing_dataset() -> list[str]:
    """Structural invariants of the evaluation set (no LM required).

    Returns a list of violations; an empty list means the dataset is sound.
    Pinned by CI so the eval suite cannot silently rot.
    """
    problems: list[str] = []
    seen_requests: dict[str, str] = {}

    for name, examples in (
        ("canonical", CANONICAL_ROUTING_EXAMPLES),
        ("adversarial", ADVERSARIAL_ROUTING_EXAMPLES),
    ):
        if not examples:
            problems.append(f"{name} routing set is empty")
        for example in examples:
            request = str(example.user_request)
            duplicate = seen_requests.get(request)
            if duplicate is not None:
                problems.append(
                    f"duplicate request {request!r} in {duplicate} and {name}"
                )
            seen_requests[request] = name
            route = example.expected_route
            if route not in ROUTES:
                problems.append(f"unknown route {route!r} for {request!r}")

    covered = {example.expected_route for example in ROUTING_EXAMPLES}
    for route in ROUTES:
        if route not in covered:
            problems.append(f"no example covers route {route!r}")

    canonical_routes = {e.expected_route for e in CANONICAL_ROUTING_EXAMPLES}
    if canonical_routes != set(ROUTES):
        problems.append(
            "canonical set must cover every route (it pins the unambiguous core)"
        )
    return problems
