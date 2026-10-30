#!/usr/bin/env bash
# runner-common.sh — shared plumbing for bin/*-runner.sh (Paperclip inbox runners).
# Fixes opencode-review findings H1 (verified done-marking), H2 (head-of-line),
# H3 (poison guard), M11 (scratch files), M12 (receipt gating), M13 (this lib),
# M14 (empty-input guard), M16 (locking), L8 (fail-count validation).
#
# Sourcing contract: the runner must export PAPERCLIP_API_URL and set
# PAPERCLIP_API_KEY, RUNID, RUNNER_LOG, LOG_PREFIX before calling any function.

BASE_DIR="/home/ubuntu/aaryas-life"
STATE_DIR="$BASE_DIR/state"
mkdir -p "$STATE_DIR"
API_TIMEOUT=30

log() { echo "[$LOG_PREFIX $(date +%T)] $*" | tee -a "$RUNNER_LOG" >&2; }

# M16: lock protects the shared inbox fetch (read-modify-write on the queue).
# Per-issue state files (fail-count-$ISSUE_ID etc.) are safe for concurrent
# access by runners working on DIFFERENT issues. The lock MUST be released
# via release_lock() after fetch_issue_detail and before the long model
# execution, otherwise process-adapter agents (kilo, qoder) cannot run in
# parallel (17 Oct 2026 fix).
acquire_lock() {
  exec 9>>"$STATE_DIR/runner.lock"
  flock -n 9 || { log "another runner holds state/runner.lock — exiting"; exit 0; }
}

release_lock() {
  # Close FD 9, releasing the flock. Safe to call when lock not held.
  exec 9>&- 2>/dev/null || true
  log "released state/runner.lock"
}

# Shared curl wrapper: timeout, and "<http_code>:<body up to 200 chars>" parsing.
api_request() { # METHOD PATH JSON
  local resp code
  resp="$(curl -s --max-time "$API_TIMEOUT" -w $'\n%{http_code}' -X "$1" "${PAPERCLIP_API_URL}/api$2" \
    -H "Authorization: Bearer ${PAPERCLIP_API_KEY:-}" \
    -H "X-Paperclip-Run-Id: ${RUNID:-}" \
    -H "Content-Type: application/json" \
    -d "$3" 2>&1)"
  code="$(printf '%s' "$resp" | tail -n 1)"
  printf '%s:%s\n' "${code:-000}" "$(printf '%s' "$resp" | head -n -1 | head -c 200)"
}
api_post()  { api_request POST  "$1" "$2"; }
api_patch() { api_request PATCH "$1" "$2"; }

# M11: private, auto-cleaned scratch file instead of fixed /tmp names.
setup_scratch() {
  umask 077
  OUTFILE="$(mktemp)" || { log "FATAL: mktemp failed"; exit 1; }
  trap 'rm -f "$OUTFILE"' EXIT
}

# L8: fail-count files must contain only digits, never trusted as-is.
read_fail_count() { # ID
  local n
  n="$(cat "$STATE_DIR/fail-count-$1" 2>/dev/null)"
  printf '%s' "$n" | grep -Eq '^[0-9]+$' || n=0
  echo "$n"
}

# H3: failures recorded against an older issue revision are stale —
# reset the counter when the issue's updatedAt changes.
reset_stale_fail_count() { # ID UPDATED_AT
  [ -f "$STATE_DIR/fail-count-$1" ] || return 0
  [ -n "$2" ] || return 0
  if [ "$(cat "$STATE_DIR/fail-ts-$1" 2>/dev/null)" != "$2" ]; then
    rm -f "$STATE_DIR/fail-count-$1" "$STATE_DIR/fail-ts-$1" "$STATE_DIR/.notified-$1"
    log "fail count for $1 reset (issue updated since the failures)"
  fi
}

bump_fail_count() { # ID UPDATED_AT -> prints new count
  local n=$(( $(read_fail_count "$1") + 1 ))
  echo "$n" > "$STATE_DIR/fail-count-$1"
  printf '%s\n' "${2:-}" > "$STATE_DIR/fail-ts-$1"
  log "fail count for $1 now $n"
  if [ "$n" -ge 3 ]; then
    notify_poisoned "$1"
  fi
  echo "$n"
}

record_failure() {
  bump_fail_count "$ISSUE_ID" "${ISSUE_UPDATED_AT:-}" >/dev/null
}

# H3: comment "needs a human look" exactly once per poisoning, guarded by a
# marker file; the marker is only written if the comment actually landed.
notify_poisoned() { # ID
  local marker="$STATE_DIR/.notified-$1" n body resp
  [ -f "$marker" ] && return 0
  n="$(read_fail_count "$1")"
  if [ -z "${RUNID:-}" ]; then
    log "issue $1 poisoned ($n failures) — no run id, cannot comment"
    return 0
  fi
  body="$(python3 -c 'import json,sys; print(json.dumps({"body": "Runner: giving up after " + sys.argv[1] + " consecutive failures — needs a human look."}))' "$n")"
  resp="$(api_post "/issues/$1/comments" "$body")"
  case "${resp%%:*}" in
    2??) touch "$marker"; log "poison notice posted for $1" ;;
    *)   log "WARN: poison notice for $1 failed: $resp (will retry next run)" ;;
  esac
}

# H2: only todo/in_progress are eligible; candidates are ordered by
# (priority rank, updatedAt); poisoned candidates are skipped so one stuck
# issue can no longer block the queue.
fetch_inbox_issue() {
  local inbox candidates cid cts poisoned=0
  inbox="$(paperclipai agent inbox --json 2>/dev/null)"
  [ -n "$inbox" ] || { log "FATAL: inbox fetch failed"; exit 1; }
  candidates="$(printf '%s' "$inbox" | python3 -c '
import json, sys
items = json.load(sys.stdin)
rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
def key(i):
    return (rank.get(str(i.get("priority") or "medium").lower(), 2),
            str(i.get("updatedAt") or ""))
for i in sorted((x for x in items if x.get("status") in ("todo", "in_progress")), key=key):
    print("%s\t%s" % (i.get("id", ""), i.get("updatedAt") or ""))
' 2>/dev/null)"
  if [ -z "$candidates" ]; then
    log "inbox has no todo/in_progress issues — nothing to do"
    exit 0
  fi
  ISSUE_ID=""
  ISSUE_UPDATED_AT=""
  while IFS=$'\t' read -r cid cts; do
    [ -n "$cid" ] || continue
    reset_stale_fail_count "$cid" "$cts"
    if [ "$(read_fail_count "$cid")" -ge 3 ]; then
      log "issue $cid poisoned (3+ consecutive failures) — skipping to next candidate"
      notify_poisoned "$cid"
      poisoned=$((poisoned + 1))
      continue
    fi
    ISSUE_ID="$cid"
    ISSUE_UPDATED_AT="$cts"
    break
  done <<< "$candidates"
  if [ -z "$ISSUE_ID" ]; then
    log "FATAL: queue stalled — all $poisoned candidate(s) poisoned; humans notified"
    exit 1
  fi
}

# M14: a failed issue get silently yields empty TITLE/DESC; never spend a
# model invocation on empty input.
fetch_issue_detail() {
  DETAIL="$(paperclipai issue get "$ISSUE_ID" --json 2>/dev/null)"
  TITLE="$(printf '%s' "$DETAIL" | python3 -c "import json,sys; print(json.load(sys.stdin).get('title',''))" 2>/dev/null)"
  DESC="$(printf '%s' "$DETAIL" | python3 -c "import json,sys; print(json.load(sys.stdin).get('description',''))" 2>/dev/null)"
  if [ -z "$TITLE" ] || [ -z "$DESC" ]; then
    log "FATAL: empty title/description for issue $ISSUE_ID (fetch failed) — not running the model"
    exit 1
  fi
}

# H1 gate: strict runners (qoder) must end with '^RESULT: DONE'. Others honor
# the sentinel when present; with no sentinel the exit code decides.
sentinel_allows_done() { # OUT [strict]
  if printf '%s\n' "$1" | grep -qi 'RESULT: BLOCKED'; then return 1; fi
  if printf '%s\n' "$1" | grep -q '^RESULT: DONE'; then return 0; fi
  if printf '%s\n' "$1" | grep -qi '^RESULT:'; then return 1; fi
  if [ "${2:-}" = "strict" ]; then return 1; fi
  return 0
}

# M12: the receipt must land before done-marking is even attempted;
# retry once on 429/5xx.
post_receipt() { # PREFIX_LINE (reads model output from $OUTFILE)
  local body resp code
  body="$(python3 -c 'import json,sys; print(json.dumps({"body": sys.argv[1] + "\n\n" + sys.stdin.read()}))' "$1" < "$OUTFILE")"
  resp="$(api_post "/issues/$ISSUE_ID/comments" "$body")"
  code="${resp%%:*}"
  case "$code" in
    429|5??)
      log "comment POST -> $resp; retrying once"
      sleep 3
      resp="$(api_post "/issues/$ISSUE_ID/comments" "$body")"
      code="${resp%%:*}"
      ;;
  esac
  case "$code" in
    2??) log "comment POST ok ($code)"; return 0 ;;
    *)   log "FATAL: comment POST failed: $resp — refusing to mark $ISSUE_ID done without a receipt"; return 1 ;;
  esac
}

# H1: close only on a verified 2xx PATCH; retry once on 403/5xx; die loudly
# (non-zero exit) if it still fails, so the loss is visible in the run log.
mark_done_verified() {
  local resp code
  if [ -z "${RUNID:-}" ]; then
    log "FATAL: no run id — cannot verify done-marking for $ISSUE_ID"
    exit 1
  fi
  resp="$(api_patch "/issues/$ISSUE_ID" '{"status":"done"}')"
  code="${resp%%:*}"
  case "$code" in
    403|5??)
      log "done PATCH -> $resp; retrying once"
      sleep 3
      resp="$(api_patch "/issues/$ISSUE_ID" '{"status":"done"}')"
      code="${resp%%:*}"
      ;;
  esac
  case "$code" in
    2??)
      log "done-marked $ISSUE_ID (HTTP $code)"
      rm -f "$STATE_DIR/fail-count-$ISSUE_ID" "$STATE_DIR/fail-ts-$ISSUE_ID" "$STATE_DIR/.notified-$ISSUE_ID"
      return 0
      ;;
    *)
      log "FATAL: done-marking failed for $ISSUE_ID: $resp — issue left open"
      exit 1
      ;;
  esac
}

# charter_for <agent-shortname>: prints the company charter header + the binding
# rules + this agent's role section from agents/CHARTER.md (the real charter).
# Replaces the stale README.md that runners used to inject. Never fatal.

# charter_for <agent-shortname>: prints the company charter header + the binding
# rules + this agent's role section from agents/CHARTER.md (the real charter).
# Replaces the stale README.md that runners used to inject. Never fatal.
charter_for() {
  local name="$1" charter="$BASE_DIR/agents/CHARTER.md"
  [ -f "$charter" ] || return 0
  {
    sed -n '1,/^## Rules binding on ALL agents/p' "$charter"
    echo
    echo "## Your role definition (from the charter - this is your mandate):"
    awk -v n="$name" '
      /^## / { if (f) exit; if ($0 ~ "^## " n "([ \xe2\x80\x94]|$)") f=1 }
      f
    ' "$charter"
  } | head -c 4500
}
# ===== Switchboard additions for bin/lib/runner-common.sh =====

# routing_for: compact switchboard routing block injected into every agent prompt.
# Token-compact for free lanes. Full tables: agents/DIRECTORY.md, agents/ROUTING.md.
routing_for() {
  cat <<'ROUTEEOF'
## Switchboard — company routing (binding, see agents/ROUTING.md + agents/DIRECTORY.md)
You are one of 13 specialists. If any part of your task is outside YOUR mandate: do NOT attempt it.
Owner lookup: build-plan→Engineer; bulk code→qoder-1/bulk-2/bulk-3; quality-critical/integration/deploy/subdomain→opencode-1; independent review→quality-2; small task→fast-1; quick research→research-1; deep research→research-2; design→design-1; personal/career/club writing→personal-1/career-1/club-1; ambiguous→ESCALATE (never guess an owner).
Hand off: paperclipai issue child:create <this-issue-id> --payload-json '{"title":"Handoff from <you>: <title>","description":"<inputs + acceptance criteria + what you already tried>","priority":"<same>","assigneeAgentId":"<owner-uuid>"}'  (owner UUIDs in agents/DIRECTORY.md; assigning auto-starts their run). Then end your turn with exactly: RESULT: HANDED-OFF to <agent-name>
Guards: max 3 handoffs per chain — count parent links (paperclipai issue get) before handing off; never hand back to the agent that handed to you; state what was already tried.
No fit / ambiguous: end with exactly: RESULT: ESCALATED - <one-line reason>
ROUTEEOF
}

# terminal_state OUT [strict] -> DONE | HANDOFF | ESCALATE | FAIL
# Classifies the model's terminal sentinel. Switchboard-aware replacement for
# sentinel_allows_done. Non-strict runners (kilo/dept) still succeed when the
# model emits no RESULT line at all (legacy behavior preserved).
terminal_state() {
  local out="$1" strict="${2:-}"
  if printf '%s\n' "$out" | grep -qi '^RESULT: BLOCKED'; then echo FAIL; return; fi
  if printf '%s\n' "$out" | grep -q '^RESULT: DONE'; then echo DONE; return; fi
  if printf '%s\n' "$out" | grep -qi '^RESULT: HANDED-OFF'; then echo HANDOFF; return; fi
  if printf '%s\n' "$out" | grep -qi '^RESULT: ESCALATED'; then echo ESCALATE; return; fi
  if printf '%s\n' "$out" | grep -qi '^RESULT:'; then echo FAIL; return; fi
  if [ "$strict" = "strict" ]; then echo FAIL; else echo DONE; fi
}

# mark_escalated: ESCALATED is not a failure — park the issue as blocked (out of
# the dispatch queue, visible for CEO triage) without touching poison counters.
mark_escalated() {
  local resp code
  if [ -z "${RUNID:-}" ]; then
    log "FATAL: no run id — cannot park $ISSUE_ID as blocked"
    exit 1
  fi
  resp="$(api_patch "/issues/$ISSUE_ID" '{"status":"blocked"}')"
  code="${resp%%:*}"
  case "$code" in
    2??) log "parked $ISSUE_ID as blocked for CEO triage (HTTP $code)"; return 0 ;;
    *)   log "FATAL: could not park $ISSUE_ID as blocked: $resp"; exit 1 ;;
  esac
}
