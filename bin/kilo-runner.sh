#!/usr/bin/env bash
# kilo-runner.sh — inbox-driven Paperclip `process`-adapter runner.
# The Engineer agent of Aarya's Life. Drives Kilo Code CLI on its anonymous
# free lane (no signup, no API keys), or on NVIDIA NIM when KILO_MODEL=
# nvidia-nim/... (key from Owner-placed server-side env file).
#
# Contract (discovered 2026-10-12): Paperclip spawns this per heartbeat run and
# injects PAPERCLIP_API_URL + PAPERCLIP_API_KEY (run-scoped). The runner pulls
# its queue from the inbox (bin/lib/runner-common.sh), works the first
# eligible non-poisoned issue with Kilo, posts the result as an issue comment,
# and marks the issue done only after verifying the write.
set -u
export PATH="/home/ubuntu/.kilo/bin:/home/ubuntu/.nvm/versions/node/v24.21.0/bin:/home/ubuntu/.local/bin:/usr/bin:/bin"
export PAPERCLIP_API_URL="${PAPERCLIP_API_URL:-http://127.0.0.1:3100}"

RUNID="${PAPERCLIP_RUN_ID:-}"
RUNNER_LOG="/home/ubuntu/aaryas-life/state/runner.log"
LOG_PREFIX="kilo-runner"
# shellcheck source=lib/runner-common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/runner-common.sh"

acquire_lock
log "=== run start ==="
log "env: PAPERCLIP_RUN_ID=${RUNID:-<unset>} PAPERCLIP_AGENT_ID=${PAPERCLIP_AGENT_ID:-<unset>} API_URL=${PAPERCLIP_API_URL:-<unset>} API_KEY=${PAPERCLIP_API_KEY:+<set>}"

# NIM models (KILO_MODEL=nvidia-nim/...) need the NIM API key from the
# Owner-placed server-side env file (600 perms, never in chat/git).
# Fail fast with a clear message if the file is missing or the key is
# empty — never run with an empty key.
if [[ "${KILO_MODEL:-}" == nvidia-nim/* ]]; then
  NIM_ENV_FILE="/home/ubuntu/.config/nvidia-nim.env"
  if [ ! -f "$NIM_ENV_FILE" ]; then
    log "FATAL: KILO_MODEL=$KILO_MODEL needs $NIM_ENV_FILE (Owner: place the NIM key there, 600 perms)"
    exit 1
  fi
  # shellcheck disable=SC1090
  . "$NIM_ENV_FILE"
  if [ -z "${NVIDIA_NIM_API_KEY:-}" ]; then
    log "FATAL: NVIDIA_NIM_API_KEY empty in $NIM_ENV_FILE"
    exit 1
  fi
  export NVIDIA_NIM_API_KEY
fi

# Agent name for prompt + receipt (default Engineer = existing behavior).
AGENT_NAME="${NIM_AGENT_NAME:-Engineer}"

[ -n "${PAPERCLIP_API_KEY:-}" ] || { log "FATAL: no PAPERCLIP_API_KEY injected"; exit 2; }

WORKDIR="${PAPERCLIP_WORKSPACE_CWD:-/home/ubuntu/aaryas-life/sandbox}"
mkdir -p "$WORKDIR"
cd "$WORKDIR" || exit 1
setup_scratch

fetch_inbox_issue
fetch_issue_detail
release_lock
log "working issue $ISSUE_ID: $TITLE"

CHARTER="$(charter_for "$AGENT_NAME")"
ROUTING="$(routing_for)"
# Skill injection: stage this agent's desired company skills under $WORKDIR/skills/.
# PAPERCLIP_AGENT_ID is preferred (exact); falls back to AGENT_NAME.
SKILL_AGENT="${PAPERCLIP_AGENT_ID:-$AGENT_NAME}"
SKILLS_SECTION="$(/home/ubuntu/aaryas-life/bin/inject-agent-skills.sh "$SKILL_AGENT" "$WORKDIR" 2>/dev/null || true)"
[ -n "$SKILLS_SECTION" ] && log "injected skills for $SKILL_AGENT (${#SKILLS_SECTION} chars)"
PROMPT="You are the $AGENT_NAME agent of the company 'Aaryas Life' (a personal agent company). Company charter (ground truth — do not invent departments or rules not listed here): $CHARTER Your workspace directory is: $WORKDIR. Stay inside it unless the task explicitly names another path. Never touch /home/ubuntu/clubsite, /home/ubuntu/clubsite-git, system services, or credentials. $SKILLS_SECTION $ROUTING Task: $TITLE. Details: $DESC. When finished, summarize what you did and list full paths of any files you created or changed."

# --auto is required: without it Kilo auto-rejects work outside its default
# workspace (e.g. /home/ubuntu/clubsite-git named by a task) and the run dies
# asking for permission. Prompt-level guardrails still apply: stay in the
# task-authorized paths, never touch /home/ubuntu/clubsite (live tree),
# system services, or credentials.
# Per-agent timeout override (seconds). Default 1200 aligns with qoder-runner.
# The old hardcoded 800s killed the slow Nemotron-3-Ultra mid-task (16 Oct 2026).
KILO_TIMEOUT="${KILO_TIMEOUT:-1200}"
if [ -n "${KILO_MODEL:-}" ]; then
  OUT="$(timeout "$KILO_TIMEOUT" kilo run --auto -m "$KILO_MODEL" "$PROMPT" 2>&1)"
else
  OUT="$(timeout "$KILO_TIMEOUT" kilo run --auto "$PROMPT" 2>&1)"
fi
RC=$?
log "kilo exit=$RC output_chars=${#OUT}"

STATE="$(terminal_state "$OUT")"
log "terminal state: $STATE"

printf '%s' "$OUT" > "$OUTFILE"

EXIT_CODE=$RC
if [ -z "$RUNID" ]; then
  log "no run id — skipped write-back (manual run)"
else
  case "$STATE" in
    DONE|HANDOFF)
      if [ "$RC" -eq 0 ]; then
        if post_receipt "$AGENT_NAME run finished (exit $RC):"; then
          mark_done_verified   # exits 1 unless the PATCH is verified 2xx
        else
          record_failure
          EXIT_CODE=1
        fi
      else
        record_failure
        EXIT_CODE=1
      fi
      ;;
    ESCALATE)
      if post_receipt "$AGENT_NAME run finished (exit $RC):"; then
        mark_escalated
      else
        record_failure
        EXIT_CODE=1
      fi
      ;;
    *)
      record_failure
      EXIT_CODE=1
      ;;
  esac
fi

printf '%s\n' "$OUT"
exit $EXIT_CODE
