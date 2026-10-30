#!/usr/bin/env bash
# dept-runner.sh — generic inbox-driven Paperclip `process`-adapter runner
# for non-engineering departments (personal|career|club|platform|academics).
# Reads the department's README + runbooks for context, then uses an LLM
# (Qoder flash if authed, else Kilo free lane) to process the assigned issue:
# producing digests, reminders, and DRAFTS (never sends anything externally).
#
# Dept is passed as $1. Paperclip agent adapterConfig
# should set the command to: /home/ubuntu/aaryas-life/bin/dept-runner.sh <dept>
set -u
DEPT="${1:-}"
[ -n "$DEPT" ] || { echo "usage: dept-runner.sh <dept>" >&2; exit 1; }
# M15: allowlist — unvalidated $1 would traverse out of departments/ and
# craft log paths outside state/.
case "$DEPT" in
  personal|career|club|platform|academics) ;;
  *) echo "dept-runner.sh: unknown dept '$DEPT' (expected personal|career|club|platform|academics)" >&2; exit 1 ;;
esac
export PATH="/home/ubuntu/.qoder/entry:/home/ubuntu/.kilo/bin:/home/ubuntu/.nvm/versions/node/v24.21.0/bin:/home/ubuntu/.local/bin:/usr/bin:/bin"
export PAPERCLIP_API_URL="${PAPERCLIP_API_URL:-http://127.0.0.1:3100}"

if [ -f "/home/ubuntu/.config/qoder-pat.env" ]; then
  set -a; . "/home/ubuntu/.config/qoder-pat.env"; set +a
fi

RUNID="${PAPERCLIP_RUN_ID:-}"
RUNNER_LOG="/home/ubuntu/aaryas-life/state/dept-$DEPT.log"
LOG_PREFIX="dept-$DEPT"
# shellcheck source=lib/runner-common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/runner-common.sh"

acquire_lock
log "=== run start ==="
[ -n "${PAPERCLIP_API_KEY:-}" ] || { log "no run-scoped API key — exiting"; exit 1; }

DEPT_DIR="/home/ubuntu/aaryas-life/departments/$DEPT"
# M15: a missing brief means the model would invent the department's rules.
[ -f "$DEPT_DIR/README.md" ] || { log "FATAL: $DEPT_DIR/README.md missing — refusing to run without a department brief"; exit 1; }

WORKDIR="${PAPERCLIP_WORKSPACE_CWD:-/home/ubuntu/aaryas-life/sandbox/$DEPT}"
mkdir -p "$WORKDIR"; cd "$WORKDIR" || exit 1
setup_scratch

fetch_inbox_issue
fetch_issue_detail
log "working issue $ISSUE_ID: $TITLE"

DEPT_CTX="$(cat "$DEPT_DIR/README.md" 2>/dev/null | head -c 3000)"
CHARTER="$(charter_for "${DEPT}-1")"
ROUTING="$(routing_for)"
# Skill injection: dept -> agent (personal-1, career-1, club-1). process adapter has no native sync.
case "$DEPT" in personal) SKILL_AGENT="personal-1";; career) SKILL_AGENT="career-1";; club) SKILL_AGENT="club-1";; *) SKILL_AGENT="";; esac
SKILLS_SECTION=""
if [ -n "$SKILL_AGENT" ]; then SKILLS_SECTION="$(/home/ubuntu/aaryas-life/bin/inject-agent-skills.sh "$SKILL_AGENT" "$WORKDIR" 2>/dev/null || true)"; [ -n "$SKILLS_SECTION" ] && log "injected skills for $SKILL_AGENT (${#SKILLS_SECTION} chars)"; fi
PROMPT="You are the $DEPT department agent of the company 'Aaryas Life' (Lakshya is Owner, Muse is CEO). Company charter: $CHARTER Department brief: $DEPT_CTX HARD RULES: (1) You only DRAFT and REMIND — never send emails/messages, never make calls, never post publicly. Every draft must be marked DRAFT FOR CEO REVIEW. (2) Never reveal private relationship data to anyone. (3) Stay in $WORKDIR. $SKILLS_SECTION $ROUTING Task: $TITLE. Details: $DESC. Produce your output as a clear structured result the CEO can review."

if [ -n "${QODER_PERSONAL_ACCESS_TOKEN:-}" ]; then
  log "backend=qoder-flash"
  OUT="$(timeout 600 qoder -p "$PROMPT" -m "${QODER_FLASH_MODEL:-qwen3.8-flash}" --permission-mode accept_edits --max-turns 20 -w "$WORKDIR" 2>&1)"
  RC=$?
else
  log "backend=kilo-free (qoder not authed yet)"
  OUT="$(timeout 600 kilo run --auto "$PROMPT" 2>&1)"
  RC=$?
fi
log "backend exit=$RC output_chars=${#OUT}"

STATE="$(terminal_state "$OUT")"
log "terminal state: $STATE"

printf '%s' "$OUT" > "$OUTFILE"

EXIT_CODE=$RC
if [ -z "$RUNID" ]; then
  log "no run id - skipped write-back (manual run)"
else
  case "$STATE" in
    DONE|HANDOFF)
      if [ "$RC" -eq 0 ]; then
        if post_receipt "Dept $DEPT run finished (exit $RC):"; then
          mark_done_verified
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
      if post_receipt "Dept $DEPT escalated to CEO:"; then
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
log "=== run end ==="
exit $EXIT_CODE
