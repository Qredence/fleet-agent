---
name: qa-web
description: >
  QA tests for the Fleet Agent web app (apps/web): React 19 + Vite chat UI at
  http://localhost:5173. Covers project/thread navigation, fixtures chat runs
  (inline run activity, tool cards, process panel), cancel, reload restore,
  settings providers dialog, and engine-mode artifact/approval flows. Driven
  by agent-browser with text snapshots as primary evidence.
---

# QA — Fleet Agent Web (apps/web)

Single anonymous local user; the app has no login. The web app is the chat
workspace at `http://localhost:5173`; it talks to the API at
`http://localhost:8000` (VITE_API_BASE_URL).

## Testing Target

This project has NO preview deployments. Always test the checked-out branch
code via a local dev server:

1. Ensure the API is running first (see orchestrator Step 4) -- the web app
   needs it for any data.
2. Start the web dev server: `pnpm dev:web` (port 5173). Poll
   `curl -sf http://localhost:5173` until ready.
3. Base URL for all flows: `http://localhost:5173`.

NEVER fall back to a remote environment. If the dev server cannot start,
report ALL web flows as BLOCKED with the startup error.

Use `npx agent-browser` (aliased `$AB` below) with session
`export AGENT_BROWSER_SESSION=fleet-qa-web`. The repo's
`scripts/e2e-fixtures.sh` / `e2e-engine.sh` are battle-tested references for
the same flows.

## Pre-flight

- `curl -sf http://localhost:8000/api/health` -> API up.
- `curl -sf http://localhost:5173` -> web up.
- Read `apps/api/.env` (never print values) to learn the agent mode:
  fixtures (default) vs engine, and whether a Tavily key exists.
- Fixtures mode is deterministic: thread creation via REST works but runs
  replay canned NDJSON streams.
- Engine mode flows additionally need PostgreSQL with `uv run alembic
  upgrade head` applied.

## UI Facts (stable selectors/labels)

- Composer: `textbox "Message input"`; send: `button "Send message"`.
- Sidebar: `button "New thread"`; thread header shows the thread title.
- Process panel container: `[data-slot="process-panel"]`; tabs `tab "Activity"`,
  `tab "Sources"`, `tab "Artifacts"`.
- URLs own project/thread state: `/projects/:projectId/threads/:threadId`.
- Settings dialog opens from the project sidebar; tabs "Providers & Models"
  and "Appearance".
- Extract element refs from `agent-browser snapshot -i` (e.g.
  `sed 's/.*ref=//; s/].*//'`); refs change between snapshots -- re-snapshot
  before every click.

## Flow Menu

Run ONLY flows relevant to the diff (see orchestrator Step 5). Each flow lists
the code areas it covers so you can match it to the diff.

### Flow A — Project/thread lifecycle + navigation
*Covers: apps/web routing, thread bootstrap, project sidebar; apps/api
projects/threads endpoints.*

1. `curl POST http://localhost:8000/api/projects` `{"name":"QA <RUN_ID>"}` ->
   capture `project_id`; `curl POST /api/projects/$ID/threads`
   `{"title":"QA thread"}` -> capture `thread_id`. Append ids to
   `./qa-results/$RUN_ID/created.txt`.
2. `$AB open http://localhost:5173/projects/$PROJECT_ID/threads/$THREAD_ID`
3. Snapshot `-i -c`: verify thread title, "Message input", "New thread".
4. POST a second thread; open its URL; verify the header switched.
5. DELETE the second thread via REST; verify a 200.

### Flow B — Fixtures chat run (inline activity, tool card, panel)
*Covers: agent-runtime-provider, run-activity-inline, tool-fallback,
process panel, trace reducer; the fixtures loop of /api/agent.*

1. Open the thread URL; snapshot; extract the composer ref.
2. `$AB fill <TEXTBOX> "How does the agent state sync work?"`; click
   `button "Send message"`.
3. Poll (1.5s intervals, up to ~10s) until settled; then:
   - `$AB get text main` contains a tool-call step ("tool call") and the
     fixture answer text.
   - Click the Activity tab: panel text contains "Completed" and
     "search_docs".
   - Click the Sources tab: panel lists "docs.ag-ui.com".
4. Record: the answer rendered as markdown (prose), run-activity steps are
   collapsible (aria-expanded toggles if you click one).

### Flow C — Cancel mid-run
*Covers: run cancellation path in agent-runtime-provider + coordinator.*

1. Send "cancel timing probe".
2. Within ~0.3s of clicking send, snapshot; "Stop generating" button must be
   visible. Click it.
3. After ~1s, snapshot: "Stop generating" is gone and the composer is idle.
   If the button vanished before the click (fixture runs are fast), re-run
   once, then report FLAKY with the timing.

### Flow D — Reload restore
*Covers: thread restoration, keyed runtime, bootstrap snapshot.*

1. `$AB reload`; wait ~2s; `$AB eval "location.pathname"` still
   `/projects/$PROJECT_ID/threads/$THREAD_ID`.
2. The prior fixtures turn (user text + assistant answer) is restored in
   `main`; snapshot shows the restored shell.

### Flow E — Settings: providers & models
*Covers: settings-dialog, lib/providers.ts, openrouter-auth, BYOK headers.*

1. Open Settings from the project sidebar.
2. Providers tab: verify "Active Provider" selector shows "Server default"
   and "OpenRouter".
3. Paste-key path: click "Or paste API key manually", type a DUMMY key
   (`sk-or-v1-qa-dummykey123456`), "Save Key" -> connected badge +
   masked key shown. This stores the dummy key in localStorage -- cleanup
   after: `$AB eval "localStorage.removeItem('openrouter_api_key')"`.
4. Invalid input boundary: empty key -> inline error, no storage write.
5. Add custom provider: "Add Provider" -> fill Name "QA Gateway", Base URL
   "https://qa-gateway.example/v1", API Key "sk-qa", Model ID
   "openai/gpt-4o", response format "JSON tool calls", messages format
   "Developer role" -> "Save Provider" -> profile listed, "Active" badge.
   Negative: base URL "not-a-url" -> inline error, nothing saved.
6. Delete the QA profile -> list reverts, active falls back to "Server
   default".
7. Theme (only if Appearance code changed): switch Light/Dark/System; the
   html class changes (verify via `$AB eval "document.documentElement.className"`).

### Flow F — Engine: search + report artifact (engine mode ONLY)
*Covers: engine bridge, artifact tools, custom artifact events, panel.*

Prerequisites: `FLEET_AGENT_AGENT_MODE=engine` + LLM key in apps/api/.env;
otherwise report BLOCKED with that remediation.

1. New thread via REST; open it.
2. Send: "Search the docs for how AG-UI state sync works, then write a short
   markdown report about it as a managed report artifact."
3. Poll up to 60s for the inline artifact card ("Open artifact"); click the
   Artifacts tab -> artifact "Ready".
4. `$AB get text main` shows tool-call steps; poll up to 60s for "Completed".
5. Verify the run activity shows the search and report steps in order.

### Flow G — Engine: continuation + restore (engine mode ONLY)
*Covers: persistence, continuation history, restore path.*

1. Continuing from Flow F's thread: fetch the artifact filename via
   `curl http://localhost:8000/api/threads/$THREAD_ID/artifacts`.
2. Send: "Without searching again: what did you just name that report file,
   and in one sentence what is its format?"
3. Poll up to 45s for an answer containing the filename; the answer must NOT
   include a new search tool step (continuation, not re-run).
4. `$AB reload` -> user turn, assistant answer, "Completed" process state,
   and the artifact entry are all restored.

### Flow H — Engine: web search via Tavily (engine mode + Tavily key)
*Covers: web tools bundle, source discovery, web-search inline events.*

Prerequisites: engine mode + `FLEET_AGENT_TAVILY_API_KEY` in apps/api/.env.
Otherwise report BLOCKED ("set FLEET_AGENT_TAVILY_API_KEY in apps/api/.env").

1. New thread; send: "Search the web for the latest AG-UI protocol news and
   summarize two items."
2. The run activity includes web-search steps; the Sources panel gains
   non-docs.ag-ui.com sources; the answer summarizes results.

### Flow I — Responsive spot check (adjacent flow)
*Covers: layout/RTL logical properties, mobile shell.*

1. `$AB set viewport 375 812`; open a thread; snapshot: sidebar collapses to
   a drawer toggle, composer usable.
2. Restore viewport 1440 900.

## Evidence

Per flow: one labeled `snapshot -i -c` text block (primary), screenshots to
`./qa-results/$RUN_ID/`, and one WebM recording (orchestrator Step 6 rules).

## Never silently skip a flow

Report BLOCKED with what was tried and the fix; continue to the next flow.

## Known Failure Modes

1. **Fixtures runs settle in ~4-5s.** Fixed sleeps longer than that waste
   time; shorter ones race. Poll snapshots at 1.5s intervals instead.
2. **The Stop button window is ~0.3s.** Fixture streams start fast; if the
   button is gone before the click, that is timing, not a bug -- retry once,
   then FLAKY.
3. **Refs are per-snapshot.** An extracted `ref=` from an old snapshot will
   fail after the DOM updates. Re-snapshot before each interaction.
4. **Panel content requires tab activation.** Sources/Artifacts are lazily
   rendered; click the tab and wait ~0.4s before reading
   `[data-slot="process-panel"]`.
5. **Engine answers are model-generated.** Never assert exact wording --
   assert structural facts (artifact present, filename from the API, no new
   search step).
6. **Dummy keys pollute localStorage.** Always remove
   `openrouter_api_key` (and `fleet_providers_v1` QA rows) after Flow E;
   verify with `$AB eval "localStorage.getItem('openrouter_api_key')"`.
7. **Vite dev server one-shot startup.** If :5173 is already in use from a
   previous run, reuse the running server instead of starting a second one.
