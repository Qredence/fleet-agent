# Fleet Agent implementation specifications

These documents define behavior and acceptance criteria. See [implementation status and measured results](implementation-status-2026-10-09.md) for delivered changes and remaining release checks. The HTML index retains the original proposal.

| Spec | Focus |
| --- | --- |
| [001 - Run outcome and durability](001-run-outcome-durability.md) | Separate completion from saving and preserve terminal truth. |
| [002 - Compound tasks and managed output](002-compound-tasks-managed-output.md) | Combine workspace evidence and report creation safely. |
| [003 - Evidence continuity and outcome](003-evidence-continuity.md) | Context-aware routing, bounded evidence and partial results. |
| [004 - Honest UI and shared cards](004-ui-capabilities-and-cards.md) | Supported inputs, scoped approval and versioned Data UI. |
| [005 - Feedback and evaluation provenance](005-feedback-evaluation-provenance.md) | Durable feedback, correct metrics and auditable candidates. |
| [006 - DSPy runtime simplification](006-dspy-runtime-simplification.md) | Isolated predictors and optional measured decision experiments. |
| [007 - Live acceptance and tracing](007-live-acceptance-and-tracing.md) | Command-provider acceptance, fault checks and metadata-only tracing. |

Start with 001, the supported-input slice of 004, and 002. Use one focused implementation task per vertical slice; do not implement the entire program in a single large change.

Each PR should report exact commands run and failures encountered. Never manufacture performance baselines or report unexecuted tests as passing.
