# Deploy checklist

For opencode-1 executing a subdomain deploy, and the CEO approving and verifying it.
Every box is ticked on the issue before step "Execute" starts.

## Approval and scope
- [ ] The hostname is `<name>.codescriet.dev`, one label deep. Not https://codescriet.dev,
      not www, not a protected name (vpn, api, code, playground-api, company, judge) unless
      the issue names it.
- [ ] The CEO has written "approved" on the issue for this exact block and hostname.
- [ ] The build behind it ended `RESULT: DONE` and was reviewed APPROVE by another family.

## Pre-checks (read-only)
- [ ] The service listens on loopback only: `ss -ltn | grep ':<port> '` shows 127.0.0.1.
- [ ] The service survives a reboot: it is a systemd unit (`systemctl status <unit> --no-pager`),
      not a process in someone's shell.
- [ ] `grep -n '<name>.codescriet.dev' /etc/caddy/Caddyfile` finds nothing (or the issue
      says this replaces an existing block).
- [ ] `caddy_block_lint.py caddy-block-<name>.txt --caddyfile /etc/caddy/Caddyfile` exits 0;
      its output is on the issue.
- [ ] Static sites: files chmod 644, every parent directory o+x (`namei -l <root>/index.html`).
- [ ] Not during the nightly backup window (21:15-21:50 UTC, 02:45-03:20 IST).

## Execute (the linted sequence, nothing else)
- [ ] Cloudflare: proxied record for `<name>`.
- [ ] `cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date -u +%Y%m%d-%H%M%S)`
- [ ] Append the block; `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`
      prints "Valid configuration".
- [ ] `sudo systemctl restart caddy` (never reload: the admin API is off).

## Verify
- [ ] `curl -sS -o /dev/null -w '%{http_code}\n' https://<name>.codescriet.dev/` prints 200.
- [ ] `curl -sSI https://<name>.codescriet.dev/ | grep -i strict-transport-security` prints the header.
- [ ] `curl -sS -o /dev/null -w '%{http_code}\n' https://codescriet.dev/` still prints 200.
- [ ] `systemctl is-active caddy xray club-api club-playground` prints four `active`.
- [ ] Next platform monitor cycle shows no new `-> down` in monitor/alerts.log.

## If anything fails
- [ ] Run the rollback line from the lint output, re-validate, restart, re-run the verify
      curls, and report on the issue with the outputs. Do not improvise a second fix.

## Receipt
- [ ] Issue comment: hostname, upstream port, Caddyfile backup path, the verify outputs,
      and the time in UTC and IST.
