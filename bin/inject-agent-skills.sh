#!/bin/bash
# inject-agent-skills.sh <agent-ref> <workdir>
# Fetches the agent's desired company skills from Paperclip and:
#   1. Writes each SKILL.md to <workdir>/skills/<slug>/SKILL.md
#   2. Prints a compact "YOUR SKILLS" prompt section to stdout
# Used by process-adapter runners (kilo/qoder/dept) which don't natively sync skills.
set -euo pipefail
AGENT_REF="${1:?usage: inject-agent-skills.sh <agent-ref> <workdir>}"
WORKDIR="${2:?usage: inject-agent-skills.sh <agent-ref> <workdir>}"
export PATH="$HOME/.nvm/versions/node/v24.21.0/bin:$PATH"
COMPANY_ID="${PAPERCLIP_COMPANY_ID:-469f7950-25cf-4366-8a82-1469c40e278f}"

# shortname -> agent UUID (paperclipai agent skills needs UUID; shortname lookup needs companyId the subcommand won't take)
agent_uuid() {
  case "$1" in
    Engineer) echo 35576977-c245-4de8-bcf8-de59b6488ad3 ;;
    opencode-1) echo aa4e3944-cc9e-4378-af40-ee934671ceb1 ;;
    qoder-1) echo 62ce1746-bcef-4753-963f-021c2200a604 ;;
    personal-1) echo 5f4bd3f5-2b95-4e1c-9238-78aadb0d79a4 ;;
    career-1) echo a10473d9-10a1-4ab7-a283-eddbae0e3ee3 ;;
    club-1) echo 765b1588-61f5-42fe-8120-49b80e565e6f ;;
    research-1) echo 4630dea7-fcc0-47b6-8a3d-22c8244917e5 ;;
    research-2) echo 93e0f3c4-9103-41b6-91e1-bd75e11eb570 ;;
    bulk-2) echo b599afa9-521a-4eb6-baa8-9c160f756443 ;;
    bulk-3) echo 9fa942b9-02c0-4137-a3f7-6d52ba284431 ;;
    fast-1) echo 896f1670-951c-49d6-b432-f467907aaf36 ;;
    quality-2) echo 5f8f8c6c-58c3-490c-b602-38a49e37b7b1 ;;
    design-1) echo 20013f7e-c6c8-4656-88f5-593e8646843c ;;
    *) echo "$1" ;;
  esac
}
AGENT_ID="$(agent_uuid "$AGENT_REF")"

KEYS="$(timeout 30 paperclipai agent skills "$AGENT_ID" --json 2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    for k in d.get('desiredSkills',[]): print(k)
except Exception: pass
")"
[ -z "$KEYS" ] && exit 0

SKILL_DIR="$WORKDIR/skills"
mkdir -p "$SKILL_DIR"

SECTION="YOUR SKILLS — when a skill's trigger below matches your task, read its full guide at $SKILL_DIR/<name>/SKILL.md first. Do not load skills whose trigger does not match."
while IFS= read -r key; do
  [ -z "$key" ] && continue
  META="$(timeout 30 paperclipai skills show "$key" -C "$COMPANY_ID" --json 2>/dev/null || echo {})"
  SLUG="$(echo "$META" | python3 -c "import json,sys; print(json.load(sys.stdin).get('slug','unknown'))" 2>/dev/null || echo unknown)"
  [ "$SLUG" = "unknown" ] || [ -z "$SLUG" ] && SLUG="$(echo "$key" | sed 's/.*\///')"
  DESC="$(echo "$META" | python3 -c "import json,sys; d=json.load(sys.stdin).get('description',''); print(d[:220])" 2>/dev/null || echo "")"
  mkdir -p "$SKILL_DIR/$SLUG"
  timeout 60 paperclipai skills file "$key" -C "$COMPANY_ID" > "$SKILL_DIR/$SLUG/SKILL.md" 2>/dev/null || true
  SECTION="$SECTION
- $SLUG: $DESC"
done <<< "$KEYS"

echo "$SECTION"
