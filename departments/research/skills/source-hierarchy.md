# Source hierarchy and verification

Every sentence in Findings is either a FACT with a citation or an INFERENCE marked as
one. `tools/cite_check.py` fails the memo otherwise. Write it right the first time.

## Rank sources, use the highest you can reach
1. Primary: official docs, pricing and limits pages, changelogs, specs and RFCs,
   papers (DOI), vendor status pages, the repository's own files (`path:line`), and
   live output you ran yourself (`engctl lanes`, a model list) with the date.
2. Secondary: reputable comparison posts, GitHub issue threads, forum answers. Use them
   only as leads to a primary source. If no primary source exists, cite the secondary
   one and say "secondary source, not confirmed by the vendor".
3. Never cite: a model's own claim, a search snippet you did not open, an undated page
   for a time-sensitive number.

## Date-check every time-sensitive number
Limits, prices, model rosters and free-tier rules change without notice. For each one:
find the page's own date (changelog entry, "last updated", release note); write
"(checked YYYY-MM-DD)" in the Sources entry; and if the page is older than about 90
days, look for a newer primary source before using it. Real example from this company:
`kilo-multi-model-research.md:175` ranked Cerebras as a standing free tier ("1M
tokens/day") from secondary reports; the live check in the same memo
(`kilo-multi-model-research.md:344`) found the vendor had delisted that tier on
2026-09-16. The secondary pages were older than the vendor change.

## Cross-check
A number that drives the recommendation needs two independent sources, or one primary
source plus your own observation. One source only: say so in the bullet.

## When sources conflict
1. State both, each with its citation, in a "Where the sources disagree" bullet.
2. Prefer, in order: the more primary source, then the newer one, then the one that
   matches what you observed on the VM.
3. If the conflict changes the recommendation and cannot be settled, the memo still
   ships with both options, and the run ends with `RESULT: ESCALATED - <exact question>`.

## Marking
- FACT: `- Anonymous Kilo use is capped at 200 requests per hour per IP [3].`
- INFERENCE: put it under an `**Inferences:**` label, or write `INFERENCE:` at the
  start. Example: `INFERENCE: three busy lanes on one IP will exhaust that together.`
- Citations: `[n]` matching a numbered Sources entry, a full URL, or `path:line`.
- Not reachable this run: write "not verified this run" and mark it INFERENCE. Never
  invent a URL, a page title or a number.
