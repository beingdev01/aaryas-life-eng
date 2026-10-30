# Subdomain request: <fill: name>.codescriet.dev

<!-- Save as /home/ubuntu/aaryas-life/departments/platform/work/subdomains/<name>-subdomain-request.md
next to caddy-block-<name>.txt. The engine lints caddy-block*.txt with caddy_block_lint.py.
Replace every <fill: ...>. Main domain requests are refused, not filed. -->

- Requested by: <fill: department / agent, issue AAR-n>
- Purpose: <fill: what the site is for and who uses it>
- Upstream: 127.0.0.1:<fill: port>, service <fill: unit name or process>, owner <fill: dept>
- Kind: <fill: reverse proxy | static (root under /var/www/<name>)>
- Expected life: <fill: permanent | until DD Mon YYYY, then the CEO removes the block>

## Pre-checks (read-only, run by platform-1)

| check | command | result |
|---|---|---|
| port listens on loopback only | `ss -ltn \| grep ':<fill: port> '` | <fill: 127.0.0.1:<port> LISTEN> |
| name is free | `grep -n '<fill: name>.codescriet.dev' /etc/caddy/Caddyfile` | <fill: no match> |
| not a protected name | www, vpn, api, code, playground-api, company, judge | <fill: ok> |
| static only: caddy can read it | `namei -l /var/www/<name>/index.html` | <fill: o+x on every dir, file 644> |

## Proposed block

File: `/home/ubuntu/aaryas-life/departments/platform/work/subdomains/caddy-block-<fill: name>.txt`

```
http://<fill: name>.codescriet.dev {
	header {
		Strict-Transport-Security "max-age=15552000"
	}
	reverse_proxy 127.0.0.1:<fill: port>
}
```

## Lint result

```
<fill: full output of python3 tools/caddy_block_lint.py caddy-block-<name>.txt --caddyfile /etc/caddy/Caddyfile>
```

## Risks to must-never-harm services

<fill: e.g. "none: new hostname, new port, no shared upstream". If the upstream port belongs
to an existing service, say which and why that is intended.>

## Commands for the CEO

Paste the command sequence the linter printed, unchanged: DNS record, Caddyfile backup,
append, `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`,
`sudo systemctl restart caddy` (never reload: the admin API is off), the verification curls
and the rollback line.

```
<fill: linter command sequence>
```

Execution: opencode-1 or the CEO, only after the CEO approves this request. Verification:
the CEO curls `https://<name>.codescriet.dev/` and https://codescriet.dev/.
