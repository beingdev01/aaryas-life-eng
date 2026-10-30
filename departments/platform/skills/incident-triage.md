# Incident triage and severity

Platform observes and reports. No agent owns production (ROUTING section 13): platform-1
detects, diagnoses and writes the report; the CEO (Muse) decides and runs every command.

## What counts as an incident
- a monitor service goes `down` (alerts.log logs `ok -> down`), or health.json is over
  20 minutes old (the 5-minute cron has stopped);
- `health_report.py` exits 1: disk over 85%, MemAvailable under 1 GiB, a certificate under
  14 days, a kilo/opencode process older than 1 hour, backup failed or over 30 h old;
- harm to a must-never-harm service: the ccsu-bypass Xray VPN, https://codescriet.dev, the
  Code.SCRIET playground, club-api, the nightly backup;
- a credential visible where it should not be.

## Severity and speed
| sev | meaning | examples | tell the CEO |
|---|---|---|---|
| SEV-1 | users affected or data at risk | clubsite, club-api, playground or VPN down; backup FAIL; credential exposed | at once: report, issue comment, `RESULT: ESCALATED - <question>` |
| SEV-2 | degraded, will break | disk > 85%, MemAvailable < 1 GiB, hung lanes > 1 GiB, cert < 14 days, monitor stale | within 4 hours |
| SEV-3 | hygiene | /tmp growth, empty domain-watch, one flap that recovered | next daily report |

One transition that recovers within a 5-minute cycle (13 Oct: HTTP 521; 20 Oct: HTTP 404)
is SEV-3 unless it repeats.

## Steps
1. Confirm with a second signal (curl the public URL, `systemctl is-active <unit>`, the log
   tail). Paperclip shows hung lanes as `running`; one source is never enough.
2. Fill `templates/incident-report.md`: timeline in UTC and IST, evidence with the exact
   file or command, impact, cause marked INFERENCE where it is one.
3. End with "Commands for the CEO": diagnosis (`journalctl -u <unit> -n 100 --no-pager`),
   then the fix (`sudo systemctl restart <unit>`), then the verifying curl.
4. Run `report_lint.py` on it; comment the exact path on the issue.

## Mistakes to avoid
- Fixing it yourself. Even restarting paperclipai stops every running agent lane.
- `systemctl reload caddy`: the admin API is off, so reload fails.
- Re-running the backup in the day: it overwrites the backup DB, last night's only copy.
