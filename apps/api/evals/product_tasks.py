"""Expanded compound/follow-up routing corpus, separate from task execution tests.

Run explicitly with ``uv run python -m evals.product_tasks``.
Development and final holdout groups remain separate.
No optimizer is invoked here.
"""

import hashlib
import json
from pathlib import Path

import dspy

from app.agent.routing import ToolRoutingSignature
from evals.agent_tool_routing import routing_metric
from evals.run import _resolve_lm


def case(
    request: str, route: str, output: str, context: str, group: str
) -> dspy.Example:
    return dspy.Example(
        user_request=request,
        conversation_context=context,
        expected_route=route,
        expected_output_intent=output,
        group_id=group,
    ).with_inputs("user_request", "conversation_context")


PRODUCT_ROUTING_EXAMPLES = [
    case(
        "Inspect README.md and produce a downloadable report",
        "workspace_read",
        "managed_report",
        "[]",
        "readme-report",
    ),
    case(
        "Make that README analysis a report",
        "direct",
        "managed_report",
        json.dumps(
            [
                {
                    "user_request": "Inspect README.md",
                    "answer": "README documents FastAPI and React.",
                }
            ]
        ),
        "readme-report",
    ),
    case(
        "Inspect package.json and report the available scripts",
        "workspace_read",
        "none",
        "[]",
        "package-scripts",
    ),
    case(
        "Export that script analysis as a downloadable report",
        "direct",
        "managed_report",
        json.dumps(
            [
                {
                    "user_request": "Inspect package.json",
                    "answer": "Scripts are build and test.",
                }
            ]
        ),
        "package-scripts",
    ),
    case(
        "Search the documentation for state replay and create a report artifact",
        "artifact",
        "managed_report",
        "[]",
        "replay-report",
    ),
    case(
        "Make the state replay findings a report",
        "direct",
        "managed_report",
        json.dumps(
            [
                {
                    "user_request": "Search the replay docs",
                    "answer": "Replay restores the selected branch.",
                }
            ]
        ),
        "replay-report",
    ),
    case(
        "Explain managed report exports without creating anything",
        "direct",
        "none",
        "[]",
        "explanation",
    ),
    case(
        "Update notes.md, then produce a downloadable summary report",
        "workspace_write",
        "managed_report",
        "[]",
        "notes-update",
    ),
]


PRODUCT_HOLDOUT_EXAMPLES = [
    case(
        "Read SECURITY.md and export a downloadable Markdown report",
        "workspace_read",
        "managed_report",
        "[]",
        "security-export",
    ),
    case(
        "Turn your security analysis into a downloadable report",
        "direct",
        "managed_report",
        json.dumps(
            [
                {
                    "user_request": "Read SECURITY.md",
                    "answer": "SECURITY.md defines a single local owner.",
                }
            ]
        ),
        "security-export",
    ),
    case(
        "Inspect LICENSE and tell me its license type",
        "workspace_read",
        "none",
        "[]",
        "license-inspection",
    ),
    case(
        "Save that license explanation as a managed report",
        "direct",
        "managed_report",
        json.dumps(
            [
                {
                    "user_request": "Inspect LICENSE",
                    "answer": "LICENSE specifies Apache-2.0.",
                }
            ]
        ),
        "license-inspection",
    ),
    case(
        "Search current PostgreSQL docs and generate a downloadable report artifact",
        "artifact",
        "managed_report",
        "[]",
        "postgres-docs",
    ),
    case(
        "Export your PostgreSQL documentation findings to a report",
        "direct",
        "managed_report",
        json.dumps(
            [
                {
                    "user_request": "Search PostgreSQL docs",
                    "answer": "Transactions commit atomically.",
                }
            ]
        ),
        "postgres-docs",
    ),
    case(
        "Describe how an artifact report works, without creating one",
        "direct",
        "none",
        "[]",
        "artifact-concept",
    ),
    case(
        "Fix the greeting text in greeting.py and export a summary report",
        "workspace_write",
        "managed_report",
        "[]",
        "greeting-edit",
    ),
]


def main() -> int:
    lm = _resolve_lm()
    if lm is None:
        print("No provider configured; product routing scoring was not executed.")
        return 2
    router = dspy.Predict(ToolRoutingSignature)
    rows = []
    with dspy.context(lm=lm, adapter=dspy.JSONAdapter()):
        for example in [*PRODUCT_ROUTING_EXAMPLES, *PRODUCT_HOLDOUT_EXAMPLES]:
            try:
                prediction = router(**example.inputs())
                verdict = routing_metric(example, prediction)
                rows.append(
                    {
                        "split": "development"
                        if example in PRODUCT_ROUTING_EXAMPLES
                        else "holdout",
                        "group_id": example.group_id,
                        "request": example.user_request,
                        "expected_route": example.expected_route,
                        "actual_route": prediction.route,
                        "route_exact": verdict.exact_match,
                        "intent_exact": prediction.output_intent
                        == example.expected_output_intent,
                        "capability_sufficiency": verdict.capability_sufficiency,
                        "invalid_output": verdict.invalid_output_rate,
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "split": "development"
                        if example in PRODUCT_ROUTING_EXAMPLES
                        else "holdout",
                        "group_id": example.group_id,
                        "route_exact": False,
                        "intent_exact": False,
                        "capability_sufficiency": False,
                        "invalid_output": True,
                        "failure_type": type(exc).__name__,
                    }
                )
    report = {
        "corpus_version": "product-routing@2",
        "examples": len(rows),
        "model_identity": str(lm.model),
        "dspy_version": dspy.__version__,
        "program_fingerprint": hashlib.sha256(
            ToolRoutingSignature.instructions.encode()
        ).hexdigest(),
        "task_success": "Measured independently by deterministic execution tests",
        "route_exact": sum(bool(row["route_exact"]) for row in rows) / len(rows),
        "intent_exact": sum(bool(row["intent_exact"]) for row in rows) / len(rows),
        "splits": {
            split: {
                "examples": sum(row["split"] == split for row in rows),
                "decision_accuracy": sum(
                    row["route_exact"] and row["intent_exact"]
                    for row in rows
                    if row["split"] == split
                )
                / sum(row["split"] == split for row in rows),
            }
            for split in ("development", "holdout")
        },
        "cases": rows,
    }
    path = Path("../../.artifacts/evals/product-routing.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if all(row["route_exact"] and row["intent_exact"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
