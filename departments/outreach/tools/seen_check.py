#!/usr/bin/env python3
"""Outreach dedupe / already-seen checker.

This is what stops the same company being spammed twice by two runs. Before a
prospect is drafted it must be checked against the department's memory: the
pipeline (single source of truth) and prior dated prospect files.

Rules encoded (from the outreach runbook):
  * one thread per prospect -- a company already in the pipeline in an active or
    contacted status (new / approved / sent / replied / meeting / sponsored /
    parked) is a DUPLICATE, at any age;
  * declined prospects are not re-added for N days (default 180 ~ six months);
    after that they are allowed again.

It reads files only; it never sends, writes, or contacts anything.

Company sources (in priority order):
  --company NAME (repeatable), or
  a PROSPECT_FILE positional whose `## <n>. Name` headings and
  `**Company:** Name ...` lines name the prospects inside it.

Usage:
  python3 seen_check.py PROSPECT.md --pipeline PIPELINE.md [--prospects-dir DIR]
                                    [--days 180] [--today 2027-11-01]
  python3 seen_check.py --company "Fictional Sponsor Corp" --pipeline PIPELINE.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys

ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
ACTIVE_STATUSES = {"new", "approved", "sent", "replied", "meeting", "sponsored", "parked"}
DECLINED = {"declined"}

PROSPECT_HEAD_RE = re.compile(r"^#{2,3}\s*\d+[\.\)]\s*(.+?)\s*$")
COMPANY_LINE_RE = re.compile(r"\*\*\s*Company\s*:?\s*\*\*[^\-]*?(.+?)(?:[（(\-]|$)")


def norm(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def match(a: str, b: str) -> bool:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # whole-word containment either way (GeeksforGeeks vs GeeksforGeeks Pvt Ltd)
    return bool(re.search(r"\b" + re.escape(na) + r"\b", nb) or
                re.search(r"\b" + re.escape(nb) + r"\b", na))


def parse_date(y, m, d):
    try:
        return _dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def latest_iso(text: str):
    best = None
    for y, m, d in ISO_RE.findall(text):
        dt = parse_date(y, m, d)
        if dt and (best is None or dt > best):
            best = dt
    return best


def _split_row(line: str):
    parts = [c.strip() for c in line.strip().strip("|").split("|")]
    return parts


def read_pipeline(path: str):
    """Return list of dicts {name,status,date,raw} from a markdown pipe table."""
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    header_idx = name_i = status_i = -1
    for i, line in enumerate(lines):
        cells = _split_row(line) if line.strip().startswith("|") else []
        low = [c.lower() for c in cells]
        if "prospect" in low:
            header_idx = i
            name_i = low.index("prospect")
            status_i = low.index("status") if "status" in low else 4
            continue
        if header_idx >= 0 and cells and set("".join(cells)) <= set("-: "):
            continue
        if header_idx >= 0 and i > header_idx and len(cells) > max(name_i, status_i):
            name = cells[name_i]
            if not name:
                continue
            status = (cells[status_i] if len(cells) > status_i else "").lower().strip()
            rows.append({"name": name, "status": status,
                         "date": latest_iso(" ".join(cells)), "raw": " ".join(cells)})
    return rows


def companies_from_file(path: str):
    names = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = PROSPECT_HEAD_RE.match(line)
            if m:
                names.append(re.split(r"\s*[-–(]", m.group(1))[0].strip())
                continue
            c = COMPANY_LINE_RE.search(line)
            if c:
                names.append(c.group(1).strip())
    # dedupe preserving order
    seen, out = set(), []
    for n in names:
        k = norm(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def scan_seen(company: str, pipeline: str, prospects_dir, days: int, today,
              exclude_files=None):
    """Return (is_duplicate, reason). exclude_files: abspaths to skip (self)."""
    exclude_files = exclude_files or set()
    for row in read_pipeline(pipeline):
        if not match(company, row["name"]):
            continue
        status, d = row["status"], row["date"]
        if status in DECLINED:
            if d and today and (today - d).days <= days:
                return True, (f"declined {d} ({(today - d).days} days ago, within "
                              f"{days}-day cooloff)")
            if d is None:
                return True, "declined (no date; assume inside cooloff)"
            return False, f"declined {d}, cooloff expired"
        if status in ACTIVE_STATUSES or status == "":
            return True, f"already in pipeline as '{status or 'untracked'}'"
    if prospects_dir and os.path.isdir(prospects_dir):
        for fn in sorted(os.listdir(prospects_dir)):
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(prospects_dir, fn)
            if os.path.abspath(fp) in exclude_files:
                continue
            fdate = latest_iso(fn)
            body = ""
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError:
                continue
            if fdate and today and (today - fdate).days > days:
                continue
            for cand in companies_from_file(fp) or _names_in_prose(body):
                if match(company, cand):
                    return True, f"appears in prospect file {fn} within {days} days"
    return False, "not previously contacted"


def _names_in_prose(body: str):
    # fall back: any bolded company mention
    return re.findall(r"\*\*Company:\*\*\s*([A-Za-z0-9 .&'-]+)", body)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Flag companies already contacted or declined.")
    ap.add_argument("prospect_file", nargs="?", help="prospect file whose companies to check")
    ap.add_argument("--company", action="append", default=[], help="company name to check (repeatable)")
    ap.add_argument("--pipeline", required=True, help="path to pipeline.md")
    ap.add_argument("--prospects-dir", default=None, help="dir of dated prospect files")
    ap.add_argument("--days", type=int, default=180, help="declined cooloff in days (default 180)")
    ap.add_argument("--today", default=None, help="reference date YYYY-MM-DD (default: system today)")
    args = ap.parse_args(argv)

    if args.today:
        m = ISO_RE.fullmatch(args.today.strip())
        today = parse_date(*m.groups()) if m else None
        if today is None:
            print("seen_check: --today must be YYYY-MM-DD", file=sys.stderr)
            return 2
    else:
        today = _dt.date.today()

    companies = list(args.company)
    exclude = set()
    if args.prospect_file:
        if not os.path.isfile(args.prospect_file):
            print(f"seen_check: no such prospect file: {args.prospect_file}", file=sys.stderr)
            return 2
        exclude.add(os.path.abspath(args.prospect_file))
        companies += companies_from_file(args.prospect_file)
    if not companies:
        print("seen_check: nothing to check (no --company and no prospects in the file)",
              file=sys.stderr)
        return 2

    duplicates = 0
    for c in companies:
        dup, reason = scan_seen(c, args.pipeline, args.prospects_dir, args.days, today,
                                exclude_files=exclude)
        if dup:
            duplicates += 1
            print(f"seen_check: DUPLICATE - {c}: {reason}")
        else:
            print(f"seen_check: clear - {c}: {reason}")
    if duplicates:
        print(f"seen_check: {duplicates} duplicate company(ies) must not be re-contacted",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
