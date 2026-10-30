# Engineering department — the task engine

Status: built, benchmarked, staged in `organisation-rebuild/`. Not installed live.
Written 2026-10-30 by the builder session on the VM. Every number here comes from a
command whose output is on disk; see `receipts/` and the run ledgers.

---

## 1. What was asked

Build the Engineering department so it can take **any** task and run it at maximum depth,
with heavy curated context, fanned out across subagent lanes — on **free models only**,
with no paid tier under any circumstance. Then: *"optimize in a way that our free models
beat the paid one."*

The certificate system named in the original brief was only an example. The department
had to be general, and it had to be proven, not described.

## 2. Why the old department could not do it

The charter already contained the right thesis in its own words: "We do not win on raw
model power — free-tier models are not frontier models. We win on process: spec quality,
independent verification, review swarms, iteration, and specialization."

The thesis was never wrong. It was never implemented. It lived as prose, so every run
depended on a model choosing to comply. Four consequences, each verified:

**a. Five of fifteen agents were dead while reporting healthy.** OpenCode Zen's free tier
was exhausted, and an exhausted lane *hangs* rather than erroring. opencode-1, design-1,
outreach-1, outreach-2 and quality-2 were all pinned to exhausted models — the integrator,
the designer, both outreach lanes and the independent reviewer. Six processes sat 11–19
hours at ~470 MB each. This is the single cause behind design-1's zero output, the three
identical certificate retries, and the "~4 GB RAM" symptom already in `ROUTING.md` §8.

**b. A run could succeed with nothing on disk.** `runner-common.sh:269` returns `DONE`
when there is no `RESULT:` line, and the kilo prompt never asks for one. A timeout was
recorded as done: `kilo exit=124 output_chars=52` → `terminal state: DONE`.

**c. One task, one model, one shot**, inside a ~13-minute cap, with no decomposition and
no second opinion.

**d. Failure was answered with an identical retry**, not a restructure.

Plus a live paid path: `qoder-runner.sh:61` switches to paid Qwen3.8-Max when a title
contains `heavy`, `complex` or `architecture` during off-peak hours.

## 3. Architecture

### 3.1 Paperclip is the record; the engine is the executor

The engine drives the model CLIs directly with its own concurrency control and writes
receipts back to the board. It does not fight the platform's scheduler, shared lock or
title deduplication — it does not depend on them. Precedent: on 25 October a direct render
script finished in four minutes what dispatched lanes had not finished in days.

The primitive, proven by live test:

```
kilo     run --format json --title T --dir WORKDIR --auto -m MODEL "PROMPT"
opencode run --format json --title T --dir WORKDIR --auto -m MODEL "PROMPT"
qodercli -p "PROMPT" -m Qwen3.8-Flash -w WORKDIR -o stream-json --permission-mode dont_ask
```

`--dir` gives real per-lane isolation, which is what removes the shared lock from the
execution path rather than merely shortening how long it is held.

### 3.2 Depth is structural

```
intake → probe → recon → plan → red team → build → gate → review → fix → integrate → verify → repair → report
```

| stage | who | output |
|---|---|---|
| intake | engine | rejects any task whose completion is not machine-checkable |
| probe | engine | the live lane pool, cached 15 min, cooldowns honoured |
| recon | N lanes in parallel | one digest per slice, merged into a budgeted context pack |
| plan | strongest reasoning lane | parts with frozen contracts, exclusive file ownership, a check each |
| red team | a different family | attacks the plan; serious findings force one revision before any build |
| build | lanes in parallel | each part in its own workdir; hard parts get K independent attempts |
| gate | engine | runs each part's check and measures its declared files |
| review | a different family than the builder | file:line findings, **including the engine's measured gate results** |
| fix | the original builder | critical and high findings only, bounded rounds |
| integrate | one lane | one delivery folder; resolves cross-part mismatches |
| verify | engine | re-runs every acceptance command, re-checks every deliverable |
| repair | a builder | real failing output fed back, then everything re-verified |
| report | engine | generated from the ledger, never from a lane's self-report |

A depth dial scales all of it:

| depth | recon slices | sampling K | review rounds | red team | fix rounds |
|---|---|---|---|---|---|
| 1 | 1 | 1 | 0 | no | 1 |
| 2 | 2 | 1 | 1 | no | 1 |
| 3 | 3 | 1 | 1 | yes | 2 |
| 4 | 4 | 2 | 2 | yes | 2 |
| 5 | 6 | 3 | 2 | yes | 2 |

### 3.3 The mechanisms that make free lanes competitive

1. **Best-of-K sampling with an independent judge.** K lanes from different families solve
   the same frozen contract separately; the engine verifies each; a judge from a family
   that built none of them picks. A weak model sampled and filtered beats one asked once.
2. **Review forced onto a different model family, in code.** Eight families are live, so
   this is real diversity, not a label.
3. **The plan is attacked before anything is built.** Spec defects are the dominant cause
   of build failure; one cheap call prevents whole parallel builds against a bad contract.
4. **Deterministic gates.** The engine runs the checks itself. No model adjudicates itself.
5. **Repair from real output.** Failing stdout and stderr go back to a builder. Iterating
   against actual test output is how cheap lanes reach correctness.
6. **Curated context packs.** Parallel recon returns FACTS with `path:line`, RELEVANT,
   CONSTRAINTS, UNKNOWNS — dense and budgeted, not a window spent rediscovering the repo.

### 3.4 Free-only, enforced at five layers

1. **Identifier proof** for kilo and opencode: a `:free` or `-free` suffix, plus a denylist
   for `max`, `ultimate`, `premium`, frontier names and `auto` selectors.
2. **Offer verification** for qodercli (`offers.py`). Qwen3.8-Flash is free only by an
   offer with no announced end date, so a name allowlist would silently become a paid path
   the day it ends. The offer page is re-fetched every 24 h; a missing phrase, a fetch
   failure or a stale check refuses the lane. It fails closed. Every other qodercli model
   is refused outright, and the lane is read-only.
3. **Pre-run audit.** A lane that fails is auto-disabled for the run, not tried.
4. **Per-call re-check**, returning `refused_paid` in 0.0 s — the test asserts the zero
   elapsed time, which proves nothing was launched.
5. **Runtime cost breaker.** Every call's real billing fields are read: `cost` from
   `step_finish` for the two forks, `total_credits`/`total_cost_usd`/per-model `credits`
   for qodercli, whose served model key must be `qfmodel`. Any non-zero value trips a
   breaker that refuses every later call and fails the run.

Silent paid paths closed: `--title` always passed (OpenCode otherwise calls paid
`gpt-5.4-nano`), and every emitted title stripped of the keywords that trigger the old
runner's Max escalation.

### 3.5 Safety that is measured, not asserted

- **Permission modes per stage.** Verified live: without `--auto`, any command outside the
  workdir is auto-rejected and the run aborts — that was silently killing recon lanes.
  With `--auto` plus a project permission file, explicit denies hold in both CLIs.
  Read-only stages cannot write or shell out; builders cannot sudo, restart services,
  push, reach Paperclip, or install packages.
- **Credential tripwire.** Every tool input is scanned. A *completed* read of a credential
  path fails the run as a security incident; a *denied* attempt is recorded as evidence the
  permission layer held. Observed live: a lane tried `~/.config/nvidia-nim.env` and
  `~/.ssh/id_rsa`; both refused.
- **Protected-path tripwire.** `agents/`, `bin/`, `~/.ssh` and the engine's own code are
  snapshotted before a run and diffed on every exit path. Any change fails the run.
- **Bounded and reaped.** Hard timeout, idle detection, completion detection on the final
  `stop` event, and process-group kills. Lanes run in their own sessions, so the CLI reaps
  them on exit and on SIGTERM, SIGINT and SIGHUP.
- **VM-wide semaphore.** Four flock slots shared by every engine process, taken only when
  at least 900 MB is free, so concurrent Paperclip seats cannot starve live services.
- **Redaction** on everything written to disk, including raw event streams.

### 3.6 Checks must be runnable before they can judge

A planner will write `python3 -c 'import x; for i in y: ...'`, which is a SyntaxError.
On the first hard benchmark that condemned a fully correct solution and sent the repair
loop after a phantom, costing a test. So `validate_verify_cmd()` compiles any Python
payload and runs `bash -n` on the command first. An unrunnable check is discarded with a
recorded warning and the part is judged on its deliverables and the task's own acceptance;
a valid check that fails still fails the part. The planner prompt now shows good and bad
examples.

## 4. The benchmark

`engctl bench` has three suites, because "it works" needs a number.

**safety** — deterministic, no models. **108 tests, OK**, with ResourceWarnings as errors.
Covers paid refusal, the cost breaker, offer verification failing closed, credential
detection, permission modes, read-only lanes refused builder stages, receipt enforcement,
the tripwire, orphan reaping, the slot cap, health caching, intake rejection, bridge loop
guards, verify-command validation, reviewer gate visibility, and the scoring itself.

**lanes** — 20 enabled, 20 provably free, **12 live across 8 families**, total cost **0.0**.

**quality** — the measurement that answers the Owner's instruction. Real programming
problems with 8–10 **hidden** tests each, written into the workdir only *after* the build.
Every hard suite was first validated against a reference implementation. Two modes on the
same free models: `baseline` (one unassisted call) and `engine` (the full pipeline).

| task | baseline | engine |
|---|---|---|
| expr-eval (arithmetic parser) | **0/10 — 0%** | **9/10 — 90%**, and the built solution passes all 10 when run directly |
| justify-text (typesetting) | **10/10 — 100%** | see the run report |

Cost in both modes: **0.0**. The baseline's parser looked plausible and failed with
`ValueError: Trailing characters`. The engine planned, red-teamed, revised, sampled two
lanes, and produced a correct parser.

Honest limits: two tasks is not a large sample; the easy task shows no gain because the
baseline already solved it; and the engine is far slower — 1,822 s versus 134 s. It buys
correctness with wall-clock time and lane calls, not with money. For a company whose
binding constraint is credits rather than latency, that is the right trade.

## 5. What exists

```
departments/engineering/pipeline/
  engctl                  lanes | probe | validate | draft | run | status | dept | bench | reap
  bin/engine-agent        Paperclip process-adapter entry (the bridge)
  lanes.yaml              20 lanes, 8 live families, dead ones disabled with reasons
  engine/
    guard.py              free-tier enforcement, title sanitisation
    offers.py             time-limited offer verification, fails closed
    lanes.py              probe + cache, bounded invocation, reaping, semaphore, picking
    spec.py               task spec, intake gate, depth dial, frozen brief
    departments.py        kit loading, brief injection, kit validation
    ledger.py             every prompt, reply, event stream, exit code, cost
    gate.py               engine-run checks, snapshots, diffs
    stages.py             recon, plan, red team
    execute.py            build, sampling, judge, review, fix, repair, integrate
    orchestrator.py       sequencing, safety post-checks, final verification
    draft.py              plain English or board issue → validated spec
    bridge.py             Paperclip wake → checkout → run → receipt → status
    bench.py              three benchmark suites
    bench_tasks.py        problems with hidden tests
    report.py             report generation, board comment
    util.py               redaction, atomic writes, clipping
  tests/test_engine.py    108 tests
```

Six department kits are built and verified alongside it (research, academics, design,
club, platform, engineering): `engctl dept` OK for each, **311 tool tests pass**, and the
gates were negative-tested against deliberately bad input.

## 6. Deliberate limits

- Paperclip's native review gates (`reviewPolicy: not_creator`, `executionPolicy.stages`,
  `blockParentUntilDone`) are unused; the engine enforces independence itself. They are
  proposed in `INSTALL_PLAN.md` rather than wired in unilaterally.
- Concurrency is 3 lanes per run and 4 VM-wide. Two vCPUs and ~470 MB per lane process make
  that the honest ceiling, not a tuning choice.
- Nothing modifies the existing runners, agent configs or live departments. Five agents
  remain paused on exhausted models; the cutover is specced with per-phase rollback.
- OpenCode's *account* is not used: its docs require a $20 balance. Only its account-free
  free models are in the pool.
