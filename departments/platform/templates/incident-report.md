# Incident report: <fill: service> <fill: one-line symptom>, <fill: YYYY-MM-DD HH:MM> IST

<!-- Save as /home/ubuntu/aaryas-life/departments/platform/work/incidents/incident-report-<YYYYMMDD-HHMM>-<service>.md
Every <fill: ...> marker must be replaced; report_lint.py fails the file while any remain.
Times in UTC with IST in brackets. Every number names the file or command it came from. -->

- Severity: <fill: SEV-1 | SEV-2 | SEV-3> (see skills/incident-triage.md)
- Status: <fill: open, waiting on the CEO | resolved by the CEO at HH:MM UTC>
- Detected by: <fill: monitor/alerts.log line, health_report breach, member report via club-1>
- Services affected: <fill: e.g. club-api, so sign-in on https://codescriet.dev fails>
- Must-never-harm services checked: VPN <fill: active>, clubsite <fill: HTTP 200>,
  playground <fill: active>, club-api <fill: active>, last backup <fill: OK at ...>

## Timeline (UTC, IST in brackets)

| time | event | source |
|---|---|---|
| <fill: 08:35:01 (14:05)> | <fill: monitor logs club-api ok -> down> | `monitor/alerts.log` |
| <fill: 08:37> | <fill: confirmed: systemctl is-active club-api -> failed> | live check |

## Evidence

<fill: the exact commands run and the lines that matter, quoted. Read-only commands only.
Redact anything that looks like a credential as [REDACTED].>

## Impact

<fill: who is affected and how: members, the playground, VPN users, the backup. Say what is
NOT affected too.>

## Cause

<fill: the cause if proven, with the evidence line. Otherwise "INFERENCE:" and the most
economical explanation, plus what would confirm it.>

## What platform-1 did not do

Nothing on the VM was restarted, reloaded, killed, deleted or edited by platform-1.

## Commands for the CEO

Diagnose first, then fix, then verify. Each block is safe to paste as written.

```
<fill: journalctl -u club-api -n 100 --no-pager>
```

```
<fill: sudo systemctl restart club-api>
```

```
<fill: systemctl is-active club-api && curl -sS -o /dev/null -w '%{http_code}\n' https://api.codescriet.dev/>
```

## Follow-up

<fill: what would stop this recurring, and who should build it (an Engineering [build] issue),
or "none".>
