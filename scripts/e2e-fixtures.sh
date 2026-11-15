#!/usr/bin/env bash
# E2E via agent-browser CLI (deterministic fixtures loop, no provider keys).
#
# Matrix (fixtures mode):
#   1. create project + thread via REST directly (deterministic ids)
#   2. navigate UI to the thread
#   3. send a question → live process steps + tool call + final answer
#   4. sources tab lists sources
#   5. cancel mid-run keeps a stable UI state
#   6. reload keeps the thread URL (restoration surface stable)
#   7. thread switching navigates correctly
#
# Engine matrix (search_docs + write_report + continuation + restore) runs
# separately via scripts/e2e-engine.sh when FLEET_AGENT_AGENT_MODE=engine.
#
# Exit non-zero on the first failed phase.

set -euo pipefail
export AGENT_BROWSER_SESSION="${AGENT_BROWSER_SESSION:-fleet-e2e-fixtures}"
API_BASE="${API_BASE:-http://localhost:8000}"
WEB_BASE="${WEB_BASE:-http://localhost:5173}"
AB="${AB:-npx agent-browser}"
# Start the frontend with matching VITE_API_BASE_URL and VITE_API_KEY.
# API_BASE/WEB_BASE select services; FLEET_AGENT_API_KEY authenticates REST probes.

# Keep authentication headers out of output and browser navigation URLs.
curl() {
  if [[ -n "${FLEET_AGENT_API_KEY:-}" ]]; then
    command curl -H "X-API-Key: ${FLEET_AGENT_API_KEY}" "$@"
  else
    command curl "$@"
  fi
}

note() { printf '\n=== %s ===\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
require_grep() {
  local haystack="$1" needle="$2" label="$3"
  grep -Fq "$needle" <<<"$haystack" || {
    printf '%s\n' "$haystack" | head -20 >&2
    die "phase '$label' — expected to find: $needle"
  }
  printf 'ok: %s\n' "$label"
}
find_ref() {
  local haystack="$1" pattern="$2" label="$3" ref
  ref=$(printf '%s\n' "$haystack" | grep -F "$pattern" | sed 's/.*ref=//; s/].*//' | head -n 1 || true)
  [[ -n "$ref" ]] || die "missing UI element '$label' ($pattern)"
  printf '%s\n' "$ref"
}

MODE=$(curl -fsS "$API_BASE/api/agent/capabilities" | python3 -c 'import json,sys; print(json.load(sys.stdin)["agent_mode"])')
[[ "$MODE" == "fixtures" ]] || die "Expected an explicit fixtures service at API_BASE"

note "setup: fresh thread via REST"
BODY=$(curl -fsS -X POST "$API_BASE/api/projects" -H 'Content-Type: application/json' -d '{"name":"E2E fixtures"}')
PROJECT_ID=$(python3 -c "import json,sys;print(json.loads(sys.stdin.read())['id'])" <<<"$BODY")
BODY=$(curl -fsS -X POST "$API_BASE/api/projects/$PROJECT_ID/threads" -H 'Content-Type: application/json' -d '{"title":"E2E thread"}')
THREAD_ID=$(python3 -c "import json,sys;print(json.loads(sys.stdin.read())['id'])" <<<"$BODY")
echo "project=$PROJECT_ID thread=$THREAD_ID"

note "phase 1: thread loads"
$AB set viewport 1440 900 >/dev/null
$AB open "$WEB_BASE/projects/$PROJECT_ID/threads/$THREAD_ID" >/dev/null
# This dedicated smoke session must not inherit provider credentials or selection.
$AB eval "localStorage.clear()" >/dev/null
$AB reload >/dev/null
sleep 1.5
SNAP=$($AB snapshot -i -c)
require_grep "$SNAP" "E2E thread" "conversation header shows the thread title"
require_grep "$SNAP" "Message input" "composer present"
require_grep "$SNAP" "New thread" "sidebar actionable"

SNAP=$($AB snapshot -i)
TEXTBOX=$(find_ref "$SNAP" 'textbox "Message input"' "message input")

note "phase 2: fixture run — send, process, answer"
$AB fill "$TEXTBOX" "How does the agent state sync work?" >/dev/null
SNAP=$($AB snapshot -i)
SEND=$(find_ref "$SNAP" 'button "Send message"' "send message button")
$AB click "$SEND" >/dev/null
sleep 4.5
MAIN=$($AB get text "main")
require_grep "$MAIN" "tool call" "tool call collapsible in the thread"
require_grep "$MAIN" "JSON snapshot" "fixture answer text"

SNAP=$($AB snapshot -i)
ACTIVITY_TAB=$(find_ref "$SNAP" 'tab "Activity' "Activity tab")
$AB click "$ACTIVITY_TAB" >/dev/null
sleep 0.3
PANEL=$($AB get text "[data-slot=\"process-panel\"]")
require_grep "$PANEL" "Completed" "run status Completed in the Activity tab"
require_grep "$PANEL" "search_docs" "tool execution card"

SNAP=$($AB snapshot -i)
SOURCES_TAB=$(find_ref "$SNAP" 'tab "Sources' "Sources tab")
$AB click "$SOURCES_TAB" >/dev/null
sleep 0.4
PANEL=$($AB get text "[data-slot=\"process-panel\"]")
require_grep "$PANEL" "docs.ag-ui.com" "sources list present"

note "phase 3: cancel flow — stop during a run returns to idle"
SNAP=$($AB snapshot -i)
TEXTBOX=$(find_ref "$SNAP" 'textbox "Message input"' "message input")
$AB fill "$TEXTBOX" "cancel timing probe" >/dev/null
SNAP=$($AB snapshot -i)
SEND=$(find_ref "$SNAP" 'button "Send message"' "send message button")
$AB click "$SEND" >/dev/null
sleep 0.2
SNAP=$($AB snapshot -i)
require_grep "$SNAP" "Stop generating" "stop button appears during a run"
CLICKED=$($AB eval "(() => { const b = document.querySelector('button[aria-label=\"Stop generating\"]'); if (!b) return 'gone'; b.click(); return 'clicked'; })()" 2>&1 | tail -1)
[[ "$CLICKED" == *clicked* ]] || die "phase 'cancel' — stop button vanished before click ($CLICKED)"
sleep 0.6
SNAP=$($AB snapshot -i)
[[ ! "$SNAP" =~ Stop\ generating ]] || die "phase 'cancel' — stop button still visible"
printf 'ok: %s\n' "cancel flow clears the stop state"

note "phase 4: reload keeps the thread surface stable (fixtures are stateless by design)"
$AB reload >/dev/null
sleep 1.5
PATHNAME=$($AB eval "location.pathname" 2>&1 | tr -d '"')
[[ "$PATHNAME" == "/projects/$PROJECT_ID/threads/$THREAD_ID"* ]] || die "phase 'reload' — pathname drifted to $PATHNAME"
printf 'ok: %s\n' "reload preserves the thread URL + shell"

note "phase 5: thread switching"
THREAD2_BODY=$(curl -fsS -X POST "$API_BASE/api/projects/$PROJECT_ID/threads" -H 'Content-Type: application/json' -d '{"title":"Second thread"}')
THREAD2_ID=$(python3 -c "import json,sys;print(json.loads(sys.stdin.read())['id'])" <<<"$THREAD2_BODY")
$AB open "$WEB_BASE/projects/$PROJECT_ID/threads/$THREAD2_ID" >/dev/null
sleep 1.2
PATHNAME=$($AB eval "location.pathname" 2>&1 | tr -d '"')
[[ "$PATHNAME" == *"$THREAD2_ID" ]] || die "phase 'switch' — did not land on the second thread"
printf 'ok: %s\n' "thread switching lands on the target thread URL"

note "DSPy engineering-mode matrix: run scripts/e2e-engine.sh (requires .env gateway config)"
echo "ALL FIXTURE PHASES PASSED"
