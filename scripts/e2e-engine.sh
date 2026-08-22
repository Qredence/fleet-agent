#!/usr/bin/env bash
# E2E engine matrix against a REAL provider (Databricks AI Gateway via .env).
#
# Requires:
#   FLEET_AGENT_AGENT_MODE=engine in apps/api/.env
#   FLEET_AGENT_LLM_* configured (model/base_url/api_key)
#   Postgres up; alembic upgraded
#
# Matrix:
#   1. create project + thread via REST
#   2. send search+report request → 2 tool calls, inline artifact card,
#      Artifacts tab entry (Ready) with working controlled download
#   3. continuation probe referencing the previous turn (no new search)
#   4. reload → messages + process state restored from persistence

set -euo pipefail
export AGENT_BROWSER_SESSION="${AGENT_BROWSER_SESSION:-fleet-e2e-engine}"
API_BASE="${API_BASE:-http://localhost:8000}"
WEB_BASE="${WEB_BASE:-http://localhost:5173}"
AB="${AB:-npx agent-browser}"

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

note "phase 2: search + write_report live run"
$AB fill "$TEXTBOX" "Search the docs for how AG-UI state sync works, write a short markdown report about it, and save the report as a file." >/dev/null
SEND=$($AB snapshot -i | grep "button \"Send message\"" | sed 's/.*ref=//; s/].*//' | head -1)
$AB click "$SEND" >/dev/null

# Live LLM runs take a while; poll for the inline artifact card (CUSTOM event).
ARTICLE=""
for _ in $(seq 1 40); do
  sleep 1.5
  SNAP_ART=$($AB snapshot -i -c 2>/dev/null || true)
  ARTICLE=$(grep -oE 'button "[^"]+ · open in Artifacts"' <<<"$SNAP_ART" | head -1 || true)
  [[ -n "$ARTICLE" ]] && break
done
[[ -n "$ARTICLE" ]] || die "phase 'artifact' — inline artifact card never appeared within 60s"
require_grep "$ARTICLE" "open in Artifacts" "inline artifact card present"

sleep 2
MAIN=$($AB get text "main")
require_grep "$MAIN" "tool call" "tool calls collapsed in thread"
SNAP=$($AB snapshot -i)
require_grep "$SNAP" "Completed" "run completed"

note "phase 3: artifact download via controlled URL"
ARTIFACTS=$(curl -sS "$API_BASE/api/threads/$THREAD_ID/artifacts")
DOWNLOAD_URL=$(python3 -c "import json,sys;d=json.load(sys.stdin);print(d[0]['downloadUrl'])" <<<"$ARTIFACTS")
STATUS=$(curl -s -o /tmp/e2e-artifact.md -w "%{http_code}" "$API_BASE$DOWNLOAD_URL")
[[ "$STATUS" == "200" ]] || die "phase 'download' — got $STATUS"
SIZE=$(wc -c < /tmp/e2e-artifact.md | tr -d ' ')
[[ "$SIZE" -gt 0 ]] || die "phase 'download' — empty body"
printf 'ok: %s (%sB)\n' "download served $DOWNLOAD_URL" "$SIZE"

note "phase 4: continuation across turns (no new search)"
TEXTBOX=$($AB snapshot -i | grep "textbox \"Message input\"" | sed 's/.*ref=//; s/].*//' | head -1)
$AB fill "$TEXTBOX" "Without searching again: what did you just name that report file, and in one sentence what is its format?" >/dev/null
SEND=$($AB snapshot -i | grep "button \"Send message\"" | sed 's/.*ref=//; s/].*//' | head -1)
$AB click "$SEND" >/dev/null

ANSWER=""
for _ in $(seq 1 30); do
  sleep 1.5
  MAIN=$($AB get text "main")
  ANSWER_LINE=$(grep -F "AG-UI-State-Sync.md" <<<"$MAIN" | tail -1 || true)
  [[ -n "$ANSWER_LINE" ]] && break
done
require_grep "$ANSWER_LINE" "AG-UI-State-Sync.md" "continuation answer names the file"
printf 'ok: %s\n' "continuation answered without re-searching"

note "phase 5: reload restores conversation + process state"
$AB reload >/dev/null
sleep 2.5
MAIN=$($AB get text "main")
require_grep "$MAIN" "Search the docs for how AG-UI state sync works" "user turn restored"
require_grep "$MAIN" "AG-UI State Sync" "assistant content restored"
SNAP=$($AB snapshot -i -c)
require_grep "$SNAP" "Completed" "process state restored"
require_grep "$SNAP" "AG-UI-State-Sync.md" "artifact restored in panel"

echo "ALL ENGINE PHASES PASSED"
