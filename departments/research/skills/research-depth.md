# Quick vs deep research

## Depth 2: research-1, quick memo
For lookups, comparisons, landscape scans. Two recon slices, one review round.
- At most three options, each with two to four cited facts.
- Primary sources only for the numbers that decide the answer.
- One screen of Findings. If the question turns out to be a decision that is expensive
  to reverse, stop and say so in Open questions: "needs a depth 4 memo (research-2)".

## Depth 4: research-2, decision memo
For decisions, first-principles analysis and pre-mortems. Four recon slices, red team,
two review rounds. Add three things a quick memo does not have:

**First principles (in Findings, first `###`).** List the hard constraints before any
option: free models only; 2 vCPUs and about 470 MB per lane process
(ENGINE_DESIGN.md:237); research never executes; the Owner's time. Each constraint gets a
citation. Then test every option against every constraint and drop the ones that break
one, saying which. Do not start from the popular option and justify it.

**Disagreement.** A "Where the sources disagree" bullet, resolved by the rules in
source-hierarchy.

**Pre-mortem (its own section, after Recommendation).** Write the date three months
out and "the recommendation failed". List the three most likely causes. For each: the
early signal that would show it, and the guard the executing department should add.
Causes must be specific to this company, for example "the free quota ran out mid-run
and the CLI hung", not "unexpected issues".

## Both depths
- Vague question: no memo. End `RESULT: BLOCKED - need a sharper question: <the
  sharper question you propose>`.
- Research writes the plan, never runs it: no code, no installs, no issues created.
- Prefer three well-cited options over ten shallow ones.
