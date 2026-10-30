#!/usr/bin/env python3
"""Platform health report for the Aarya's Life VM. Read-only.

Aggregates the files the platform cron jobs already write (monitor/health.json,
monitor/alerts.log, cert-watch/status.json, state/domain-watch.md, the nightly
backup status line) with live read-only host checks (disk, MemAvailable, load
average, long-lived kilo/opencode lane processes read from /proc) into one
markdown report at the path given with --out.

It never restarts, reloads, kills, deletes or edits anything. When a threshold
is breached it still writes the full report, lists the exact commands the CEO
should run, and exits 1.

Exit codes: 0 all thresholds within limits, 1 at least one breach,
2 usage error or the report could not be written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM_LIVE = "/home/ubuntu/aaryas-life/departments/platform"
ENGCTL = "/home/ubuntu/aaryas-life/organisation-rebuild/departments/engineering/pipeline/engctl"
TOOLS_DIR = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULTS = {
    "monitor": f"{PLATFORM_LIVE}/monitor/health.json",
    "alerts": f"{PLATFORM_LIVE}/monitor/alerts.log",
    "certs": f"{PLATFORM_LIVE}/cert-watch/status.json",
    "domain": "/home/ubuntu/aaryas-life/state/domain-watch.md",
    "backup": "/home/ubuntu/db-backups/last-status.txt",
}

LANE_NAMES = {"kilo", ".kilo", "opencode", ".opencode"}
WRAPPERS = {"node", "bun", "nodejs"}

# What the CEO should look at first when the monitor reports a service problem.
# Restart lines are commands for the CEO, never for an agent.
SERVICE_COMMANDS = {
    "codescriet.dev": [
        "curl -sS -o /dev/null -w '%{http_code}\\n' https://codescriet.dev/",
        "systemctl status caddy --no-pager",
        "tail -n 30 /home/ubuntu/auto-deploy.log",
    ],
    "club-api": [
        "systemctl status club-api --no-pager",
        "journalctl -u club-api -n 100 --no-pager",
        "sudo systemctl restart club-api    # only after reading the journal",
    ],
    "xray-vpn": [
        "systemctl status xray --no-pager",
        "journalctl -u xray -n 100 --no-pager",
        "sudo systemctl restart xray    # drops every connected ccsu-bypass VPN user",
    ],
    "paperclip-dashboard": [
        "systemctl --user status paperclipai --no-pager",
        "journalctl --user -u paperclipai -n 100 --no-pager",
        "systemctl --user restart paperclipai    # stops every running agent lane",
    ],
    "disk": ["df -h /", "du -xsh /tmp /home/ubuntu/* 2>/dev/null | sort -h | tail -15"],
}


@dataclass
class Finding:
    check: str
    message: str
    commands: list = field(default_factory=list)


@dataclass
class Section:
    title: str
    lines: list = field(default_factory=list)


class Collector:
    def __init__(self):
        self.breaches: list[Finding] = []
        self.warnings: list[Finding] = []
        self.summary: list[tuple] = []     # (check, value, threshold, status)
        self.sections: list[Section] = []

    def breach(self, check, message, commands=None):
        self.breaches.append(Finding(check, message, list(commands or [])))

    def warn(self, check, message, commands=None):
        self.warnings.append(Finding(check, message, list(commands or [])))


# ---------------------------------------------------------------- helpers

def parse_iso(text: str) -> datetime | None:
    if not text:
        return None
    text = str(text).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d{(seconds % 86400) // 3600:02d}h"


def read_json(path: Path):
    try:
        return json.loads(path.read_text()), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as exc:
        return None, f"unreadable ({type(exc).__name__})"


# ---------------------------------------------------------------- file sources

def check_monitor(col: Collector, path: Path, now: datetime, max_age_min: int):
    sec = Section("Services (platform monitor, every 5 minutes)")
    col.sections.append(sec)
    data, err = read_json(path)
    rerun = [f"crontab -l | grep monitor/check.py",
             f"/usr/bin/python3 {PLATFORM_LIVE}/monitor/check.py"]
    if err:
        sec.lines.append(f"Source `{path}` is {err}.")
        col.breach("monitor", f"monitor snapshot {path} is {err}", rerun)
        col.summary.append(("monitor snapshot", err, "present", "BREACH"))
        return
    gen = parse_iso(data.get("generated_at", ""))
    age = (now - gen).total_seconds() if gen else None
    services = data.get("services") or []
    sec.lines += [f"Source: `{path}`, generated {data.get('generated_at', '?')}"
                  + (f" ({fmt_age(age)} ago)." if age is not None else "."), "",
                  "| service | status | detail |", "|---|---|---|"]
    for svc in services:
        sec.lines.append(f"| {svc.get('service', '?')} | {svc.get('status', '?')} | "
                         f"{str(svc.get('detail', '')).replace('|', '/')} |")
    if age is None or age > max_age_min * 60:
        shown = fmt_age(age) if age is not None else "unknown"
        col.breach("monitor", f"monitor snapshot is stale ({shown} old, limit "
                   f"{max_age_min}m): the 5-minute cron may have stopped", rerun)
        col.summary.append(("monitor freshness", shown, f"<= {max_age_min}m", "BREACH"))
    else:
        col.summary.append(("monitor freshness", fmt_age(age), f"<= {max_age_min}m", "ok"))
    bad = 0
    for svc in services:
        name, status = svc.get("service", "?"), svc.get("status", "unknown")
        cmds = SERVICE_COMMANDS.get(name, [])
        if status == "down":
            bad += 1
            col.breach(f"service {name}", f"{name} is down: {svc.get('detail', '')}", cmds)
        elif status != "ok":
            col.warn(f"service {name}", f"{name} is {status}: {svc.get('detail', '')}", cmds)
    col.summary.append(("services down", str(bad), "0", "BREACH" if bad else "ok"))


def check_alerts(col: Collector, path: Path, tail: int):
    sec = Section("Recent state changes (monitor/alerts.log)")
    col.sections.append(sec)
    try:
        lines = [ln for ln in path.read_text(errors="replace").splitlines() if ln.strip()]
    except OSError:
        sec.lines.append(f"`{path}` not readable; no transition history.")
        return
    sec.lines.append(f"{len(lines)} transitions logged in total; last {min(tail, len(lines))}:")
    sec.lines.append("")
    sec.lines += [f"- {ln}" for ln in lines[-tail:]] or ["- none"]


def check_certs(col: Collector, path: Path, now: datetime, min_days: int, max_age_h: int):
    sec = Section("Certificates (cert-watch, daily 09:30 UTC)")
    col.sections.append(sec)
    data, err = read_json(path)
    cmds = ["echo | openssl s_client -connect codescriet.dev:443 -servername codescriet.dev "
            "2>/dev/null | openssl x509 -noout -enddate -issuer",
            "# The edge certificate is Cloudflare's (TLS terminates at Cloudflare). Renew or "
            "re-issue it in Cloudflare SSL/TLS > Edge Certificates; nothing on the VM renews it."]
    if err:
        sec.lines.append(f"Source `{path}` is {err}.")
        col.breach("certificates", f"cert-watch status {path} is {err}",
                   [f"/usr/bin/python3 {PLATFORM_LIVE}/cert-watch/check.py"])
        col.summary.append(("certificate expiry", err, f">= {min_days}d", "BREACH"))
        return
    gen = parse_iso(data.get("generated_at", ""))
    age = (now - gen).total_seconds() if gen else None
    sec.lines += [f"Source: `{path}`, generated {data.get('generated_at', '?')}.", "",
                  "| host | status | days left | not after |", "|---|---|---|---|"]
    lowest = None
    for cert in data.get("certs") or []:
        host = cert.get("service", "?")
        days = cert.get("expires_in_days")
        sec.lines.append(f"| {host} | {cert.get('status', '?')} | "
                         f"{days if days is not None else '-'} | "
                         f"{cert.get('not_after', cert.get('detail', '-'))} |")
        if not isinstance(days, (int, float)):
            col.breach(f"certificate {host}",
                       f"cert-watch could not read the certificate for {host}: "
                       f"{cert.get('detail', 'no expiry recorded')}", cmds)
            continue
        lowest = days if lowest is None else min(lowest, days)
        if days < min_days:
            col.breach(f"certificate {host}",
                       f"certificate for {host} expires in {days} days (limit {min_days})", cmds)
    col.summary.append(("certificate expiry (min days)",
                        "-" if lowest is None else str(lowest), f">= {min_days}d",
                        "BREACH" if lowest is None or lowest < min_days else "ok"))
    if age is None or age > max_age_h * 3600:
        col.breach("cert-watch", f"cert-watch status is stale "
                   f"({fmt_age(age) if age is not None else 'unknown age'}, limit {max_age_h}h)",
                   ["crontab -l | grep cert-watch",
                    f"/usr/bin/python3 {PLATFORM_LIVE}/cert-watch/check.py"])


EXPIRY_RE = re.compile(r"expir\w*[^:]*:\s*(\d{4}-\d{2}-\d{2})", re.I)
DOMAIN_HDR = re.compile(r"^==\s*domain-watch\s+(\S+)\s*==\s*$")


def check_domain(col: Collector, path: Path, now: datetime, min_days: int):
    sec = Section("Domain registration (domain-watch, weekly Sunday 11:00 UTC)")
    col.sections.append(sec)
    try:
        text = path.read_text(errors="replace")
    except OSError:
        sec.lines.append(f"`{path}` not readable.")
        col.warn("domain", f"domain-watch file {path} is missing or unreadable")
        return
    entries, current = [], None
    for line in text.splitlines():
        m = DOMAIN_HDR.match(line.strip())
        if m:
            current = {"at": m.group(1), "lines": []}
            entries.append(current)
        elif current is not None and line.strip():
            current["lines"].append(line.strip())
    if not entries:
        sec.lines.append("No domain-watch runs recorded.")
        col.warn("domain", "domain-watch has no recorded runs")
        return
    with_data = [e for e in entries if any(EXPIRY_RE.search(ln) for ln in e["lines"])]
    latest = entries[-1]
    sec.lines.append(f"{len(entries)} runs recorded; {len(with_data)} contained an expiry "
                     f"date. Latest run: {latest['at']}.")
    last_run = parse_iso(latest["at"])
    if last_run and (now - last_run).days > 8:
        col.warn("domain", f"latest domain-watch run is {(now - last_run).days} days old; "
                 "the weekly cron may have stopped")
    if not with_data:
        col.warn("domain", f"none of the {len(entries)} domain-watch runs recorded an expiry "
                 "date (whois returned nothing); domain expiry is unknown",
                 ["whois codescriet.dev | grep -i expir",
                  "getent hosts whois.nic.dev    # whois for .dev needs this name to resolve"])
        col.summary.append(("domain expiry", "unknown", f">= {min_days}d", "warn"))
        return
    m = None
    for ln in with_data[-1]["lines"]:
        m = EXPIRY_RE.search(ln)
        if m:
            break
    expiry = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    days = (expiry - now).days
    sec.lines.append(f"Expiry recorded by run {with_data[-1]['at']}: {m.group(1)} ({days} days).")
    status = "ok"
    if days < min_days:
        status = "BREACH"
        col.breach("domain", f"codescriet.dev registration expires in {days} days "
                   f"(limit {min_days}); renewal is an Owner spending decision",
                   ["whois codescriet.dev | grep -i expir"])
    col.summary.append(("domain expiry", f"{days}d", f">= {min_days}d", status))


BACKUP_RE = re.compile(r"^(OK|FAIL)\s*::\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\s*\w+)?(?:\s*::\s*(.*))?$")


def check_backup(col: Collector, path: Path, now: datetime, max_age_h: int):
    sec = Section("Nightly database backup (03:00 IST = 21:30 UTC)")
    col.sections.append(sec)
    cmds = ["cat /home/ubuntu/db-backups/last-status.txt",
            "tail -n 40 /home/ubuntu/db-backup.log",
            "# Re-running overwrites the backup DB with the live DB; CEO decision only:",
            "/usr/bin/flock -n /home/ubuntu/.dbbackup.lock /home/ubuntu/db-nightly-backup.sh"]
    try:
        line = path.read_text(errors="replace").strip().splitlines()[0]
    except (OSError, IndexError):
        sec.lines.append(f"`{path}` not readable.")
        col.warn("backup", f"backup status file {path} is missing or empty", cmds[:2])
        col.summary.append(("nightly backup", "unknown", f"OK, <= {max_age_h}h", "warn"))
        return
    m = BACKUP_RE.match(line)
    if not m:
        sec.lines.append(f"Unrecognised status line: `{line[:120]}`")
        col.warn("backup", "backup status line not in the expected 'OK :: <time> UTC' form", cmds[:2])
        col.summary.append(("nightly backup", "unparsed", f"OK, <= {max_age_h}h", "warn"))
        return
    state = m.group(1)
    at = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    age = (now - at).total_seconds()
    sec.lines.append(f"Last status: {state} at {m.group(2)} UTC ({fmt_age(age)} ago)"
                     + (f", reason: {m.group(3)}" if m.group(3) else "") + ".")
    status = "ok"
    if state == "FAIL":
        status = "BREACH"
        col.breach("backup", f"last nightly backup FAILED: {m.group(3) or 'see log'}", cmds)
    elif age > max_age_h * 3600:
        status = "BREACH"
        col.breach("backup", f"last successful backup is {fmt_age(age)} old (limit {max_age_h}h)", cmds)
    col.summary.append(("nightly backup", f"{state}, {fmt_age(age)} ago", f"OK, <= {max_age_h}h", status))


# ---------------------------------------------------------------- live host checks

def check_disk(col: Collector, path: str, max_pct: float):
    sec = Section(f"Disk ({path})")
    col.sections.append(sec)
    try:
        du = shutil.disk_usage(path)
    except OSError as exc:
        col.breach("disk", f"disk usage for {path} unreadable: {exc}")
        return
    denom = du.used + du.free
    pct = (du.used * 100.0 / denom) if denom else 0.0
    sec.lines.append(f"{pct:.1f}% used (df-style used/(used+available)), "
                     f"{du.free / 1024**3:.1f} GiB available of {du.total / 1024**3:.1f} GiB.")
    status = "ok"
    if pct > max_pct:
        status = "BREACH"
        col.breach("disk", f"disk {path} is {pct:.1f}% used (limit {max_pct:g}%)",
                   SERVICE_COMMANDS["disk"] +
                   [f"python3 {TOOLS_DIR}/tmp_sandbox_report.py --root /tmp --older-than-hours 24"])
    col.summary.append((f"disk used {path}", f"{pct:.1f}%", f"<= {max_pct:g}%", status))


def read_meminfo(proc: Path) -> dict:
    out = {}
    for line in (proc / "meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            out[key.strip()] = int(parts[0])      # kB
    return out


def check_memory(col: Collector, proc: Path, min_mib: int):
    sec = Section("Memory")
    col.sections.append(sec)
    try:
        mem = read_meminfo(proc)
    except OSError as exc:
        col.breach("memory", f"{proc}/meminfo unreadable: {exc}")
        return
    avail = mem.get("MemAvailable")
    if avail is None:
        col.breach("memory", "MemAvailable missing from meminfo")
        return
    avail_mib = avail / 1024
    total_mib = mem.get("MemTotal", 0) / 1024
    swap_used = (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) / 1024
    sec.lines.append(f"MemAvailable {avail_mib:.0f} MiB of {total_mib:.0f} MiB; "
                     f"swap in use {swap_used:.0f} MiB.")
    status = "ok"
    if avail_mib < min_mib:
        status = "BREACH"
        col.breach("memory", f"MemAvailable {avail_mib:.0f} MiB is below {min_mib} MiB",
                   ["free -m", "ps -eo pid,etimes,rss,args --sort=-rss | head -15",
                    f"{ENGCTL} reap --older-than 3600"])
    col.summary.append(("MemAvailable", f"{avail_mib:.0f} MiB", f">= {min_mib} MiB", status))


def check_load(col: Collector, proc: Path, ncpu: int):
    sec = Section("Load")
    col.sections.append(sec)
    try:
        one, five, fifteen = (float(x) for x in (proc / "loadavg").read_text().split()[:3])
    except (OSError, ValueError) as exc:
        col.warn("load", f"load average unreadable: {exc}")
        return
    sec.lines.append(f"Load average {one:.2f} / {five:.2f} / {fifteen:.2f} (1/5/15 min) "
                     f"on {ncpu} vCPU.")
    status = "ok"
    if fifteen > 2 * ncpu:
        status = "warn"
        col.warn("load", f"15-minute load {fifteen:.2f} is above twice the {ncpu} vCPUs",
                 ["ps -eo pid,etimes,pcpu,rss,args --sort=-pcpu | head -15"])
    col.summary.append(("load (15 min)", f"{fifteen:.2f}", f"<= {2 * ncpu} (warn only)", status))


def _proc_name(argv: list, comm: str) -> str | None:
    if not argv:
        return comm if comm in LANE_NAMES else None
    base0 = os.path.basename(argv[0])
    if base0 in LANE_NAMES:
        return base0.lstrip(".")
    if base0 in WRAPPERS and len(argv) > 1 and os.path.basename(argv[1]) in LANE_NAMES:
        return os.path.basename(argv[1]).lstrip(".")
    if comm in LANE_NAMES:
        return comm.lstrip(".")
    return None


def _arg_value(argv: list, *flags) -> str:
    for i, tok in enumerate(argv):
        for flag in flags:
            if tok == flag and i + 1 < len(argv):
                return argv[i + 1]
            if tok.startswith(flag + "="):
                return tok.split("=", 1)[1]
    return ""


def lane_processes(proc: Path, clk_tck: int, self_pid: int | None = None) -> list[dict]:
    """Every live kilo/opencode process, with age and resident memory, from /proc."""
    uptime = float((proc / "uptime").read_text().split()[0])
    rows = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == self_pid:
            continue
        try:
            argv = [a for a in (entry / "cmdline").read_bytes().split(b"\0") if a]
            argv = [a.decode(errors="replace") for a in argv]
            comm = (entry / "comm").read_text().strip() if (entry / "comm").exists() else ""
            name = _proc_name(argv, comm)
            if not name:
                continue
            stat = (entry / "stat").read_text()
            after = stat[stat.rindex(")") + 2:].split()
            ppid = int(after[1])
            start_ticks = int(after[19])
            rss_kb = 0
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break
        except (OSError, ValueError, IndexError):
            continue          # process exited mid-read, or not ours to read
        sub = argv[1] if len(argv) > 1 and os.path.basename(argv[0]) not in WRAPPERS else (
            argv[2] if len(argv) > 2 else "")
        rows.append({
            "pid": int(entry.name), "ppid": ppid, "cli": name, "subcommand": sub,
            "age_sec": max(0.0, uptime - start_ticks / clk_tck), "rss_kb": rss_kb,
            "model": _arg_value(argv, "-m", "--model"),
            "title": _arg_value(argv, "--title"),
            "workdir": _arg_value(argv, "--dir"),
        })
    return sorted(rows, key=lambda r: -r["age_sec"])


def check_lanes(col: Collector, proc: Path, max_age_h: float, clk_tck: int):
    sec = Section("Lane processes (kilo / opencode)")
    col.sections.append(sec)
    try:
        rows = lane_processes(proc, clk_tck, os.getpid())
    except (OSError, ValueError) as exc:
        col.warn("lanes", f"could not scan {proc} for lane processes: {exc}")
        return
    limit = max_age_h * 3600
    hung = [r for r in rows if r["age_sec"] >= limit]
    total_mb = sum(r["rss_kb"] for r in rows) / 1024
    hung_mb = sum(r["rss_kb"] for r in hung) / 1024
    sec.lines.append(f"{len(rows)} lane processes alive holding {total_mb:.0f} MiB resident; "
                     f"{len(hung)} older than {max_age_h:g}h holding {hung_mb:.0f} MiB.")
    if rows:
        sec.lines += ["", "| pid | ppid | cli | age | rss MiB | model | title |",
                      "|---|---|---|---|---|---|---|"]
        for r in rows[:40]:
            sec.lines.append(f"| {r['pid']} | {r['ppid']} | {r['cli']} {r['subcommand']} | "
                             f"{fmt_age(r['age_sec'])} | {r['rss_kb'] // 1024} | "
                             f"{r['model'] or '-'} | {(r['title'] or '-')[:40]} |")
        sec.lines.append("")
        sec.lines.append("A kilo lane shows as two processes (a small node wrapper and the "
                         ".kilo worker). A quota-exhausted opencode lane does not exit: it "
                         "sleeps on a network read at roughly 400-470 MiB until killed.")
    status = "ok"
    if hung:
        status = "BREACH"
        older = int(limit)
        col.breach("lanes", f"{len(hung)} lane process(es) older than {max_age_h:g}h holding "
                   f"{hung_mb:.0f} MiB (pids {', '.join(str(r['pid']) for r in hung[:10])})",
                   [f"{ENGCTL} reap --older-than {older}",
                    "# confirm in Paperclip that no in_progress issue depends on these runs, then:",
                    f"{ENGCTL} reap --older-than {older} --kill"])
    col.summary.append(("hung lane processes", f"{len(hung)} ({hung_mb:.0f} MiB)",
                        f"0 older than {max_age_h:g}h", status))


# ---------------------------------------------------------------- report

def render(col: Collector, now: datetime, host: str, sources: dict, argv_line: str) -> str:
    verdict = "OK" if not col.breaches else f"BREACH ({len(col.breaches)})"
    ist = now.astimezone(IST)
    out = [f"# Health report: {host}, {ist:%Y-%m-%d %H:%M} IST", "",
           f"- Generated: {now:%Y-%m-%dT%H:%M:%SZ} UTC ({ist:%d %b %Y %H:%M} IST)",
           f"- Verdict: **{verdict}**, {len(col.warnings)} warning(s)",
           "- Produced by: platform `tools/health_report.py` (read-only; nothing was "
           "restarted, killed or changed)", "",
           "## Summary", "", "| check | value | threshold | status |", "|---|---|---|---|"]
    out += [f"| {c} | {v} | {t} | {s} |" for c, v, t, s in col.summary]
    out.append("")
    for sec in col.sections:
        out += [f"## {sec.title}", ""] + (sec.lines or ["Nothing to report."]) + [""]
    out += ["## Breaches", ""]
    out += [f"- **{b.check}**: {b.message}" for b in col.breaches] or ["None."]
    out += ["", "## Warnings", ""]
    out += [f"- **{w.check}**: {w.message}" for w in col.warnings] or ["None."]
    out += ["", "## Commands for the CEO", ""]
    actionable = [f for f in col.breaches + col.warnings if f.commands]
    if not actionable:
        out.append("No commands needed: every threshold is within limits.")
    for f in actionable:
        kind = "breach" if f in col.breaches else "warning"
        out += [f"### {f.check} ({kind})", "", "```"] + f.commands + ["```", ""]
    out += ["", "To regenerate this report:", "", "```", argv_line, "```", "",
            "## Sources", ""]
    out += [f"- {k}: `{v}`" for k, v in sources.items()]
    return "\n".join(out).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="health_report.py",
        description="Read-only platform health report. Aggregates the monitor, cert-watch, "
                    "domain-watch and backup status files with live disk, memory, load and "
                    "lane-process checks into one markdown report. Exits 1 when any "
                    "threshold is breached (the report is still written).")
    p.add_argument("--out", required=True, help="markdown report path to write")
    p.add_argument("--monitor", default=DEFAULTS["monitor"], help="monitor health.json")
    p.add_argument("--alerts", default=DEFAULTS["alerts"], help="monitor alerts.log")
    p.add_argument("--certs", default=DEFAULTS["certs"], help="cert-watch status.json")
    p.add_argument("--domain", default=DEFAULTS["domain"], help="domain-watch markdown log")
    p.add_argument("--backup-status", default=DEFAULTS["backup"],
                   help="nightly backup last-status.txt")
    p.add_argument("--disk-path", default="/", help="filesystem to check (default /)")
    p.add_argument("--proc", default="/proc", help="proc filesystem root (for tests)")
    p.add_argument("--disk-max-pct", type=float, default=85.0)
    p.add_argument("--mem-min-mib", type=int, default=1024)
    p.add_argument("--cert-min-days", type=int, default=14)
    p.add_argument("--domain-min-days", type=int, default=60)
    p.add_argument("--lane-max-age-hours", type=float, default=1.0,
                   help="a kilo/opencode process older than this counts as hung (default 1h; "
                        "no engine lane call may run longer than 15 minutes)")
    p.add_argument("--monitor-max-age-min", type=int, default=20)
    p.add_argument("--cert-max-age-hours", type=int, default=50)
    p.add_argument("--backup-max-age-hours", type=int, default=30)
    p.add_argument("--alerts-tail", type=int, default=8)
    p.add_argument("--json", action="store_true", help="print a JSON summary to stdout")
    return p


def main(argv=None, now: datetime | None = None, clk_tck: int | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = now or datetime.now(timezone.utc)
    out = Path(args.out).resolve()
    sources = {"monitor": args.monitor, "alerts": args.alerts, "certs": args.certs,
               "domain": args.domain, "backup status": args.backup_status}
    for src in sources.values():
        if Path(src).resolve() == out:
            print(f"health_report: refusing to overwrite input file {out}", file=sys.stderr)
            return 2
    proc = Path(args.proc)
    if clk_tck is None:
        clk_tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

    col = Collector()
    check_monitor(col, Path(args.monitor), now, args.monitor_max_age_min)
    check_alerts(col, Path(args.alerts), args.alerts_tail)
    check_certs(col, Path(args.certs), now, args.cert_min_days, args.cert_max_age_hours)
    check_domain(col, Path(args.domain), now, args.domain_min_days)
    check_backup(col, Path(args.backup_status), now, args.backup_max_age_hours)
    check_disk(col, args.disk_path, args.disk_max_pct)
    check_memory(col, proc, args.mem_min_mib)
    check_load(col, proc, os.cpu_count() or 1)
    check_lanes(col, proc, args.lane_max_age_hours, clk_tck)

    argv_line = "python3 " + str(Path(__file__).resolve()) + " " + " ".join(
        sys.argv[1:] if argv is None else argv)
    text = render(col, now, socket.gethostname(), sources, argv_line.strip())
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(text)
        tmp.replace(out)
    except OSError as exc:
        print(f"health_report: cannot write report {out}: {exc}", file=sys.stderr)
        return 2

    summary = {"verdict": "OK" if not col.breaches else "BREACH", "report": str(out),
               "breaches": [f"{b.check}: {b.message}" for b in col.breaches],
               "warnings": [f"{w.check}: {w.message}" for w in col.warnings]}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"health_report: {summary['verdict']} ({len(col.breaches)} breach(es), "
              f"{len(col.warnings)} warning(s)) -> {out}")
    if col.breaches:
        print(f"health_report: {len(col.breaches)} threshold breach(es): "
              + "; ".join(b.message for b in col.breaches)[:400], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
