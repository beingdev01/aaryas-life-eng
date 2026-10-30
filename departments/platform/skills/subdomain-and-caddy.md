# Subdomain and Caddy rules

1. Subdomains only. https://codescriet.dev is the clubsite alone; never the apex or www.
   One label deep: Cloudflare's edge certificate covers `*.codescriet.dev` only.
2. A subdomain is one block, address `http://<name>.codescriet.dev` (plain http: Cloudflare
   terminates TLS; :443 is the VPN), `reverse_proxy 127.0.0.1:<port>`, plus HSTS. No `tls`,
   `bind`, `admin`, or :2019.
3. After a change: back up the Caddyfile, `caddy validate`, then `sudo systemctl restart caddy`.
   Reload fails: `admin off` means the admin API on :2019 is not listening.
4. Caddy runs as user caddy: static roots need o+x on every parent directory and o+r on every
   file (chmod 644). Serve from a dedicated directory under /var/www/.
5. Never touch the VPN, apex, code., playground-api., api. or company. blocks unless the
   issue names them.
6. platform-1 lints and writes commands. opencode-1 deploys only with CEO approval; the CEO
   verifies by curling the live URL.

## Worked example
Host a service on 127.0.0.1:18790 at certs.codescriet.dev. Write `caddy-block-certs.txt`:

```
# certificates service (AAR-<n>)
http://certs.codescriet.dev {
	header {
		Strict-Transport-Security "max-age=15552000"
	}
	reverse_proxy 127.0.0.1:18790
}
```

Run `python3 tools/caddy_block_lint.py caddy-block-certs.txt --caddyfile /etc/caddy/Caddyfile`.
It reads the Caddyfile only to catch a duplicate hostname and never runs caddy. On a clean
lint it prints the CEO's sequence: proxied DNS record, timestamped `cp` backup, append,
`caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`, restart, curl of the new
URL and of https://codescriet.dev, `systemctl is-active xray club-api club-playground`, and a
rollback line. Paste it unchanged into `templates/subdomain-request.md`.

## What the linter rejects, and why
- `https://` or a bare hostname: Caddy tries to take :443, colliding with the VPN.
- a non-loopback upstream or no port: exposes another host, or loops into Caddy on :80.
- `file_server` over /home/ubuntu, the company tree, a .git or the clubsite tree.
- Never copy the `company.` block: it holds a password hash.
