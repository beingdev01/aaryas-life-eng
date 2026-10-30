# Plan: <fill: task title> (AAR-<fill: n>)

<!-- Engineer's plan for a multi-part build. Save beside the spec as <slug>-plan.md.
The engine's planner produces the same structure as JSON (PLAN.json); this document is
for builds the CEO reviews before dispatch (ROUTING section 1). Replace every <fill: ...>.
No part may share a file with another part. Every verify command must fail on fake work. -->

- Planner: Engineer
- Spec: <fill: absolute path of the spec>
- Depth: <fill: 1-5, and why>
- Date: <fill: YYYY-MM-DD>

## Summary

<fill: two or three sentences: the approach, and why this split rather than another.>

## Context used

<fill: the files and facts the plan rests on, each with path:line, and anything still
unknown marked UNKNOWN.>

## Parts

| id | owns files (exclusive) | depends on | builder | difficulty | verify_cmd |
|---|---|---|---|---|---|
| <fill: parser> | <fill: work/roster-convert/roster.py> | - | <fill: bulk-3> | <fill: medium> | <fill: python3 -m unittest test_parser> |
| <fill: cli-and-tests> | <fill: work/roster-convert/test_roster.py> | parser | <fill: qoder-1> | <fill: low> | <fill: ...> |

### Contract: <fill: part id>

- Input: <fill: exact type, file format or function signature>
- Output: <fill: exact shape, with one example>
- Errors: <fill: what happens on bad input; exit codes>
- Must not: <fill: the boundary, e.g. no network, no writes outside owns_files>

(One contract block per part. A builder reads only its own contract and the brief.)

## Integration

<fill: who integrates (opencode-1 for quality-critical work), into which delivery folder,
and which cross-part mismatches to expect.>

## Risks

| risk | likelihood | what we do about it |
|---|---|---|
| <fill: the most likely way this goes wrong> | <fill: high/medium/low> | <fill: the check or design choice that catches it> |

## Review and verification

- Reviewer: quality-2 (different model family from every builder); findings in
  `templates/review-report.md` form, linted by `tools/review_lint.py`.
- Acceptance the engine runs at the end: <fill: list the spec's acceptance names>.
- Repo work: `python3 tools/git_hygiene.py <repo>` exits 0 (every branch pushed).

## Decisions needed from the CEO

<fill: anything product, spending, sending, deploying or irreversible, or "none".>
