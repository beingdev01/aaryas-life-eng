# Using the engine (engctl)

`organisation-rebuild/departments/engineering/pipeline/engctl`; Paperclip stays the record.

## Commands
- `engctl draft "<request>"`: plain English -> validated spec in pipeline/specs/; read and
  spec_lint it before running. `engctl draft --issue AAR-<n> --run`: draft and run at once.
- `engctl validate <spec>`: intake gate. `engctl run <spec> --dry-run`: nothing dispatched.
- `engctl run <spec> --board-issue AAR-<n>`: full pipeline, summary comment on the issue.
- `engctl status <run-id>`, `engctl lanes` (free-tier audit), `engctl probe` (runs every lane
  once; never loop it), `engctl reap` (lists hung lanes; `--kill` is the CEO's decision).

## Reading a run (pipeline/runs/<stamp>-<id>/)
- `RUN_REPORT.md`, written from the ledger: result line, live and excluded lanes, total
  reported cost (must be 0), parts (builder, family, verified, reviewer, verdict), receipts
  with sizes, gate results.
- `ledger.jsonl`: one event per line: `lane_call` (lane, model, verdict, exit_code,
  elapsed_sec, cost), `gate` (check, passed, reason), `stage_done`, `warning`, `tripwire`,
  `cost_breaker`, `run_end`. Lane verdicts: ok, empty, quota, no_funds, rate_limited, auth,
  hang, error, refused_paid, paid_cost_detected.
- `gates/<stage>.<check>.txt`: command, exit code, output tail. `lanes/`: prompts, replies.

## RESULT lines
- `DONE`: every deliverable is above min_bytes and every acceptance check passed when the
  engine ran it. Comment the receipt paths.
- `BLOCKED`: spec failed intake, no live lane, a lane not provably free, or the planner
  needs an answer. Fix the spec or ask the question.
- `ESCALATED`: a builder said the contract cannot be met and gates failed. Answer it or
  take it to the CEO; never rerun unchanged.
- `FAILED`: gates still failing after fix rounds, cost breaker, or tripwire. Read gates/
  first, then change the spec; an identical retry never helps.
`engctl run` exits 0 DONE, 1 not done, 2 spec or lane refused, 3 engine error.
