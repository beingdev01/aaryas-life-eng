# Research review checklist

For the reviewer lane (a different model family than the builder) and for the CEO.
Run the two gates first; a memo that fails either is REVISE without further reading.

```
python3 <kit>/tools/memo_lint.py <memo.md>
python3 <kit>/tools/cite_check.py <memo.md>
```

## Question and scope
- [ ] The Question is one falsifiable sentence, and it is the question the issue asked.
- [ ] Why it matters names who decides what, and by when.
- [ ] Depth matches the agent: research-1 at most three options; research-2 has
      first-principles constraints, a disagreement bullet where sources differ, and a
      Pre-mortem with three specific causes, signals and guards.

## Sources
- [ ] Open three cited sources at random. Each exists and says what the bullet claims.
- [ ] The numbers that decide the recommendation come from primary sources (vendor docs,
      limits or pricing pages, specs, papers, repository files), not blog summaries.
- [ ] Every time-sensitive number has a checked date, and no source is stale against a
      newer primary source.
- [ ] Secondary sources are labelled as secondary.
- [ ] Where sources conflict, both are cited and the memo says which it trusts and why.

## Facts and inference
- [ ] Nothing under Facts is actually reasoning; nothing under Inferences is presented
      as certain.
- [ ] Nothing is invented: no unreachable source is cited as if it was read.

## Free-tier discipline (any memo about a tool, model, API or host)
- [ ] Each option states its free limit with unit and scope (per key, account, IP).
- [ ] Each option states what happens at the limit (429, pause, hang, paid fallback).
- [ ] Standing tiers are kept apart from one-time grants.
- [ ] No paid model, paid tier or card-gated trial is recommended.

## Recommendation
- [ ] One recommendation, with its strongest reason and what would change it.
- [ ] It follows from the Findings; nothing new appears only in the Recommendation.
- [ ] Anything only Lakshya can decide is an escalation, not a buried assumption.

## Boundaries
- [ ] The memo does not execute anything, contain production code, or create issues.
- [ ] No credentials, tokens or private data appear anywhere in it.

Verdict: APPROVE, or REVISE with findings as `memo.md:line: problem -> fix`.
