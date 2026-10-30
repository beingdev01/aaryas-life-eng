# Deploy and hosting procedure

Execution: opencode-1 (ROUTING section 5), only after the CEO approves on the issue.
A non-trivial deploy is planned by Engineer first. Verification: the CEO.

## Rules
- Subdomains only; https://codescriet.dev is the clubsite alone, never the apex or www.
- One block: `http://<name>.codescriet.dev` (Cloudflare terminates TLS; :443 is the VPN),
  `reverse_proxy 127.0.0.1:<port>`, an HSTS header. The service binds 127.0.0.1 only.
- `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`, then
  `sudo systemctl restart caddy`. Never reload: `admin off`, so :2019 is not listening.
- Static sites live in /var/www/<name>, files chmod 644, o+x on every parent (user caddy).
- Never touch the VPN, apex, code., playground-api., api. or company. blocks, club-api or
  the nightly backup unless the issue names them.

## Steps
1. The build is `RESULT: DONE` from the engine and reviewed.
2. Write `caddy-block-<name>.txt`; lint it with
   `departments/platform/tools/caddy_block_lint.py <file> --caddyfile /etc/caddy/Caddyfile`.
3. Post block, lint output and command sequence on the issue. No written CEO approval, no deploy.
4. Run exactly the linted sequence: proxied DNS record, timestamped backup, append,
   validate, restart.
5. Verify, pasting output into the receipt: the new URL returns 200 with HSTS,
   https://codescriet.dev still 200, `systemctl is-active xray club-api club-playground`.
6. Any check fails: run the rollback line from the lint output, then report.

Merging to main of clubsite-git is also a deploy (auto-deploy ships origin/main within
3 minutes) and needs the same approval.
