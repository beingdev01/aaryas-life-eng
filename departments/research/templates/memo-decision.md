# Research Memo: [insert the decision this memo settles]

<!-- Decision memo (depth 4, research-2). For choices that are expensive to reverse.
     Replace every [insert ...] before filing; memo_lint fails while any remain, and
     memo_lint requires the Pre-mortem section once it is present.
     File as departments/research/memos/YYYY-MM-DD-<slug>.md once the gates pass. -->

**Agent:** research-2
**Date:** [insert YYYY-MM-DD]
**Issue:** [insert Paperclip issue id and title]

## Question
[insert the decision as a question with its constraint, e.g. "Should X replace Y for Z, given free models only and a 2 vCPU VM?"]
Requested by: [insert agent or person]

## Why it matters / decision it feeds
[insert the decision, who makes it, the deadline, and the cost of getting it wrong]

## Findings

### Constraints from first principles
- [insert each hard constraint with where it comes from, e.g. "2 vCPUs on the VM (ENGINE_DESIGN.md:237)"]

### Evidence
**Facts:**
- [insert checked fact with citation [1]]

**Inferences:**
- [insert reasoning; mark anything not directly stated by a source]

### Where the sources disagree
- [insert source A says ... [1]; source B says ... [2]; which one is newer and more primary]

## Options & trade-offs

| Criterion (weight) | [insert option A] | [insert option B] | [insert option C: do nothing] |
|---|---|---|---|
| [insert criterion] | [insert] | [insert] | [insert] |
| Free-tier limit and failure mode | [insert] | [insert] | [insert] |
| Reversibility | [insert] | [insert] | [insert] |

## Recommendation
[insert one recommendation, the reasoning that leads to it, and the first step the executing department takes]

What would change it: [insert the facts that would flip it]

## Pre-mortem
Assume it is [insert date three months out] and the recommendation failed.
1. [insert most likely cause of failure, how we would notice early, and the guard]
2. [insert second cause, signal, and guard]
3. [insert third cause, signal, and guard]

## Open questions
- [insert unresolved question, why it matters, and who can answer it]

## Sources
[1] [insert title] - [insert primary-source URL] (checked [insert YYYY-MM-DD])
[2] [insert title] - [insert URL or path:line] (checked [insert YYYY-MM-DD])

RESULT: DONE
