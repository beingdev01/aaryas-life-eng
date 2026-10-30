#!/usr/bin/env python3
"""promise_log.py - the open promises that the CRM README asks for and nothing kept.

  promise_log.py [--store FILE] add --person ID --text TEXT [--due YYYY-MM-DD]
  promise_log.py [--store FILE] list [--today YYYY-MM-DD] [--person ID]
  promise_log.py [--store FILE] done ID [--today YYYY-MM-DD] [--note TEXT]
  promise_log.py [--store FILE] overdue [--today YYYY-MM-DD]
  promise_log.py [--store FILE] validate

Store defaults to
/home/ubuntu/aaryas-life/departments/personal/crm/promises.json and is append-only:
`done` sets a status and a closed date, it never removes an entry. A deleted promise is
a broken promise nobody can see.

Ids are deterministic and short: the first 8 hex characters of sha1 of
"<person>|<made>|<text>", so re-adding the same promise is a no-op reported as
"duplicate" rather than a second entry. That makes the tool safe to re-run from a cron.

Entry: {id, person, text, made, due, status(open|done|dropped), closed, note}
`dropped` exists for a promise Lakshya explicitly cancelled; the tool never chooses it.

Exit codes: 0 ok; 1 nothing overdue (only for `overdue`, so a cron can alert on 0); 2
bad arguments, unparseable store, or a text/due that fails validation; 4 duplicate add.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_STORE = Path("/home/ubuntu/aaryas-life/departments/personal/crm/promises.json")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("open", "done", "dropped")


def make_id(person, made, text):
    return hashlib.sha1(f"{person}|{made}|{text}".encode()).hexdigest()[:8]


class BadDate(ValueError):
    pass


class StoreError(ValueError):
    pass


def parse_date(value, what):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise BadDate(f"promise_log: {what} must be YYYY-MM-DD, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise BadDate(f"promise_log: {what} is not a real date: {value!r}")


def today_or(arg):
    if not arg:
        return dt.date.today()
    return parse_date(arg, "--today")


def load(path: Path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreError(f"promise_log: store {path} is not readable JSON: {exc}")
    if not isinstance(data, list):
        raise StoreError("promise_log: store must be a JSON list")
    return data


def save(path: Path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def validate_entries(entries):
    problems = []
    seen = set()
    for e in entries:
        if not isinstance(e, dict):
            problems.append(f"entry is not an object: {e!r}")
            continue
        eid = e.get("id", "")
        if eid in seen:
            problems.append(f"duplicate id {eid}")
        seen.add(eid)
        for field in ("id", "person", "text", "made", "status"):
            if not e.get(field):
                problems.append(f"{eid or '?'}: missing {field}")
        for field in ("made", "due", "closed"):
            val = e.get(field)
            if val and not DATE_RE.match(str(val)):
                problems.append(f"{eid}: {field} is not YYYY-MM-DD")
        if e.get("status") not in STATUSES:
            problems.append(f"{eid}: status {e.get('status')!r} not in {STATUSES}")
        if e.get("status") == "done" and not e.get("closed"):
            problems.append(f"{eid}: done without a closed date")
    return problems


def cmd_add(entries, args, today):
    text = (args.text or "").strip()
    if len(text) < 3:
        print("promise_log: --text must say what was promised", file=sys.stderr)
        return 2
    if not (args.person or "").strip():
        print("promise_log: --person is a CRM id", file=sys.stderr)
        return 2
    made = parse_date(args.made, "--made") if args.made else today
    eid = make_id(args.person, made.isoformat(), text)
    if any(e.get("id") == eid for e in entries):
        print(f"duplicate: {eid} already in the store")
        return 4
    entry = {"id": eid, "person": args.person.strip(), "text": text,
             "made": made.isoformat(), "due": args.due or None, "status": "open",
             "closed": None, "note": ""}
    entries.append(entry)
    print(f"added {eid}: {args.person} - {text}")
    return 0


def cmd_done(entries, args, today):
    matches = [e for e in entries if e.get("id", "").startswith(args.id)]
    if not matches:
        print(f"promise_log: no entry starts with {args.id!r}", file=sys.stderr)
        return 2
    if len(matches) > 1:
        print(f"promise_log: {args.id!r} is ambiguous "
              f"({', '.join(m['id'] for m in matches)})", file=sys.stderr)
        return 2
    entry = matches[0]
    if entry.get("status") == "done":
        print(f"already done: {entry['id']}")
        return 0
    entry["status"] = "done"
    entry["closed"] = (parse_date(args.closed, "--closed") if args.closed
                       else today).isoformat()
    if args.note:
        entry["note"] = args.note
    print(f"closed {entry['id']}: {entry['person']} - {entry['text']}")
    return 0


def rows(entries, today, person=None):
    out = []
    for e in entries:
        if person and e.get("person") != person:
            continue
        if e.get("status") != "open":
            continue
        due = parse_date_soft(e.get("due"))
        overdue = due is not None and due < today
        out.append((e, overdue))
    return out


def parse_date_soft(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def render(items, today, header):
    print(f"{header} ({today.isoformat()})")
    if not items:
        print("  none")
        return
    for e, overdue in sorted(items, key=lambda p: (not p[1], str(p[0].get("due") or "9999"))):
        flag = "OVERDUE" if overdue else ("due " + str(e.get("due"))) if e.get("due") else "no due date"
        print(f"  {e['id']}  {e.get('person')}  {e.get('text')}  [{flag}]")


def main(argv=None):
    # --store and --today must work either before or after the subcommand, because the
    # runbook calls the tool both ways. SUPPRESS means an absent subcommand-level flag
    # leaves the top-level value in place instead of overwriting it with a default.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--store", default=argparse.SUPPRESS)
    shared.add_argument("--today", default=argparse.SUPPRESS)

    ap = argparse.ArgumentParser(prog="promise_log.py", parents=[shared])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", parents=[shared])
    a.add_argument("--person", required=True)
    a.add_argument("--text", required=True)
    a.add_argument("--due")
    a.add_argument("--made")
    l = sub.add_parser("list", parents=[shared])
    l.add_argument("--person")
    d = sub.add_parser("done", parents=[shared])
    d.add_argument("id")
    d.add_argument("--closed")
    d.add_argument("--note")
    sub.add_parser("overdue", parents=[shared])
    sub.add_parser("validate", parents=[shared])
    args = ap.parse_args(argv)

    path = Path(getattr(args, "store", str(DEFAULT_STORE)))
    try:
        entries = load(path)
    except StoreError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        today = today_or(getattr(args, "today", None))
    except BadDate as exc:
        print(str(exc), file=sys.stderr)
        return 2
    rc = 0

    try:
        if args.cmd == "add":
            if args.due:
                parse_date(args.due, "--due")
            rc = cmd_add(entries, args, today)
        elif args.cmd == "done":
            rc = cmd_done(entries, args, today)
        elif args.cmd == "list":
            render(rows(entries, today, args.person), today, "Open promises")
        elif args.cmd == "overdue":
            items = [pair for pair in rows(entries, today) if pair[1]]
            render(items, today, "Overdue promises")
            rc = 0 if items else 1
        elif args.cmd == "validate":
            problems = validate_entries(entries)
            for p in problems:
                print(f"  - {p}")
            rc = 1 if problems else 0
            print(f"{len(entries)} entries, {len(problems)} problems")
    except BadDate as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if rc in (0,) and args.cmd in ("add", "done"):
        save(path, entries)
    return rc


if __name__ == "__main__":
    sys.exit(main())
