# Memo format

One memo per issue. `tools/memo_lint.py` enforces the sections and their order;
`tools/cite_check.py` enforces citations. Start from `templates/memo-quick.md` (depth 2)
or `templates/memo-decision.md` (depth 4). Both tools must exit 0 before you report.

## Sections, in this order (## headings)
1. **Question**: one falsifiable sentence, then `Requested by:`. "Which of X, Y, Z is
   cheapest for W" is a question; "look into hosting" is not (return BLOCKED).
2. **Why it matters / decision it feeds**: who acts on the answer, what they decide,
   by when. A `Decision this feeds:` line under Question also satisfies this.
3. **Findings**: one `###` per option or sub-question. Under each, `**Facts:**`
   bullets ending in `[n]`, then `**Inferences:**` bullets. Each bullet is one claim.
4. **Options & trade-offs**: a table, criteria as rows. For any tool or service, the
   rows include the free-tier limit, what happens at the limit, and the setup the
   Owner must do.
5. **Recommendation**: one choice and its strongest reason, then
   `What would change it:`. "It depends" is not a recommendation; if the choice turns
   on the Owner's taste, money or risk appetite, recommend a default and escalate.
6. **Pre-mortem** (decision memos only).
7. **Open questions**: what this run could not settle and who could.
8. **Sources**: `[n] Title - URL (checked YYYY-MM-DD)`, one per line, numbered in
   order of first use. URLs in full; repository files as `path:line`.

End the file with `RESULT: DONE`. Filed copies are named
`departments/research/memos/YYYY-MM-DD-<slug>.md` (lowercase slug, the date the sources
were checked), as in `2026-10-13-static-docs-hosting-free-tier.md`.

## Worked example (shortened)
```
## Question
Can the engine's review lane use a second OpenCode Zen model?
Requested by: CEO
## Why it matters / decision it feeds
CEO decides today whether to add a Zen lane to lanes.yaml.
## Findings
### Zen free pool
**Facts:**
- On 2026-10-30 five of seven Zen free models returned "Free usage limit
  reached" and the CLI hung (ENGINE_DESIGN.md:39).
**Inferences:**
- A Zen lane needs a hard timeout, or a hung call blocks the review stage.
## Options & trade-offs
| Criterion | Add Zen lane | Keep current pool |
| At the limit | hangs, no exit | n/a |
## Recommendation
Keep the current pool; a lane that hangs at quota costs more than it adds.
What would change it: Zen returning an error exit at quota instead of hanging.
## Open questions
- When does the Zen free quota reset? No source found; CEO can re-run engctl probe.
## Sources
[1] Engine design - ENGINE_DESIGN.md:39 (checked 2026-10-30)
```

## Mistakes that fail the gates
Leftover `[insert ...]`, TODO or TBD; a Findings paragraph with no `[n]`; a `[4]` with
no Sources entry 4; `http//` typos; Recommendation written after Open questions.
