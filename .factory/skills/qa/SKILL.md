---
name: qa
description: >
  Run QA tests for Fleet Agent. Analyzes the git diff to determine affected
  apps (web, api), starts local dev servers, runs configured test flows as a
  single anonymous local user, and generates a diff-targeted report with text
  snapshots, screenshots, and per-flow WebM recordings. Uses agent-browser for
  web testing and curl for API testing. Use when testing PRs, releases, or
  smoke testing the local environment.
---

# QA Orchestrator

**SCOPE: This skill performs manual/functional QA only -- verifying that the
application actually works by interacting with it as a real user would
(browser, API calls). Do NOT run or report on CI checks, linting, typecheck,
unit tests (pytest/vitest), or any static analysis. Those are handled by
separate commands.**

## Step 1: Load Configuration

Read `.factory/skills/qa/config.yaml` for environment URLs, apps, path
patterns, integrations, and cleanup rules.

## Step 2: Determine Target Environment

Default target is `local-dev-fixtures` (web :5173, API :8000). Engine flows
(`local-dev-engine`) run only when `apps/api/.env` has
`FLEET_AGENT_AGENT_MODE=engine` plus an LLM key (MODAL_* or
FLEET_AGENT_LLM_*). Read .env to decide -- NEVER print or copy its key values
into logs, reports, or files. When engine mode is not configured, run fixtures
flows and report engine flows as BLOCKED with the exact remediation ("set
FLEET_AGENT_AGENT_MODE=engine and MODAL_* in apps/api/.env").

There are no remote environments and no preview deployments in this project.
Never substitute a remote URL for local dev servers.

## Step 3: Analyze Git Diff

Run `git diff` (against `origin/main` or the merge base for a PR) to determine
what changed. Map changed files to apps using `path_patterns` in config.yaml:

- `apps/web/**` and `packages/contracts/**` -> web (agent-browser flows)
- `apps/api/**`, `packages/contracts/**`, `compose.yaml` -> api (curl flows)

Files matching NO app (`.factory/skills/**`, `docs/**`, `scripts/**`,
`README.md`, root config) are out of scope: do NOT run app flows for them.

For each affected app: run ONLY that app's relevant flows (Step 5) plus
diff-targeted tests. Apps NOT affected by the diff are completely out of
scope -- do not load their sub-skill, run their flows, or their pre-flight
checks.

If NO app is affected, report INCONCLUSIVE: "No app code changed -- QA not
applicable for this diff." Do NOT run any flows.

## Step 4: Pre-flight Checks (affected apps only)

This project has no preview deployments; QA always tests the checked-out
branch code via local dev servers:

1. PostgreSQL: `docker compose up -d postgres` (dev DB `fleet_agent`, port
   5432). Do NOT use the `fleet_agent_test` DB -- that one belongs to pytest.
2. API migrations: `cd apps/api && uv run alembic upgrade head`
3. Start the API in the background:
   `cd apps/api && uv run fastapi dev app/main.py` (port 8000; log to
   ./qa-results/$RUN_ID/api.log). Poll `curl -sf http://localhost:8000/api/health`
   until ready (timeout 60s).
4. If the web app is affected, start it in the background:
   `pnpm dev:web` (port 5173; log to ./qa-results/$RUN_ID/web.log). Poll
   `curl -sf http://localhost:5173` until ready (timeout 60s).
5. Read `apps/api/.env` to detect the agent mode (fixtures vs engine) and
   whether a Tavily key exists -- never print values.

If a pre-flight check fails for an affected app, report that app's tests as
BLOCKED with the error and remediation, and continue with other apps.

## Step 5: Execute Diff-Relevant Flows Only

For each affected app, read its sub-skill:

- web -> `.factory/skills/qa-web/SKILL.md`
- api -> `.factory/skills/qa-api/SKILL.md`

The sub-skill is a MENU of flows. You must:

1. Read the diff and identify which flows touch the changed behavior
   (e.g., a settings-dialog change -> provider dialog flows; an approval.py
   change -> approval preview + privacy; a contracts schema change -> both
   apps' fixture-stream flows).
2. Run those flows PLUS adjacent integration flows that verify the change
   did not break neighbors (e.g., a new tool catalog entry -> the tool appears
   in GET /api/tools and in the fixtures run's activity panel).
3. Do NOT run unrelated flows (a settings change does not require thread
   lifecycle tests; a docs change requires nothing).
4. If no existing flow covers the change, write an ad-hoc test that directly
   verifies the changed behavior as a real user would.
5. Do NOT run pytest, vitest, ruff, mypy, tsc, or any automated suite.

## Step 6: Evidence Capture

Primary evidence is TEXT: `agent-browser snapshot -i -c` (accessibility tree)
for web flows, and command + response bodies for API flows. Label every
snapshot with what it shows and why it matters. Each successive snapshot MUST
show something different (wait for the UI to actually change first).

Also capture screenshots to `./qa-results/$RUN_ID/` (PNG) as visual proof,
and generate an ImageMagick GIF diff (before/after) when a visual change is
the point of the diff.

**Video evidence (`video_evidence: true` in config.yaml):**

1. Before each browser flow: `npx agent-browser record start
   ./qa-results/$RUN_ID/<flow-slug>.webm`
2. Run the flow's interactions.
3. After the flow completes or fails: `npx agent-browser record stop`
4. Exactly one recording per flow, 60 seconds maximum. Never one video for
   the whole run.
5. Verify the file exists and is non-empty (`test -s <file>`). If missing or
   empty, re-run the flow once; still missing -> fall back to text evidence
   for that flow and note it.
6. This project has NO CI workflow, so there is no upload API available:
   reference the recording by filename in the report's evidence section
   (e.g., "Video: fixtures-run.webm") and note that all files in
   ./qa-results/ are the deliverable evidence bundle. NEVER embed unverified
   remote URLs.

## Step 7: Test Quality Gate

1. CHANGE-SPECIFIC FIRST. At least half the tests must directly verify the
   diff's behavioral change.
2. Integration tests are valid (the change coexists with neighbors), but
   they are not a license to run everything.
3. NO unrelated flows.
4. NO automated test suites (see Step 5).
5. At least 1 negative/boundary test per run (e.g., invalid provider headers,
   404 thread, duplicate runId 409, XSS-looking input rendered inert).
6. Interact as a real user: real browser clicks, real HTTP calls.
7. If you cannot articulate what the diff changes, mark INCONCLUSIVE rather
   than PASS.

## Step 8: Handle Failures

**Never silently skip a flow.** If a flow cannot complete, report it as
BLOCKED with what was tried and how the user can fix it, then continue to the
next flow. Never abort the entire run for a single failure.

## Step 9: Generate Report

Write `./qa-results/report.md` following
`.factory/skills/qa/REPORT-TEMPLATE.md` exactly:

- Starts with `## QA Report` and the results table.
- Result emojis: :white_check_mark: PASS, :x: FAIL, :no_entry: BLOCKED,
  :warning: FLAKY, :grey_question: INCONCLUSIVE.
- Concise: table + optional Action Required + one collapsed evidence block.
- No "Behavioral Change Summary", no Info metadata table, no prose about what
  the diff does, no setup rows (server startup is not a test).
- All snapshots/evidence in ONE `<details>` block; recordings referenced by
  filename.

## Step 10: Suggested Skill Updates (Failure Learning)

`failure_learning: suggest_in_report` -- after the report, if any BLOCKED or
FAIL revealed a NEW environment insight (not a bad selector or an
expected diff behavior), append a "Suggested Skill Updates (N issues found)"
table with severity (🔴 Breaking / 🟡 Degraded / 🔵 Info), target file, and a
self-contained fix prompt in a collapsed `<details>` per row. If nothing
genuinely new was learned, omit the section entirely.

## Cleanup (always, even on failure)

Delete every QA-created project via
`DELETE http://localhost:8000/api/projects/{id}`. Record created ids in
`./qa-results/$RUN_ID/created.txt` as you go, and reconcile at the end. Never
delete projects you did not create. Leave dev servers running if the user
started them interactively; stop servers that QA itself started (background
PIDs recorded in ./qa-results/$RUN_ID/).
