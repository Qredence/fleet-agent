---
name: qa-api
description: >
  QA tests for the Fleet Agent API (apps/api): FastAPI + DSPy at
  http://localhost:8000. Covers health/ready, projects/threads CRUD, the
  /api/agent AG-UI SSE stream in fixtures and engine modes, bootstrap,
  artifacts, sources, the tools catalog, validation failures, and CORS
  behavior. Driven by curl with response bodies as primary evidence.
---

# QA — Fleet Agent API (apps/api)

Single anonymous local user; no auth endpoints exist. Base URL
`http://localhost:8000` (FastAPI dev server). Optional shared gate: if
`FLEET_AGENT_API_KEY` is set in apps/api/.env, send `X-API-Key` on every call
(read .env to detect it -- never print the value).

## Testing Target

No preview deployments exist. Start the checked-out branch code locally:

1. `docker compose up -d postgres` (dev DB `fleet_agent` on :5432 -- NOT the
   pytest `fleet_agent_test` DB).
2. `cd apps/api && uv run alembic upgrade head`
3. `cd apps/api && uv run fastapi dev app/main.py` (background; log to
   ./qa-results/$RUN_ID/api.log); poll `curl -sf http://localhost:8000/api/health`.

If the API cannot start, report ALL api flows as BLOCKED with the error. If
:8000 is already serving, reuse it (verify `git rev-parse HEAD` matches the
working tree expectations -- otherwise restart it).

## Pre-flight

- `curl -sf http://localhost:8000/api/health` and `/api/ready` -> 200.
- Read `apps/api/.env` (never print): agent mode (fixtures/engine), whether
  an LLM key and Tavily key exist, whether the shared API key is set.

## API Facts

- AG-UI agent stream: `POST /api/agent` with `RunAgentInput` JSON
  (`threadId`, `runId`, `state`, `messages`, `tools`, `context`,
  `forwardedProps`); response is SSE with `data: {json}` lines (NDJSON of
  typed events: RUN_STARTED, TEXT_MESSAGE_START/CONTENT/END, STATE_SNAPSHOT,
  STATE_DELTA, TOOL_CALL_*, RUN_FINISHED | RUN_ERROR).
- Fixtures mode is thread-agnostic; engine mode requires a persisted thread
  (404 otherwise) and an LLM key.
- Errors use public codes from `app/contracts/error_codes.py`; stack traces
  never appear in responses.
- CORS accepts EXACT origins only (default `http://localhost:5173`).

## Flow Menu

Run ONLY flows relevant to the diff. Each flow lists the code areas it covers.

### Flow A — Liveness & catalog
*Covers: main app wiring, health, tools catalog.*

1. `GET /api/health`, `GET /api/ready` -> 200 JSON.
2. `GET /api/tools` -> 200, a JSON list of tool descriptors; capture the
   count.

### Flow B — Projects & threads CRUD
*Covers: api/projects.py, threads.py, persistence.*

1. `POST /api/projects` `{"name":"QA <RUN_ID>"}` -> 200/201, capture id;
   append to `./qa-results/$RUN_ID/created.txt`.
2. `GET /api/projects` -> contains the QA project.
3. `PATCH /api/projects/$ID` `{"name":"QA renamed"}` -> renamed in list.
4. `POST /api/projects/$ID/threads` `{"title":"QA thread"}` -> capture id.
5. `GET /api/projects/$ID/threads` -> contains it; `PATCH
   /api/threads/$TID` rename -> 200.
6. Negative: `GET /api/projects/00000000-0000-0000-0000-000000000000/threads`
   and `PATCH` on a missing thread -> 404, safe public error body.
7. Cleanup at run end: `DELETE /api/projects/$ID` -> 200; verify the list no
   longer contains it.

### Flow C — Fixtures agent stream (SSE)
*Covers: /api/agent, fixtures coordinator, event mapper, trace reducer,
run lifecycle.*

1. Create project+thread (Flow B helpers) or use threadless fixtures mode.
2. `curl -N -X POST http://localhost:8000/api/agent -H 'Content-Type:
   application/json' -d '{"threadId":"...","runId":"qa-<RUN_ID>","state":null,
   "messages":[{"id":"m1","role":"user","content":"How does state sync work?"}],
   "tools":[],"context":[],"forwardedProps":null}'` -- capture the full body.
3. Assert the event sequence: first `RUN_STARTED`; exactly one
   `TEXT_MESSAGE_START`; `TOOL_CALL_START`/`TOOL_CALL_RESULT` present;
   `STATE_SNAPSHOT` early; final event `RUN_FINISHED` with a completed
   outcome and an answer string; NO `RUN_ERROR`.
4. Assert safety: the raw stream contains no `next_thought`, no
   `dspy.History`, no stack traces.
5. Negative: POST the same `runId` again -> 409 with a public error code.
6. Negative: malformed JSON body -> 422; oversized body (>1MB) -> 413.

### Flow D — Bootstrap, sources, artifacts
*Covers: threads bootstrap, artifacts API, sources API.*

1. `GET /api/threads/$TID/bootstrap` -> 200 versioned snapshot
   (`schemaVersion` present), browser-safe (no raw history fields).
2. After a fixtures run on the thread: `GET /api/threads/$TID/sources` ->
   list containing docs.ag-ui.com items.
3. `GET /api/threads/$TID/artifacts` -> 200 JSON array (fixtures: empty ok).

### Flow E — Provider override validation (BYOK)
*Covers: provider.py header parsing, SSRF guard, 422 mapping.*

1. `POST /api/agent` with header `X-LLM-Key: sk-qa` but NO `X-LLM-Base-Url`
   -> 422 (a base URL is required for a provider key override).
2. With `X-LLM-Base-Url: http://localhost:4000/v1` -> 422 (private base URLs
   rejected).
3. With `X-LLM-Key: sk-qa` + `X-LLM-Base-Url: https://qa-gateway.example/v1`
   in FIXTURES mode -> the override is accepted but fixtures replay
   regardless; assert the request still streams (no 5xx). In ENGINE mode
   without a valid upstream key this will surface as a safe RUN_ERROR/422 --
   that is expected; note it, do not retry.
4. Legacy: `X-OpenRouter-Key` without `X-OpenRouter-Model` still accepted
   (headers parse; fixtures unaffected).

### Flow F — Engine run + artifact download (engine mode ONLY)
*Covers: live coordinator, DSPy engine, artifact storage, controlled URLs.*

Prerequisites: engine mode + LLM key in apps/api/.env; otherwise report
BLOCKED with "set FLEET_AGENT_AGENT_MODE=engine and MODAL_* in apps/api/.env".

1. New project+thread via REST (required -- engine runs belong to threads).
2. POST /api/agent asking to "write a short markdown report as a managed
   report artifact" -> SSE completes with RUN_FINISHED; capture events.
3. `GET /api/threads/$TID/artifacts` -> >=1 artifact with `downloadUrl`;
   `curl -o file -w "%{http_code}"` the download URL -> 200, non-empty body.
4. Negative: `GET /api/artifacts/00000000-0000-0000-0000-000000000000` ->
   404.

### Flow G — CORS exact-origin behavior
*Covers: settings-driven CORS.*

1. `curl -s -i -X OPTIONS http://localhost:8000/api/agent -H 'Origin:
   http://evil.example' -H 'Access-Control-Request-Method: POST'` -> the
   response must NOT allow that origin (no `Access-Control-Allow-Origin:
   http://evil.example`, never `*`).
2. Same preflight with `-H 'Origin: http://localhost:5173'` -> allowed.

## Evidence

Per flow: the exact curl command (headers redacted of any secrets), the
status line, and the (trimmed) response body as labeled fenced blocks. SSE
bodies: show the event-type sequence plus the final event, trimmed to ~40
lines.

## Never silently skip a flow

Report BLOCKED with what was tried and the fix; continue to the next flow.

## Known Failure Modes

1. **SSE needs a real socket.** Use the running uvicorn dev server with
   `curl -N` (no timeout). ASGI test transports in-process are NOT the QA
   target.
2. **Fixtures vs engine divergence.** Fixtures ignores provider overrides
   and threads; engine 404s without a persisted thread and RUN_ERRORs
   without a working LLM key. Check the mode FIRST (read .env, never print).
3. **runId idempotency.** Reusing a runId returns 409 unless the run was
   interrupted and the request carries a resume entry. Use unique runIds
   (`qa-$RUN_ID-<n>`).
4. **UUID-shaped ids everywhere.** Thread/project ids are UUIDs; a random
   UUID 404 test must use a well-formed one (the zero UUID) or you are
   testing input validation instead of lookup.
5. **Never print secrets.** apps/api/.env contains real keys (MODAL_*,
   Tavily). Read it to branch behavior; never echo values into evidence.
6. **Error bodies are contracts.** Assert the public error code string, not
   prose; bodies must never contain stack traces (assert that too).
