#!/usr/bin/env bash
# qoder-runner.sh — inbox-driven Paperclip `process`-adapter runner.
# Drives Qoder CLI (qodercli) for the Engineering department of Aarya's Life.
#
# Model strategy (CEO-approved):
#   - Qwen3.8-Flash (0.0x, effectively free) -> default for all engineering work
#   - Qwen3.8-Max (0.2x during off-peak)   -> heavy tasks, off-peak only
# Off-peak window: 19:30–05:30 IST (14:00–00:00 UTC), when Max is 98% off.
# Daily 100 free credits are the buffer for everything else.
#
# An issue requests Max by containing "[max]" or "heavy" in title/description.
# If Max is requested outside off-peak, the runner uses Flash and says so
# (never burns full-price credits silently).
#
# Auth: PAT in /home/ubuntu/.config/qoder-pat.env (600 perms):
#   export QODER_PERSONAL_ACCESS_TOKEN="pt-..."
set -u
export PATH="/home/ubuntu/.qoder/entry:/home/ubuntu/.nvm/versions/node/v24.21.0/bin:/home/ubuntu/.local/bin:/usr/bin:/bin"
export PAPERCLIP_API_URL="${PAPERCLIP_API_URL:-http://127.0.0.1:3100}"

# Load the Qoder PAT if present (server-side only, never logged).
if [ -f "/home/ubuntu/.config/qoder-pat.env" ]; then
  # shellcheck disable=SC1091
  set -a; . "/home/ubuntu/.config/qoder-pat.env"; set +a
fi

RUNID="${PAPERCLIP_RUN_ID:-}"
RUNNER_LOG="/home/ubuntu/aaryas-life/state/qoder-runner.log"
LOG_PREFIX="qoder-runner"
# shellcheck source=lib/runner-common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/runner-common.sh"

acquire_lock
log "=== run start ==="

if [ -z "${QODER_PERSONAL_ACCESS_TOKEN:-}" ]; then
  log "NO PAT: create one at https://qoder.com/account/integrations and save to /home/ubuntu/.config/qoder-pat.env — exiting"
  exit 0
fi
if [ -z "${PAPERCLIP_API_KEY:-}" ]; then log "no run-scoped API key — exiting"; exit 1; fi

# Off-peak check: 19:30–05:30 IST.
IST_HM="$(TZ=Asia/Kolkata date +%H%M)"
if [ "$IST_HM" -ge 1930 ] || [ "$IST_HM" -lt 530 ]; then OFFPEAK=1; else OFFPEAK=0; fi
log "IST now $(TZ=Asia/Kolkata date +%H:%M), offpeak=$OFFPEAK"

WORKDIR="${PAPERCLIP_WORKSPACE_CWD:-/home/ubuntu/aaryas-life/sandbox}"
mkdir -p "$WORKDIR"; cd "$WORKDIR" || exit 1
setup_scratch

fetch_inbox_issue
fetch_issue_detail
release_lock
log "working issue $ISSUE_ID: $TITLE"

# Model selection. IDs overridable via env; defaults per Qoder docs.
# Verify exact IDs with `qoder --list-models` after auth.
FLASH_MODEL="${QODER_FLASH_MODEL:-Qwen3.8-Flash}"
MAX_MODEL="${QODER_MAX_MODEL:-Qwen3.8-Max}"
WANT_MAX=0
if printf '%s %s' "$TITLE" "$DESC" | grep -qiE '\[max\]|heavy|complex|architecture'; then WANT_MAX=1; fi
if [ "$WANT_MAX" -eq 1 ] && [ "$OFFPEAK" -eq 1 ]; then
  MODEL="$MAX_MODEL"; REASON="heavy task in off-peak window (0.2x)"
elif [ "$WANT_MAX" -eq 1 ]; then
  MODEL="$FLASH_MODEL"; REASON="heavy task requested but outside off-peak — using free Flash instead of burning full-price credits"
else
  MODEL="$FLASH_MODEL"; REASON="default free engineering lane"
fi
log "model=$MODEL ($REASON)"

CHARTER="$(charter_for "qoder-1")"
ROUTING="$(routing_for)"
# Skill injection for qoder-1 (process adapter has no native skill sync).
SKILLS_SECTION="$(/home/ubuntu/aaryas-life/bin/inject-agent-skills.sh qoder-1 "$WORKDIR" 2>/dev/null || true)"
[ -n "$SKILLS_SECTION" ] && log "injected skills for qoder-1 (${#SKILLS_SECTION} chars)"
PROMPT="You are the Qoder Engineer of the company 'Aaryas Life' (a personal agent company). Company charter (ground truth — do not invent departments or rules not listed here): $CHARTER Your workspace directory is: $WORKDIR. Stay inside it unless the task explicitly names another path. Never touch /home/ubuntu/clubsite, /home/ubuntu/clubsite-git, system services, or credentials. $SKILLS_SECTION $ROUTING Task: $TITLE. Details: $DESC. When finished, summarize what you did and list full paths of any files you created or changed. End your response with exactly one line: RESULT: DONE (only if every deliverable in the task exists and works) or RESULT: BLOCKED - <one-line reason> (if you cannot finish)."

# bypass_permissions: headless runs cannot approve prompts; accept_edits auto-denies Bash. Prompt still forbids touching clubsite/services/creds.
OUT="$(timeout 1200 qoder -p "$PROMPT" -m "$MODEL" --permission-mode bypass_permissions --max-turns 40 -w "$WORKDIR" 2>&1)"
RC=$?
log "qoder exit=$RC model=$MODEL output_chars=${#OUT}"

STATE="$(terminal_state "$OUT" strict)"
log "terminal state: $STATE"

printf '%s' "$OUT" > "$OUTFILE"

if [ -z "$RUNID" ]; then
  log "no run id — skipped write-back (manual run)"
else
  case "$STATE" in
    DONE|HANDOFF)
      if [ "$RC" -eq 0 ]; then
        if post_receipt "Qoder run finished (exit $RC, model $MODEL):"; then
          mark_done_verified   # exits 1 unless the PATCH is verified 2xx
        else
          record_failure
          exit 1
        fi
      else
        record_failure
      fi
      ;;
    ESCALATE)
      if post_receipt "Qoder run finished (exit $RC, model $MODEL):"; then
        mark_escalated
      else
        record_failure
        exit 1
      fi
      ;;
    *)
      record_failure
      ;;
  esac
fi
log "=== run end ==="
