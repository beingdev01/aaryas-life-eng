# Runbook: Engineering

How a request becomes verified, delivered work through the shared engine (`engctl`,
`organisation-rebuild/departments/engineering/pipeline/`). The engine is the executor;
Paperclip is the system of record; this kit is what the engine loads for Engineering:
the skills injected into every lane prompt, the tools lanes may run, and the acceptance
templates that turn those tools into gates.

## 1. The flow

```
issue (todo) -> spec (draft or by hand) -> spec_lint + validate -> engctl run
  -> probe -> recon (N lanes) -> plan -> red team -> build (parallel, own workdirs)
  -> gates -> cross-family review -> fix -> integrate -> verify -> RUN_REPORT.md
  -> board comment -> receipt comment by the agent -> CEO verifies on disk
```

1. **Spec.** `engctl draft --issue AAR-<n>` or start from `templates/task-spec.yaml`. Then
   `python3 tools/spec_lint.py <spec>` (must exit 0) and `engctl validate <spec>`.
2. **Dry run** when the spec is new: `engctl run <spec> --dry-run`.
3. **Run:** `engctl run <spec> --board-issue AAR-<n>`. Concurrency is 3 lanes (2 vCPU,
   about 470 MB per lane process); do not start a second run beside a running one.
4. **Read the result** (skills/using-the-engine.md), comment the receipt, end with the
   matching `RESULT:` line.

## 2. Gates

| gate | who runs it | fails when |
|---|---|---|
| intake | engine/spec.py | no title, goal under 40 chars, depth not 1-5, neither deliverables nor acceptance |
| free-lane audit | engine/guard.py | any enabled lane not provably free |
| part verify | engine/gate.py, each part's `verify_cmd` | the part's own check fails |
| deliverables | engine, at verify | a file is missing or under `min_bytes` |
| acceptance | engine, at verify | any spec check fails (exit code, expect_stdout, forbid_stdout) |
| `dept:spec-lint:*` | this kit on `*spec*.yaml` | the delivered spec is weak |
| `dept:review-lint:*` | this kit on `*review*.md`, `*REVIEW*.md`, `*review*.json` | a vague or verdict-less review |
| tripwire | engine/orchestrator.py | any write under agents/, bin/, ~/.ssh, the engine code or lanes.yaml |
| cost breaker | engine/lanes.py | any provider reports a non-zero cost |

Add `git_hygiene.py <repo>` to the acceptance of every task that commits to a repository.

## 3. Worked example

Request from Club (via the CEO), AAR-201: "Turn the Google Forms attendance export into a
certificate roster."

1. fast-1 checks the issue is sharp: input format known, output wanted, failure behaviour
   stated. It is not: no column names. fast-1 ends
   `RESULT: BLOCKED - which export (event, date) should the converter be built against?`.
2. The CEO attaches a sample export. Engineer writes `roster-convert-spec.yaml` from the
   template: depth 3, three deliverables with floors 1800/1200/300 bytes, five acceptance
   checks including a fixture round-trip that parses the JSON and a check that an empty
   file exits non-zero. `spec_lint.py` flags `test -f roster.py` that Engineer had added as
   a sixth check ("only tests existence"); it is removed, since the deliverable floor already
   covers existence.
3. `engctl run roster-convert-spec.yaml --board-issue AAR-201`. Probe finds 11 of 12 lanes
   live. Three recon lanes read the club folder and the sample; the planner splits two
   parts (`parser`, `cli-and-tests`), the red team (another family) points out that names
   with initials break title case; the plan is revised before any build.
4. Two build lanes from different families (for example `laguna-s` and `north-code` in
   lanes.yaml) build the two parts in separate workdirs. The engine runs each part's
   `verify_cmd`. A reviewer from a third family returns REVISE: one high finding at
   `roster.py:88` (empty input exits 0). The fix round goes to the part's builder; the
   second review approves.
5. Integration writes the single delivery folder; the engine re-runs all five acceptance
   checks and the deliverable floors. `RESULT: DONE`. RUN_REPORT.md shows total cost 0.
6. The agent comments the receipt: paths, sizes, `5/5 acceptance passed`, the run dir.
   The CEO verifies on disk.

## 4. Failure modes and what to do

- **A lane is quota-exhausted.** A free provider out of quota makes the CLI hang, not fail.
  The probe marks it `quota` or `hang` and excludes it; mid-run, the hard timeout (900 s)
  kills the call's whole process group and the ledger records the verdict. If the probe
  finds no live lane, the run ends `RESULT: BLOCKED - no live model lane`. Do not retry in
  a loop. Ask the CEO to disable the dead lane in lanes.yaml (engine code is not ours to
  edit), check stray processes with `engctl reap`, and rerun once lanes are live.
- **A part fails verification.** The part's `verify_cmd` failed. The fix round sends the
  failing output to the builder. If the final gates still pass after integration, the run
  is DONE with a warning; if they fail, it is FAILED. Read `gates/` and the part's reply in
  `lanes/` before touching anything: usually the contract was ambiguous, so fix the spec,
  not the code.
- **Review REVISE loops.** Fix rounds are bounded (depth 3 and above: two). If the same
  critical or high finding survives both, the reviewer and builder disagree about the
  contract. Do not run it again unchanged: Engineer rules on the contract, or
  `RESULT: ESCALATED - <the disputed point>` to the CEO.
- **The cost breaker trips.** A provider reported a non-zero cost on a lane believed free.
  Every later call was refused and the run is FAILED with the lane and model named. Nothing
  in Engineering may rerun until the CEO disables that lane in lanes.yaml. Report the
  ledger line verbatim; do not guess whether money was spent.
- **The protected-path tripwire fires.** A lane wrote under agents/, bin/, ~/.ssh, the
  engine code or lanes.yaml. The run is FAILED whatever the lanes report. Do not revert the
  change yourself: list the paths from the `tripwire` ledger event, escalate to the CEO at
  once, and treat the spec as unsafe until its authorized paths and constraints are fixed.
  Changes under banned paths are reported for review, not auto-failed, because cron jobs
  (auto-deploy every 3 minutes, the monitor every 5) write there too.
- **The spec was rejected at intake.** `RESULT: BLOCKED - spec rejected: ...`. Fix the named
  field; run `spec_lint.py` again; never weaken a check to get through.
- **Unpushed work.** `git_hygiene.py` exits 1. Push the feature branch before reporting done.
