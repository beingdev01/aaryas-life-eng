# Runbook: research

How one research issue becomes a filed, gated memo. The engine does the model work;
this department's kit decides what "done" means.

## 0. Intake (before any engine call)
Read the issue. It must state the question, why it matters, and the decision it feeds.
- All three present: continue.
- Any missing: comment the sharper question you propose and end
  `RESULT: BLOCKED - need a sharper question: <proposed question>`. No engine run.
- Clearly an Owner decision (taste, money, relationships, risk appetite): end
  `RESULT: ESCALATED - <exact question>`.

## 1. Draft and run
```
/home/ubuntu/aaryas-life/organisation-rebuild/departments/engineering/pipeline/engctl draft --issue <ISSUE-ID> --run
```
The engine probes the drafting lanes, drafts a task spec from the issue, has a lane from
a different model family attack its checkability, and validates it at the intake gate.
The spec names one deliverable, the memo, inside the run workdir under
`/home/ubuntu/aaryas-life/departments/research/work/<slug>/`, named
`YYYY-MM-DD-<slug>.md`. Because the deliverable ends in `.md`, this kit's acceptance
templates add two engine-run gates to the spec:

| Gate name | Command | Fails when |
|---|---|---|
| `dept:cited:<file>` | `python3 <kit>/tools/cite_check.py <memo>` | no Sources; a Findings claim with no citation and no INFERENCE marker; a `[n]` not in Sources; a malformed URL |
| `dept:memo-format:<file>` | `python3 <kit>/tools/memo_lint.py <memo>` | a section missing or out of order; empty Recommendation; TODO, TBD, XXX, lorem or `[insert` left in |

Depth comes from the agent: research-1 runs at depth 2 (two recon slices, one review
round, no red team), research-2 at depth 4 (four recon slices, best-of-2 sampling on
hard parts, red team on the plan, two review rounds). Recon lanes may read web pages
because the profile sets `web: true`; every lane prompt carries this kit's four skills
and the profile's constraints.

If you want to read the spec before it runs, drop `--run`, check it, then
`engctl run <spec-path>`.

## 2. What the engine checks, in order
1. Build lanes write the memo in their own workdirs.
2. Gate: each `dept:` command runs in a subprocess with a timeout; exit code 0 or the
   part goes to fix.
3. Review: a lane from a different family than the builder returns file:line findings.
   Reviewers should use `checklists/research-review.md`.
4. Fix: the builder fixes critical and high findings, bounded rounds.
5. Verify: the engine re-runs every gate on the integrated memo and writes
   `RUN_REPORT.md` from the ledger. Only `RESULT: DONE` from the engine counts.

## 3. File and receipt (the research agent does this, not a lane)
```
K=/home/ubuntu/aaryas-life/organisation-rebuild/departments/research
M=/home/ubuntu/aaryas-life/departments/research/memos
cp <run-delivery>/2026-10-30-zen-review-lane.md $M/
python3 $K/tools/memo_lint.py --filed $M/2026-10-30-zen-review-lane.md
python3 $K/tools/cite_check.py $M/2026-10-30-zen-review-lane.md
python3 $K/tools/memo_index.py --memos $M --out $M/INDEX.md
wc -c $M/2026-10-30-zen-review-lane.md
```
Then comment on the issue: the filed path, the byte count, both `OK` lines, and the
recommendation in one sentence. End `RESULT: DONE`, or `RESULT: ESCALATED - <question>`
if the memo leaves an Owner decision open.

## Worked example
Illustrative issue (the id AAR-140 is an example): "Can the engine's review stage use
another OpenCode Zen free model? CEO decides
today whether to add it to lanes.yaml." Assigned to research-1.
1. Intake passes: question, why, decision all present.
2. `engctl draft --issue AAR-140 --run` drafts a depth 2 spec with the deliverable
   `.../research/work/zen-review-lane/2026-10-30-zen-review-lane.md` (min 1500 bytes).
3. Recon slice 1 reads `ENGINE_DESIGN.md` and finds the 2026-10-30 quota failures (lines
   38-40); slice 2 reads the Zen documentation pages for published free limits.
4. First build fails `dept:cited`: "claim has no citation ... 'Zen quotas reset
   daily'". No source said that. The fix round marks it
   `INFERENCE (not verified this run)` and moves it to Open questions.
5. Verify passes both gates; the agent files the memo and posts the receipt.

## Failure modes and what to do
- `RESULT: BLOCKED - no live drafting lane`: every free drafting lane is down. Do not
  retry in a loop. Comment the probe output on the issue and leave it for the CEO;
  the next scheduled run retries.
- A lane hangs at quota: the engine kills it at its timeout and picks another live lane;
  if `engctl reap` lists old lane processes, report them to the CEO (killing is opt-in).
- cite_check fails on a source with no locator: give the full URL or `path:line`. A
  paper needs its DOI URL (`https://doi.org/...`).
- memo_lint "out of order": move the section; do not rename headings to dodge the check.
- Gates pass but the reviewer says a source is secondary: replace it with the primary
  source, or keep it and say "secondary source" in the bullet.
- The question changes during research: stop, file nothing, comment the new question,
  end BLOCKED. Do not answer a question nobody asked.
- Asked to build or install what the memo recommends: hand off to Engineering per the
  charter; never do it here.
