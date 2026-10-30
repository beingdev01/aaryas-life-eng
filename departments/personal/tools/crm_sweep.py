#!/usr/bin/env python3
"""crm_sweep.py - measure who is due for contact, without ever reading private fields.

  crm_sweep.py [--people FILE] [--today YYYY-MM-DD] [--stale-days 14]
               [--occasion-days 14] [--json] [--quiet]

Reads the people CRM and prints three things: stale contacts, occasions inside the
window, and records with broken dates. It is the only sanctioned way for this
department to look at the CRM, because it structurally cannot emit `contact_info`:
only id, name, relationship, days and tags are ever formatted into the output, and a
final scrub rejects the run rather than printing a value that matched an email or
phone pattern.

Thresholds: 7 days for records tagged `priority`, --stale-days (default 14) for
everyone else. 45+ days is reported in the `quiet` bucket as well, so a low-frequency
friendship is listed but never nagged. `last_contact` missing is `unknown` and always
shown; a future date is a data defect, never a negative count.

Output (--json): {"today", "checked", "stale": [...], "quiet": [...], "unknown": [...],
"occasions": [...], "defects": [...], "due": N}. Without --json a markdown-ish text
report is printed instead.

Exit codes: 0 nothing due; 3 something is due (a cron can alert on this); 2 the file is
missing, unreadable or not a list of records.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

DEFAULT_PEOPLE = Path("/home/ubuntu/aaryas-life/departments/personal/crm/people.json")
PRIORITY_DAYS = 7
QUIET_DAYS = 45

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SCRUB_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"   # any email
    r"|\b\d{10}\b"                                       # bare mobile
    r"|\+?\d{2}[-\s]?\d{4}[-\s]?\d{4,6}"                 # grouped mobile
)


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def days_between(then, today):
    return (today - then).days


def load_people(path: Path):
    if not path.exists():
        raise SystemExit(2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit(2)
    if isinstance(data, dict):
        for key in ("people", "records", "contacts"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            # A dict with no list under a known key is an unreadable store, not an
            # empty one. Treating it as empty makes "nobody needs a call" look true.
            raise SystemExit(2)
    if not isinstance(data, list):
        raise SystemExit(2)
    return [r for r in data if isinstance(r, dict)]


def sweep(records, today, stale_days, occasion_days):
    out = {"today": today.isoformat(), "checked": len(records), "stale": [], "quiet": [],
           "unknown": [], "occasions": [], "defects": [], "due": 0}
    for rec in records:
        pid = str(rec.get("id") or "").strip() or "(no id)"
        name = str(rec.get("name") or pid).strip()
        rel = str(rec.get("relationship") or "").strip() or "(none)"
        tags = [str(t).lower() for t in (rec.get("tags") or []) if isinstance(rec.get("tags"), list)] \
            if isinstance(rec.get("tags"), list) else []
        entry = {"id": pid, "name": name, "relationship": rel, "priority": "priority" in tags}

        raw_last = rec.get("last_contact")
        if not raw_last:
            out["unknown"].append(dict(entry, days_since=None, note="last_contact missing"))
            continue
        last = parse_date(str(raw_last))
        if last is None:
            out["defects"].append({"id": pid, "name": name, "field": "last_contact",
                                   "value_shape": "not YYYY-MM-DD"})
            continue
        days = days_between(last, today)
        if days < 0:
            out["defects"].append({"id": pid, "name": name, "field": "last_contact",
                                   "value_shape": "in the future"})
            continue
        entry["days_since"] = days
        limit = PRIORITY_DAYS if "priority" in tags else stale_days
        if days >= limit:
            (out["quiet"] if days >= QUIET_DAYS else out["stale"]).append(
                dict(entry, threshold=limit))

        bday = rec.get("birthday")
        if bday:
            bd = parse_date(str(bday))
            if bd is None:
                out["defects"].append({"id": pid, "name": name, "field": "birthday",
                                       "value_shape": "not YYYY-MM-DD"})
            else:
                upcoming = dt.date(today.year, bd.month, bd.day)
                if (upcoming - today).days < 0:
                    upcoming = dt.date(today.year + 1, bd.month, bd.day)
                in_days = (upcoming - today).days
                if in_days <= occasion_days:
                    out["occasions"].append(dict(entry, in_days=in_days, kind="birthday",
                                                 on=bd.isoformat()[5:],
                                                 year_known=int(bd.year) != 1900))
    out["due"] = len(out["stale"]) + len(out["occasions"])
    return out


def render(rep):
    lines = [f"# CRM sweep {rep['today']}",
             f"Checked: {rep['checked']} records. Stale: {len(rep['stale'])}. "
             f"Quiet 45d+: {len(rep['quiet'])}. Occasions: {len(rep['occasions'])}. "
             f"Unknown last_contact: {len(rep['unknown'])}. Defects: {len(rep['defects'])}.",
             ""]
    for title, key in (("Stale contacts", "stale"), ("Low-frequency (45+ days)", "quiet"),
                       ("Unknown last contact", "unknown")):
        rows = rep[key]
        if rows:
            lines.append(f"## {title}")
            for r in rows:
                days = r.get("days_since")
                shown = "unknown" if days is None else f"{days}d"
                star = " [priority]" if r.get("priority") else ""
                lines.append(f"- {r['id']} - {r['name']} ({r['relationship']}) - {shown}{star}")
            lines.append("")
    if rep["occasions"]:
        lines.append("## Occasions in window")
        for o in rep["occasions"]:
            age = "" if not o.get("year_known") else ""
            lines.append(f"- {o['id']} - {o['name']}: {o['kind']} {o['on']} in "
                         f"{o['in_days']}d{age}")
        lines.append("")
    if rep["defects"]:
        lines.append("## Data defects (report, do not guess a fix)")
        for d in rep["defects"]:
            lines.append(f"- {d['id']}: {d['field']} is {d['value_shape']}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="crm_sweep.py")
    ap.add_argument("--people", default=str(DEFAULT_PEOPLE))
    ap.add_argument("--today")
    ap.add_argument("--stale-days", type=int, default=14)
    ap.add_argument("--occasion-days", type=int, default=14)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    today = parse_date(args.today) if args.today else dt.date.today()
    if today is None:
        print("crm_sweep: --today must be YYYY-MM-DD", file=sys.stderr)
        return 2

    rep = sweep(load_people(Path(args.people)), today, args.stale_days, args.occasion_days)
    body = json.dumps(rep, indent=2) if args.as_json else render(rep)

    if SCRUB_RE.search(body):
        print("crm_sweep: refusing to print - output matched an email or phone pattern. "
              "A CRM field leaked into a name or tag; fix the record, not the printer.",
              file=sys.stderr)
        return 2
    if not args.quiet:
        print(body)
    return 3 if rep["due"] else 0


if __name__ == "__main__":
    sys.exit(main())
