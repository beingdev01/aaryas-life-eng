# Routing Table — Aarya's Life Switchboard

Task type → owner → execution chain → verifier. When a task arrives at the
wrong agent, that agent hands off per the routing rule (injected in every
prompt) — it does NOT attempt the work.

Conventions: `→` = hands to (child issue). CEO verifies receipts on disk at
every terminal hop ("receipts or it didn't happen"). Max 3 handoffs per chain.
Never hand back to the agent that handed to you.

---

## 1. New feature build (multi-part)
**Owner:** Engineer → **Chain:** Engineer plans (PLAN.md: parts, frozen contracts,
file ownership, acceptance) → CEO reviews plan → parallel build: opencode-1
(quality-critical parts) + qoder-1 / bulk-2 / bulk-3 (bulk parts, one part per
agent) → opencode-1 integrates → quality-2 reviews (independent) → CEO verifies
on disk → **Verifier:** CEO (a different agent never verifies its own build)

## 2. Bugfix — small (typo, copy change, single-file fix, quick check)
**Owner:** fast-1 → **Chain:** fast-1 fixes → **Verifier:** CEO or requesting agent
(receipt: before/after evidence)

## 3. Bugfix — medium (multi-file, needs tests, no architecture change)
**Owner:** qoder-1 (bulk-2 if Qoder lane busy) → **Chain:** qoder-1 fixes to the
existing contracts → **Verifier:** quality-2 if the area is quality-critical,
else CEO

## 4. Bugfix — hard (root cause unknown, architectural, data-loss risk)
**Owner:** Engineer → **Chain:** Engineer diagnoses → specced fix → qoder-1 or
opencode-1 implements → quality-2 reviews → **Verifier:** CEO

## 5. Hosting / subdomain / deploy
**Owner:** opencode-1 → **Chain:** (complex: Engineer plans first) → opencode-1
executes: DNS via Cloudflare API token, Caddy subdomain block
`http://<name>.codescriet.dev → 127.0.0.1:<port>`, `sudo systemctl restart caddy`
(never reload), chmod 644 on static files → **Verifier:** CEO (curl the live URL).
NEVER the main domain. NEVER touch ccsu-bypass, doc-classifier, or clubsite
unless the issue explicitly names them.

## 6. Research — quick (lookup, comparison, best practice, landscape scan)
**Owner:** research-1 → **Chain:** research-1 memos → **Verifier:** CEO
(memo in `departments/research/`, facts cited, inferences marked)

## 7. Research — deep (decision memo, first-principles, pre-mortem, hard trade-off)
**Owner:** research-2 → **Chain:** research-2 memos → **Verifier:** CEO.
Research NEVER executes: the memo goes back to the requesting dept/CEO for execution.

## 8. Design asset — INVITATION JOBS USE THE DESIGN TEAM, NEVER A SOLO AGENT (fixed 25 Oct 2026)
**Why this changed:** the old rule sent every invitation to design-1 alone. One agent, one
free-model session, heartbeat every 5 min, maxConcurrentRuns 20 — so one invitation spawned
up to 11 concurrent mimo runs that sat idle for hours, ate ~4 GB RAM, and never closed their
issues (AAR-153 locked 11+ h, AAR-154 idle with no run at all, AAR-158 idle 77 min). That is
what "the agent gets tired" was: not tiredness, unlimited concurrency + no deadline + no receipt.
**Owner:** Design Team (4 lanes, dispatched TOGETHER by the CEO, see §16) → **Chain:**
Lane A analyzes (15 min, gates the build) → Lanes B + C + D run IN PARALLEL on separate
workdirs/variants → opencode-1 integrates → CEO approves final → **Verifier:** CEO.
A solo design-1 invitation issue is now a routing violation — the CEO must split it into §16 lanes.
For non-invitation assets (poster, certificate, UI mockup): design-1 drafts (HTML/CSS/SVG source
+ preview PNG) → CEO art-directs (max 3 rounds) → CEO approves final → **Verifier:** CEO.
If the design must become a page/site: design-1 → hands source to opencode-1 to build.

## 9. Audit / review (code, security, plan, paper)
**Owner:** quality-2 (independent) → **Chain:** quality-2 reviews with
file:line:issue:fix findings → fix-ups to the owning builder (max 2, then
escalate) → **Verifier:** CEO. Builders never verify their own work.

## 10. Writing — personal (CRM, reminders, drafts for Lakshya)
**Owner:** personal-1 → **Verifier:** CEO. Draft-and-remind ONLY — never sends.

## 11. Writing — career (opportunities, applications, resumes, interview prep)
**Owner:** career-1 → **Verifier:** CEO (Lakshya approves every submission per item).
Never misrepresent qualifications.

## 12. Writing — club (event checklists, member drafts, triage)
**Owner:** club-1 → **Verifier:** CEO. Drafts only — never sends, posts, or touches the clubsite.

## 13. Platform / infra (VM health, monitors, backups, certs)
**Owner:** CEO directly (no agent owns production). Agents may only *report*
platform issues → club-1 triages → **Escalate to CEO immediately.**

## 14. Ambiguous / unknown / no-fit
**Owner:** none — **end with `RESULT: ESCALATED - <reason>`**. The CEO triages.
Never guess an owner.

---

## 15. Outreach — sponsor prospecting & engagement
**Owner:** outreach-1 (prospect) → outreach-2 (drafts/replies) → **Verifier:** CEO. Drafts only — never sends or contacts. Sends go via CEO from outreach@codescriet.dev after Owner approval.

## 16. Invitation / Design Team — the 4-lane parallel chain (binding, 25 Oct 2026)
One invitation request = FOUR issues dispatched together by the CEO, distinct titles
(Paperclip deduplicates exact titles — never reuse one). No lane starts blind, no lane waits
for another lane's taste, no lane shares a workdir with another lane.

Lane A — Analyze: research-1 (4630dea7-fcc0-47b6-8a3d-22c8244917e5). Read the brief +
reference + Lakshya's taste rules. Write DESIGN_SPEC.md: concept in 3 lines, palette (exact
hex), typography, layering order (what sits over what, in what order), movement arc, what must
NOT be reused. Nothing else. No render. First receipt: DESIGN_SPEC.md on disk + issue comment,
15 min. This lane gates Lane B.

Lane B — Build: design-1 (20013f7e-c6c8-4656-88f5-593e8646843c). Build ONLY from Lane A's
spec. Source + first preview PNG / first frames. Own workdir departments/design/work/<slug>-build/.
Never re-decide palette/layering — follow the spec, flag conflicts to CEO. First receipt: first
preview/frame on disk + comment, 15 min after spec. Hard clock: 45 min.

Lane C — Style (layering + color): quality-2 (5f8f8c6c-58c3-490c-b602-38a49e37b7b1, model now
opencode/beam-free, 25 Oct 2026). Independent check IN PARALLEL with Lane B, on Lane B's first
preview: layer order, color contrast, legibility at phone size, ghosting/overlap, crest integrity.
Output is a fix list with exact locations, or APPROVE. Never rebuilds, never approves its own
build. First receipt: style verdict on Lane B's first preview, 15 min after it lands.

Lane D — Motion + render + QA: opencode-1 (aa4e3944-cc9e-4378-af40-ee934671ceb1). Assemble the
final: ffmpeg render, WhatsApp 720p FIRST + master second, frame checks at 0/25/50/75/100% +
closing frame, exact file paths + sizes in the final comment. Own workdir, never overwrites
Lanes B/C. Hard clock: 45 min from spec.

Rules that make it fast instead of tired:
1. Single-flight, enforced twice: Paperclip maxConcurrentRuns is now 1 for design-1, opencode-1
   and quality-2 (set 25 Oct 2026), AND the CEO never dispatches a second job to an agent with an
   open in_progress invitation issue. A second wake while the first is open is a bug, not parallelism.
2. No "take your time" briefs on invitations. Every invitation issue states: first receipt 15 min,
   done 45 min, RESULT: DONE only with files on disk. Silence past 15 min = CEO pings once; past
   45 min = CEO takes the pen and renders directly (proven 25 Oct 2026: render_aarambh.py ran both
   720p student videos in ~4 min). Never dispatch a third retry to the same stalled agent.
3. A heartbeat is not a receipt. A heartbeat file, a "still working" comment, or a succeeded run
   with no file on disk counts as NOTHING. Receipt = preview PNG / mp4 on disk + issue comment
   naming its exact path. No receipt in 90 min with an execution lock still held = CEO force-releases
   the issue and re-dispatches once, then takes the pen.
4. Separate workdirs, one integrator. Lanes never write to the same folder. Only Lane D writes the
   final delivery folder. This kills the file-overwrite races that made concurrent design-1 runs
   produce previews but no finished video.
5. Model health is checked before dispatch: quality-2's model longcat-2.5-preview-free was removed
   from OpenCode on/before 25 Oct 2026 and quality-2 sat in error — a chain waiting on it could never
   finish. Before any invitation dispatch, the CEO checks agent list — any design-team lane in error
   is fixed or replaced BEFORE dispatch, never discovered mid-job.

## Handoff mechanics (binding)

1. The handing agent runs:
   `paperclipai issue child:create <this-issue-id> --payload-json '{"title":"Handoff from <you>: <short title>","description":"<inputs + acceptance criteria + what you already tried>","priority":"<same>","assigneeAgentId":"<owner-uuid>"}'`
   (Assigning fires the next agent's run automatically. Owner UUIDs: `agents/DIRECTORY.md`.)
2. Then ends its turn with exactly: `RESULT: HANDED-OFF to <agent-name>`
3. The runner posts the receipt and marks the hop done; the child carries the work forward.

## Loop guards (binding)

- **Max 3 handoffs per task chain.** Count parent links before handing off; at 3, ESCALATE instead.
- **State what was already tried** in every handoff description.
- **Never hand back** to the agent that handed the task to you — escalate instead.
- A handoff is not a failure: each hop is marked done with its receipt; the chain stays traceable via parent links.
