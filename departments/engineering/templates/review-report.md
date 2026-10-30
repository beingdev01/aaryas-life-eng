# Review: <part or task name>

<!-- Copy this file to <slug>-review.md. The engine runs tools/review_lint.py on any
deliverable named *review*.md, so every finding must carry a severity, a file:line,
the problem and the fix. Delete this comment and the example rows before filing. -->

- Reviewer: quality-2
- Builder: opencode-1
- Spec: /home/ubuntu/aaryas-life/departments/engineering/work/roster-convert/roster-convert-spec.yaml
- Run: /home/ubuntu/aaryas-life/organisation-rebuild/departments/engineering/pipeline/runs/20261031T0905Z-roster-convert
- Date: 2026-10-31

Verdict: REVISE

## What I checked myself

- Re-ran every acceptance command from the spec: 4 of 5 pass; `empty_input_fails` fails (exit 0, expected non-zero).
- Read roster.py end to end against the frozen contract in the spec goal.
- Ran the tests: `python3 -m unittest test_roster -v` -> 9 tests, OK.
- Scope: `git status` shows changes only under work/roster-convert/; nothing under banned paths.

## Findings

| # | severity | location | problem | fix |
|---|---|---|---|---|
| 1 | high | roster.py:88 | An input with a header and no data rows returns exit 0 with an empty roster, so the empty-file failure path in the contract never fires. | Count accepted rows after parsing and `sys.exit(2)` with a one-line stderr reason when it is zero. |
| 2 | medium | roster.py:41 | Duplicates are merged by exact roll number, so `21CS001` and `21cs001 ` count as two people. | Normalise with `.strip().upper()` before using the roll number as the merge key. |
| 3 | low | test_roster.py:12 | The fixture path is built from the current directory, so the suite fails when run from another directory. | Build it from `Path(__file__).resolve().parent / "tests"`. |

## Not findings (checked and clean)

- No third-party imports; no network calls; no credential paths read.
- Title-case handling covers hyphenated and initialled names (`A. K. Sharma`, `Rao-Singh`).

<!-- When nothing needs fixing, the whole Findings section is the single word "None."
and the verdict is APPROVE. That is a valid, useful review. -->
