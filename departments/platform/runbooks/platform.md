# Runbook: Platform

How a Platform task moves from a board issue to a receipt, using the shared engine
(`engctl`, in `organisation-rebuild/departments/engineering/pipeline/`) with this kit
loaded. Platform tasks are small: depth 1, one recon slice, one build lane, no review
round, one fix round. The tools do the checking; the lane writes the report.

## 1. Intake

A task reaches platform-1 as a Paperclip issue in `todo` (never `backlog`: backlog issues
get no wake). The CEO or platform-1 turns it into a spec, either with
`engctl draft --issue AAR-<n>` or by hand from Engineering's `templates/task-spec.yaml`.
A Platform spec always has:

- a deliverable under `/home/ubuntu/aaryas-life/departments/platform/work/` whose name
  contains `report` (so the engine adds the `report-lint` gate automatically), with a
  realistic `min_bytes` (a health report is 3-8 KB; 1500 is a sane floor);
- an acceptance command that runs a tool, for example the health report itself;
- banned paths: the cron scripts and their outputs, /etc/caddy, the clubsite trees.

## 2. Gates the engine runs

| gate | from | fails when |
|---|---|---|
| deliverable size | spec `deliverables` | report missing or under `min_bytes` |
| `dept:report-lint:<file>` | this kit, `*report*.md` | no "Commands for the CEO", placeholder text, credential-looking text, a trivial report |
| `dept:caddy-block-lint:<file>` | this kit, `caddy-block*.txt` | apex/www host, https://, non-loopback upstream, no HSTS, admin or :2019, sensitive file_server |
| spec acceptance | spec `acceptance` | whatever the spec says |
| tripwire | engine | any write under agents/, bin/, ~/.ssh or the engine's code fails the run |

`health_report.py` exits 1 on a threshold breach. For a scheduled health report that is
the finding, not a failure of the task, so the acceptance command checks the report, not
the exit code:

```
python3 <dept>/tools/health_report.py --out <work_root>/health/h.md --json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('VERDICT', d['verdict'])"
```

with `expect_stdout: VERDICT`. The verdict itself goes into the report and the comment.

## 3. Worked example: daily health report

Issue AAR-<n>: "Platform health report, 31 Oct". Spec essentials:

```
title: Platform health report for 31 Oct
depth: 1
deliverables:
  - path: /home/ubuntu/aaryas-life/departments/platform/work/health/health-report-20261031.md
    min_bytes: 1500
acceptance:
  - name: report_written_and_parsed
    cmd: python3 .../platform/tools/health_report.py --out .../health-report-20261031.md --json | python3 -c "import json,sys; print('VERDICT', json.load(sys.stdin)['verdict'])"
    expect_stdout: VERDICT
```

Run `engctl run <spec> --board-issue AAR-<n>`. The lane runs the tool, reads the report,
adds a two-line summary at the top if the template asks for one, and stops. The engine then
re-runs the acceptance, checks the size, runs `report_lint.py` on the file, writes
`RUN_REPORT.md` and posts the board comment. platform-1's own comment names the report path
and the verdict, for example "BREACH (1): 6 lane processes older than 1h holding 2,520 MiB;
CEO commands in section 'Commands for the CEO'". Then `RESULT: DONE`, or
`RESULT: ESCALATED - <question>` for SEV-1.

## 4. Incident flow

1. Read monitor/alerts.log and health.json; confirm with a second signal.
2. Assign severity (skills/incident-triage.md). SEV-1: write the incident report first and
   escalate within minutes; do not wait for a full engine run if the tools alone answer it.
3. Fill `templates/incident-report.md`; list commands for the CEO in diagnosis, fix,
   verify order; run `report_lint.py`.
4. Comment the path; end with `RESULT: ESCALATED - <exact question>`.

## 5. Subdomain request flow

1. Engineering or the CEO asks for `<name>.codescriet.dev -> 127.0.0.1:<port>`.
2. Confirm the port is listening on loopback (`ss -ltn | grep :<port>`) and the name is free
   (`grep -n '<name>.codescriet.dev' /etc/caddy/Caddyfile`).
3. Write `caddy-block-<name>.txt`, run `caddy_block_lint.py --caddyfile /etc/caddy/Caddyfile`,
   paste its command sequence into `templates/subdomain-request.md`.
4. Hand to the CEO for approval; opencode-1 or the CEO executes; the CEO curls the URL.

## 6. Failure modes

- **A source file is stale or missing.** health.json older than 20 minutes means the monitor
  cron stopped; that is itself a SEV-2 breach. Report it; do not run the monitor yourself on
  top of cron unless the issue asks.
- **The lane is quota-exhausted or hangs.** The engine probes lanes before dispatch and
  kills a hung call at its timeout. If no lane is live, `engctl run` ends
  `RESULT: BLOCKED - no live model lane`. The tools still work without a model: run
  `health_report.py` directly and file its report by hand.
- **report-lint fails.** Usually the "Commands for the CEO" section is empty or a template
  placeholder survived. The fix round gets the lint output; fix the file, never the gate.
- **A breach you cannot classify.** Report the raw numbers and the command that produced
  them, mark the cause INFERENCE, and escalate.
- **Temptation to act.** A one-line restart looks harmless. It is not Platform's to run:
  restarting paperclipai kills every running lane; restarting xray drops every VPN user.
