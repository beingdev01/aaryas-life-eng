# Service map of this VM

From read-only inspection on 2026-10-30 (`ss -ltnp`, `systemctl list-units`, `--user`,
`crontab -l`, /etc/caddy/Caddyfile). 2 vCPU, 11.6 GiB RAM, 193 GB disk (25% used).
Re-check before relying on a port; report anything missing or new.

## Public path
Cloudflare (proxied DNS, TLS at the edge) -> VM :80 Caddy (`admin off`, no :2019) for every
`http://<name>.codescriet.dev` block. VM :443 is Xray (ccsu-bypass, vpn.codescriet.dev), not
Caddy; unknown-SNI traffic falls back to Caddy on :8080.

| port | service | reached as |
|---|---|---|
| :80 | caddy.service | every site block |
| :443 | xray.service (VPN) | vpn.codescriet.dev:443 |
| :5001 | club-api.service | api.codescriet.dev |
| :5002 | club-playground.service | playground-api.codescriet.dev |
| 127.0.0.1:3100 | paperclipai (user unit) | company.codescriet.dev (basic auth) |
| 127.0.0.1:54329 | Paperclip's own PostgreSQL | local only |
| 127.0.0.1:3000 | judge | judge.codescriet.dev |
| 127.0.0.1:8081 | mcp-http-bridge.service | :80 /mcp (bearer auth) |
| 127.0.0.1:8501 | doc-classifier (user unit) | doc-classifier.codescriet.dev |
| 8100-8103, 18761-18766 | TDS course services | /tds-q* paths, tds-ga1-* hosts |

https://codescriet.dev serves /home/ubuntu/clubsite/apps/web/dist; code.codescriet.dev
serves apps/playground/dist. The clubsite database is on Neon, not this VM.
/home/ubuntu/clubsite has a broken .git: a deploy target, never a working copy.

## Scheduled jobs (ubuntu crontab, clock is UTC)
- every 3 min: auto-deploy.sh polls origin/main of ~/clubsite-git and deploys
- every 5 min: platform monitor/check.py -> health.json, alerts.log
- 09:30 daily: cert-watch/check.py -> status.json
- 21:30 daily (03:00 IST): db-nightly-backup.sh, live Neon -> backup Neon, status in
  /home/ubuntu/db-backups/last-status.txt. The backup DB is a mirror overwritten nightly:
  never move audit or archive rows into it.
- Sunday 11:00: whois -> state/domain-watch.md. No run has recorded an expiry date:
  whois.nic.dev does not resolve from the VM, so domain expiry is unknown.

Read these jobs' output files; never run or edit the scripts themselves.
