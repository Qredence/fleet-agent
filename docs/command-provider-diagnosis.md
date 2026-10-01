# Command provider investigation

## Status

Incomplete: the authorized browser regeneration failed. The exact provider
rejection rule has not been recovered, so no speculative serialization or
compatibility change has been applied.

## Confirmed evidence

The configured browser profile remained Command with model
`deepseek/deepseek-v4.1-flash`, native function calling and system messages.
Run `uK3HVFw` in thread `thread_ffb848aaea26` made four provider requests:

| Call | Stage | HTTP status | Relevant structure |
| --- | --- | --- | --- |
| 1 | Routing | 200 | JSON schema containing `route`; no tools |
| 2 | Evidence gathering | 200 | Seven declared tools; `next_thought` schema |
| 3 | Evidence continuation | 200 | Two paired tool calls/results; nonempty replayed reasoning |
| 4 | Forced submission, inferred from DSPy source | 400 | Same history/tools/schema; adds `tool_choice` |

The receipt originally labeled call 4 as evidence gathering because it classified
forced submission by the declared tool list. DSPy declares all tools during
forced submission and selects `submit` by name. The recorder now identifies that
selection explicitly. The original receipt is preserved without changing its
recorded facts. Its historical rejection fields reflect the earlier recorder; new
receipts omit arbitrary rejection prose.

The 1,151-byte error envelope was inspected before native error normalization.
It contained `invalid_request_error`; no provider request ID was captured.
Its embedded message was sanitized without successfully extracting the inner
rejection. Raw response bytes were discarded and cannot be reprocessed.
Nested data, double-encoded JSON and JSON followed by a gateway label are now
covered by deterministic parser regressions. This improves future capture;
it does not establish which of those forms Command actually used.

The browser displays `provider_request_rejected` and the Fleet run ID. The same
failed branch and message remain after reload. There is no final answer.

See [the sanitized run receipt](diagnostics/command-provider-uK3HVFw.json).

## Leading hypothesis

Native DSPy `ReActV2._forced_submit` sends a named `submit` tool choice.
DeepSeek documents that named and required tool choices return HTTP 400 in
thinking mode. That rule matches the successful continuation followed by the
forced-submission failure, but Command's actual error did not confirm it.

Sources:

- [DeepSeek Chat Completions request format](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek thinking and tool continuations](https://api-docs.deepseek.com/guides/thinking_mode/)

This remains a hypothesis. Removing `tool_choice` would weaken DSPy's forced
submission guarantee; changing thinking mode could change the model's behavior.
Neither is justified solely by the current opaque rejection.

## Implemented support

- Opt-in native HTTP transport recorder for hosted providers and gateways with run ID, call index, structural
  stage, status and sanitized provider request IDs. Native bytes and SSE lines
  are forwarded unchanged.
- Bounded error-envelope parsing in memory and nested-envelope parsing. New
  receipts retain only allowlisted error codes, field/rule vocabulary, structural
  locations, and recognizable request IDs that do not overlap request content.
  Free-form provider messages and error excerpts are discarded.
- Structural request facts include hashed call/result pairing, content types,
  reasoning presence, schema fields, tool count and tool-choice mode. Message
  summaries and retained receipts have explicit bounds.
- Per-run wire-call ceiling on hosted providers and gateways; failed attempts
  count toward the ceiling and DSPy retries are disabled when a ceiling is set.
- Shared safe `provider_request_rejected` error mapping with Fleet run ID.
- Removed the earlier truncated-error keyword logger. Diagnostic mode defaults
  to off. No dependency patches, model replacement or fallback were introduced.
- Retained reasoning replay: fixture tests verify exact replay across two tool
  iterations, including parallel calls and streaming, and clearing on close.

## Live request accounting

Three synthetic pairs consumed six provider requests: regular, native-tool and
streaming requests. Each pair received two HTTP 200 responses. The per-pair
ceiling stopped further inference; these are successful HTTP controls, not
completed architecture-analysis runs or a reproduced failing/control pair.

The single browser regeneration consumed four requests and failed at call 4.
Total: **10 of 14** provider requests. All six synthetic slots and the one browser
regeneration have been used. No further regeneration or synthetic probe was
performed. The numerical remainder does not override those separate limits.

## Remaining implementation checkpoint

1. With revised live-probe authorization, replay a minimal synthetic continuation
   with automatic tool choice and a matched request selecting `submit` by name.
   Use the improved recorder to recover Command's actual inner rejection.
2. Require an actionable field/rule and a successful control. If the documented
   thinking-mode rule is confirmed, choose an explicit supported native policy
   that preserves forced submission semantics; do not silently drop the choice.
3. Add the demonstrated failing/control pair as a fixture regression and verify
   routing, evidence, forced submission, synthesis and terminal cleanup.
4. Obtain renewed authorization for browser acceptance. Require a final answer,
   no run-error event, terminal persistence and history after reload.

The current changes improve diagnosis and public error handling. They do not
resolve or certify the Command architecture-analysis flow.

## Validation receipt

| Check | Result |
| --- | --- |
| Focused gateway, diagnostics, coordinator and resource tests | 48 passed |
| Final backend suite | 591 passed, 1 live test skipped |
| Ruff lint | Passed |
| Ruff formatting | 160 files passed |
| mypy | 91 source files passed |
| Frontend tests | 204 passed across 26 files |
| Frontend lint | Passed |
| Production build | Passed; Vite reported large bundle chunks |
| `git diff --check` | Passed |
| API health and web availability | HTTP 200 |
| Browser reload | Failed branch, safe error and run ID persisted |
| Live architecture-analysis acceptance | Failed: HTTP 400, no final answer |

The backend suite reported one SQLAlchemy deprecation warning in MLflow dataset
tests. The final API process runs with diagnostic mode off; both native tmux
services remain available. No personal environment file, credentials or selected
browser provider was changed. No commit or push was made.

Screenshot: `/tmp/fleet-agent-ui-checks/command-rejection-uK3HVFw.png`.
