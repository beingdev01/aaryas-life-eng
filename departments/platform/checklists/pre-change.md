# Pre-change checklist (for the CEO, before running any Platform command)

Platform never changes the VM. When a report asks the CEO to, this is the list the CEO
works through first. platform-1 attaches it, filled in as far as read-only checks allow.

## Before
- [ ] The change is in a Platform report that passed `report_lint.py`, and the exact
      commands come from its "Commands for the CEO" section.
- [ ] Time: not between 21:15 and 21:50 UTC (02:45-03:20 IST), when the nightly backup runs.
      `cat /home/ubuntu/db-backups/last-status.txt` shows the last run.
- [ ] Not inside an auto-deploy: `tail -n 5 /home/ubuntu/auto-deploy.log` shows no deploy in
      the last 3 minutes.
- [ ] Who is affected is known: restarting xray drops every ccsu-bypass VPN user; restarting
      paperclipai stops every running agent lane; restarting club-api drops live Socket.io
      sessions; restarting caddy blips every subdomain and https://codescriet.dev.
- [ ] A backup of what changes exists: for Caddy,
      `cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date -u +%Y%m%d-%H%M%S)`.
- [ ] For Caddy: `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile` prints
      "Valid configuration". Then restart, never reload (admin API is off).
- [ ] For a lane kill: `engctl reap --older-than 3600` listed the pids, and Paperclip shows
      no in_progress issue that depends on those runs.
- [ ] For a /tmp cleanup: the command is the one `tmp_sandbox_report.py` printed, so held
      directories are re-checked at run time.
- [ ] The rollback command is written down before the change runs.

## After
- [ ] `systemctl is-active caddy xray club-api club-playground` all print `active`.
- [ ] `curl -sS -o /dev/null -w '%{http_code}\n' https://codescriet.dev/` prints 200.
- [ ] The changed thing is verified by its own check (the new subdomain's curl, MemAvailable
      after a reap, `du -sh /tmp` after a cleanup).
- [ ] The next monitor cycle (within 5 minutes) shows no new `-> down` line in alerts.log.
- [ ] The issue gets a comment: what ran, when (UTC and IST), and the verification output.
