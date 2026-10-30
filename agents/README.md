# Agent roster — Aarya's Life

**Source of truth for roles:** `agents/CHARTER.md` (this file tracks the department mapping; Paperclip tracks the employees).

**Structure (8 departments, 13 agents):** Personal, Academics, Career, Club / Code.SCRIET, Platform, Research, Engineering, Design. Engineering has six specialist agents (Planner, Bulk Workhorse, Quality/Integration, NIM Bulk, NIM Fast, Free-lane Bulk); every other department has one.

| Department | Agent | Runner | Model / Lane | Status (verified 2026-10-15) |
|---|---|---|---|---|
| Personal | personal-1 | `process` → `bin/dept-runner.sh personal` | Qoder flash (or Kilo free fallback) | idle |
| Academics | — | ceo-cron | — | not staffed — tracker cron not on this VM |
| Career | career-1 | `process` → `bin/dept-runner.sh career` | Qoder flash (or Kilo free fallback) | idle (error 2026-10-14 was transient; resumed) |
| Club / Code.SCRIET | club-1 | `process` → `bin/dept-runner.sh club` | Qoder flash (or Kilo free fallback) | idle |
| Platform | — | vm-cron | n/a | system live (monitors/backups), not staffed |
| Research | research-1 | `process` → `bin/kilo-research1.sh` | Kilo anonymous free lane | idle |
| Research | research-2 | `process` → `bin/kilo-nim-research2.sh` | NIM nemotron-3-ultra (Owner key, server-side) | idle |
| Engineering | Engineer (Planner) | `process` → `bin/kilo-nim-engineer.sh` | NIM nemotron-3-ultra (Owner key, server-side) | idle |
| Engineering | qoder-1 (Bulk Workhorse) | `process` → `bin/qoder-runner.sh` | Qwen3.8-Flash (free) | idle |
| Engineering | opencode-1 (Quality/Integration) | `opencode_local` → `opencode/mimo-v2.6-flash-free` | OpenCode Zen (free) | idle |
| Engineering | bulk-2 (NIM Bulk) | `process` → `bin/kilo-nim-bulk2.sh` | NIM nemotron-3-super (Owner key, server-side) | idle |
| Engineering | bulk-3 (Free-lane Bulk) | `process` → `bin/kilo-bulk3.sh` | Kilo laguna-s-2.1:free | idle |
| Engineering | fast-1 (NIM Fast) | `process` → `bin/kilo-nim-fast1.sh` | NIM nemotron-3-lightning (Owner key, server-side) | idle |
| Engineering | quality-2 (Second Quality Lane) | `opencode_local` → `opencode/longcat-2.5-preview-free` | OpenCode Zen (free) | idle |
| Design | design-1 | `opencode_local` → `opencode/mimo-v2.6-flash-free` | OpenCode Zen (free) | idle (was `muse-spark-1.3` — hit "insufficient funds"; moved to free lane 2026-10-15) |

## Notes

- **All agents are `role=general` in Paperclip.** Role semantics live in `CHARTER.md` and are injected into every run: process-adapter runners via `bin/lib/runner-common.sh#charter_for`, opencode_local agents via their `instructions/AGENTS.md`.
- **Skill sync:** process adapters use `bin/inject-agent-skills.sh` (stages SKILL.md into the task workspace; verified working 2026-10-15). opencode_local agents use Paperclip native `paperclipSkillSync`.
- **State:** runners read/write `/home/ubuntu/aaryas-life/state/` (shared, lock-guarded). Departments keep domain state in `departments/<name>/`.
- **Known issue (open):** heartbeat-run receipt write-back gets 403 (run not attributed to issue); affected runs need a board close. Tracked for Platform.
