#!/usr/bin/env bash
# Supplementary E2E engine matrix against the configured live provider.
#
# Requires:
#   FLEET_AGENT_AGENT_MODE=engine in apps/api/.env
#   FLEET_AGENT_LLM_* configured (model/base_url/api_key)
#   Postgres up; alembic upgraded
#
# Matrix:
#   1. create project + thread via REST
#   2. send search+report request → evidence tools, inline artifact card,
#      Artifacts tab entry (Ready) with working controlled download
#   3. continuation probe referencing the previous turn (no new search)
#   4. reload → messages + process state restored from persistence

set -euo pipefail
export AGENT_BROWSER_SESSION="${AGENT_BROWSER_SESSION:-fleet-e2e-engine}"
API_BASE="${API_BASE:-http://localhost:8001}"
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
    printf '%s\n' "$haystack" | head -24 >&2
    die "phase '$label' — expected to find: $needle"
  }
  printf 'ok: %s\n' "$label"
}

MODE=$(curl -fsS "$API_BASE/api/agent/capabilities" | python3 -c 'import json,sys; print(json.load(sys.stdin)["agent_mode"])')
[[ "$MODE" == "engine" ]] || die "Expected an explicit engine service at API_BASE"

note "setup: fresh thread via REST"
BODY=$(curl -sS -X POST "$API_BASE/api/projects" -H 'Content-Type: application/json' -d '{"name":"E2E engine"}')
PROJECT_ID=$(python3 -c "import json,sys;print(json.loads(sys.stdin.read())['id'])" <<<"$BODY")
BODY=$(curl -sS -X POST "$API_BASE/api/projects/$PROJECT_ID/threads" -H 'Content-Type: application/json' -d '{"title":"Engine e2e"}')
THREAD_ID=$(python3 -c "import json,sys;print(json.loads(sys.stdin.read())['id'])" <<<"$BODY")
echo "project=$PROJECT_ID thread=$THREAD_ID"

note "phase 1: open thread"
$AB set viewport 1440 900 >/dev/null
$AB open "$WEB_BASE/projects/$PROJECT_ID/threads/$THREAD_ID" >/dev/null
sleep 1.5
SNAP=$($AB snapshot -i -c)
require_grep "$SNAP" "Message input" "composer present"

TEXTBOX=$($AB snapshot -i | grep "textbox \"Message input\"" | sed 's/.*ref=//; s/].*//' | head -1)

note "phase 2: search + managed report live run"
# Evidence routing and managed output intent are selected together.
# The application creates one Markdown report after synthesis.
$AB fill "$TEXTBOX" "Search the docs for how AG-UI state sync works, then write a short markdown report about it as a managed report artifact." >/dev/null
SEND=$($AB snapshot -i | grep "button \"Send message\"" | sed 's/.*ref=//; s/].*//' | head -1)
$AB click "$SEND" >/dev/null

# Live LLM runs take a while; poll for the inline artifact card (CUSTOM event).
ARTICLE=""
for _ in $(seq 1 40); do
  sleep 1.5
  SNAP_ART=$($AB snapshot -i -c 2>/dev/null || true)
  ARTICLE=$(grep -oE 'button "[^"]*· open in Artifacts|button "Open artifact [^"]+"' <<<"$SNAP_ART" | head -1 || true)
  [[ -n "$ARTICLE" ]] && break
done
[[ -n "$ARTICLE" ]] || die "phase 'artifact' — inline artifact card never appeared within 60s"
require_grep "$ARTICLE" "Open artifact" "inline artifact card present"

sleep 2
MAIN=$($AB get text "main")
require_grep "$MAIN" "tool call" "tool calls collapsed in thread"

# The run may still be streaming after the artifact event lands; poll for the
# settled "Saved" status before asserting.
SNAP=""
for _ in $(seq 1 40); do
  SNAP=$($AB snapshot -i)
  grep -q "Saved" <<<"$SNAP" && break
  sleep 1.5
done
require_grep "$SNAP" "Saved" "terminal persistence committed"
require_grep "$SNAP" "download artifact:" "authenticated download control present"

note "phase 3: artifact download via controlled URL"
ARTIFACTS=$(curl -sS "$API_BASE/api/threads/$THREAD_ID/artifacts")
DOWNLOAD_URL=$(python3 -c "import json,sys;d=json.load(sys.stdin);print(d[0]['downloadUrl'])" <<<"$ARTIFACTS")
STATUS=$(curl -s -o /tmp/e2e-artifact.md -w "%{http_code}" "$API_BASE$DOWNLOAD_URL")
[[ "$STATUS" == "200" ]] || die "phase 'download' — got $STATUS"
SIZE=$(wc -c < /tmp/e2e-artifact.md | tr -d ' ')
[[ "$SIZE" -gt 0 ]] || die "phase 'download' — empty body"
printf 'ok: %s (%sB)\n' "download served $DOWNLOAD_URL" "$SIZE"

note "phase 4: continuation across turns (no new search)"
# The managed report filename is deterministic; verify its resource metadata.
ARTIFACTS=$(curl -sS "$API_BASE/api/threads/$THREAD_ID/artifacts")
REPORT_NAME=$(python3 -c "import json,sys;print(json.load(sys.stdin)[0]['filename'])" <<<"$ARTIFACTS" 2>/dev/null || python3 -c "import json,sys;print(json.load(sys.stdin)[0]['name'])" <<<"$ARTIFACTS")
TEXTBOX=$($AB snapshot -i | grep "textbox \"Message input\"" | sed 's/.*ref=//; s/].*//' | head -1)
$AB fill "$TEXTBOX" "Make that a report using the prior answer, without searching again." >/dev/null
SEND=$($AB snapshot -i | grep "button \"Send message\"" | sed 's/.*ref=//; s/].*//' | head -1)
$AB click "$SEND" >/dev/null

# The prior card must not satisfy the follow-up assertion. Wait for a second
# ready managed artifact, then inspect its owning run's tool count.
for _ in $(seq 1 40); do
  ARTIFACTS=$(curl -fsS "$API_BASE/api/threads/$THREAD_ID/artifacts")
  READY_COUNT=$(python3 -c 'import json,sys; print(sum(a["status"] == "ready" for a in json.load(sys.stdin)))' <<<"$ARTIFACTS")
  [[ "$READY_COUNT" == "2" ]] && break
  sleep 1.5
done
[[ "$READY_COUNT" == "2" ]] || die "follow-up did not create exactly one additional report"
BOOTSTRAP=$(curl -fsS "$API_BASE/api/threads/$THREAD_ID/bootstrap")
python3 -c 'import json,sys; s=json.load(sys.stdin)["agentState"]; assert s["run"]["toolCallCount"] == 0' <<<"$BOOTSTRAP" || die "follow-up unnecessarily executed tools"
printf 'ok: continuation created a distinct report without re-searching\n'

# Wait for the continuation run to settle before reloading; an in-flight run
# is cancelled on disconnect, which would otherwise be restored as the final
# process state.
for _ in $(seq 1 40); do
  SNAP=$($AB snapshot -i)
  grep -q "Saved" <<<"$SNAP" && break
  sleep 1.5
done

note "phase 5: reload restores conversation + process state"
$AB reload >/dev/null
sleep 2.5
MAIN=$($AB get text "main")
require_grep "$MAIN" "Search the docs for how AG-UI state sync works" "user turn restored"
require_grep "$MAIN" "AG-UI" "assistant content restored"
SNAP=$($AB snapshot -i -c)
require_grep "$SNAP" "Saved" "process state restored"
require_grep "$SNAP" "$REPORT_NAME" "artifact restored in panel"

echo "ALL ENGINE PHASES PASSED"
