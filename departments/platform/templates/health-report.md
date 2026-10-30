# Health report: <fill: hostname>, <fill: YYYY-MM-DD HH:MM> IST

<!-- Produced by tools/health_report.py, which writes every section below from the cron
outputs and live read-only checks:

  python3 /home/ubuntu/aaryas-life/organisation-rebuild/departments/platform/tools/health_report.py \
    --out /home/ubuntu/aaryas-life/departments/platform/work/health/health-report-<YYYYMMDD-HHMM>.md

The lane's job is only the "Reading" paragraph at the top: three to five plain sentences
on what changed since the last report and what the CEO should look at first. Never edit
the numbers the tool wrote. Replace every <fill: ...>; report_lint.py fails leftovers. -->

## Reading

<fill: e.g. "One breach: six opencode lane processes pinned to exhausted models have been
alive 11-14 hours and hold 2.5 GiB. Everything user-facing is up; the backup ran OK at
03:04 IST. Domain expiry is still unknown because whois returns nothing.">

- Generated: <tool> UTC (<tool> IST)
- Verdict: **OK** or **BREACH (n)**, n warning(s)

## Summary

| check | value | threshold | status |
|---|---|---|---|
| monitor freshness | <tool> | <= 20m | ok / BREACH |
| services down | <tool> | 0 | |
| certificate expiry (min days) | <tool> | >= 14d | |
| domain expiry | <tool> | >= 60d | |
| nightly backup | <tool> | OK, <= 30h | |
| disk used / | <tool> | <= 85% | |
| MemAvailable | <tool> | >= 1024 MiB | |
| load (15 min) | <tool> | <= 2 x vCPU (warn only) | |
| hung lane processes | <tool> | 0 older than 1h | |

## Services, recent state changes, certificates, domain, backup, disk, memory, load, lane processes

One section each, written by the tool, each naming its source file.

## Breaches

One line per breach: check, measured value, limit.

## Warnings

One line per warning.

## Commands for the CEO

One fenced block per breach or warning, in the order the CEO should run them. When nothing
is breached the tool writes "No commands needed: every threshold is within limits." and the
command that regenerates the report.

## Sources

The exact paths read.
