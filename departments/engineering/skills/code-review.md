# Code review rubric

Reviewers are a different model family from the builder; the engine enforces it.
quality-2 never reviews its own build. Read the spec first, then the code.

## Order of attention
1. Correctness: does it do what the frozen contract says, on the failure path too? Re-run
   the acceptance commands yourself; do not trust the builder's transcript.
2. Completeness: no stubs, `pass` bodies, placeholder returns, TODOs, dead code, or
   features the contract names but the code skips.
3. Constraint breaches: credentials read or printed, writes outside owned files, network
   or sends, deploys, a paid model named, banned paths touched.
4. Only then style, and only where it hurts correctness or readability.

## Finding format
One finding per problem: severity, `file:line`, problem, fix.
```
| # | severity | location | problem | fix |
| 1 | high | tools/lanewatch.py:142 | age uses > so a process exactly at the threshold is missed | compare with >= and add a boundary test |
```
- critical: data loss, credential exposure, production harm, paid spend.
- high: wrong result or broken contract; must be fixed before merge.
- medium: wrong in an edge case, or a missing test for a real path.
- low: clarity, naming, small robustness.

Without a line it is vague and `tools/review_lint.py` rejects it: "error handling could
be better" is not a finding.

## Verdict
`Verdict: APPROVE` only when no critical or high finding remains. APPROVE with zero
findings is valid and useful; do not invent findings to look thorough. `Verdict: REVISE`
must list what to change. Fix rounds go to the builder that owns the part; at most two,
then escalate.
