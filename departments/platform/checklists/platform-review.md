# Platform review checklist

Run on every Platform deliverable before it is commented as done. A reviewer who answers
"no" to any line returns the report with the line number and the fix.

## Report-only, enforced
- [ ] Nothing on the VM was changed by the lane: no restart, reload, kill, rm, crontab edit,
      Caddyfile edit, deploy. The run's tripwire and banned-path diff in RUN_REPORT.md are clean.
- [ ] Every action is in "Commands for the CEO", in diagnose, fix, verify order, each in a
      fenced block that pastes cleanly.
- [ ] No command uses `systemctl reload caddy` or `caddy reload`; Caddy changes show
      `caddy validate` before `sudo systemctl restart caddy`.
- [ ] Any `engctl reap` is shown without `--kill` first, with the Paperclip check before `--kill`.
- [ ] Any cleanup goes through `tmp_sandbox_report.py --print0-stale | xargs -0 -r rm -rf --`,
      never a hand-written `rm -rf /tmp/...` glob.

## Evidence
- [ ] Every number names its source: a file path or the command quoted in the report.
- [ ] Times are in UTC with IST alongside.
- [ ] A suspected cause is marked INFERENCE unless a log line proves it.
- [ ] Each problem has a severity (SEV-1, SEV-2, SEV-3) that matches skills/incident-triage.md.
- [ ] The must-never-harm services were checked and their state is stated: the ccsu-bypass
      VPN, https://codescriet.dev, the playground, club-api, the last backup.

## Safety of the text
- [ ] No credential, token, password hash, private key or database URL; `report_lint.py` passes.
- [ ] No content copied from the `company.codescriet.dev` basic-auth block or the /mcp bearer check.
- [ ] Hostnames are subdomains; the main domain appears only as https://codescriet.dev being checked.

## Gates
- [ ] `python3 tools/report_lint.py <report>` exits 0.
- [ ] For a subdomain request, `python3 tools/caddy_block_lint.py caddy-block-<name>.txt
      --caddyfile /etc/caddy/Caddyfile` exits 0 and its output is pasted unchanged.
- [ ] The issue comment names the exact path and size of the report, and the verdict.
