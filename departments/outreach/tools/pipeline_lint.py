#!/usr/bin/env python3
"""Outreach pipeline lint.

work/pipeline.md is the single source of truth for every prospect. A malformed
row or a stray status quietly breaks dedupe and follow-up sequencing, so this
gate keeps the table honest.

It checks a pipeline (or any prospect) markdown pipe table for:
  * a header row containing all required columns;
  * every data row having exactly as many cells as the header;
  * a non-empty prospect name;
  * a status drawn only from the allowed set;
  * a valid ISO date (YYYY-MM-DD) in the "last touch" column;
  * a non-blank "next step" (no row may sit in the pipeline with no action);
  * no duplicate prospect (case/punctuation-insensitive).

Read-only: parses markdown, writes nothing, never contacts anyone.

Usage:
  python3 pipeline_lint.py PIPELINE.md [--allow-status new,sent,...]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys

REQUIRED_COLUMNS = ["prospect", "tier", "contact", "angle", "status",
                    "last touch", "next step", "notes"]
ALLOWED_STATUSES = {"new", "approved", "sent", "replied", "meeting",
                    "sponsored", "declined", "parked"}
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def norm(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def cells_of(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) or c == "" for c in cells)


def has_valid_iso(text: str):
    for y, m, d in ISO_RE.findall(text):
        try:
            _dt.date(int(y), int(m), int(d))
            return True
        except ValueError:
            continue
    return False


def lint(path: str, allowed):
    problems = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    header = None
    col_idx = {}
    nrows = 0
    seen_names = {}
    for lineno, line in enumerate(lines, 1):
        if not line.strip().startswith("|"):
            continue
        cells = cells_of(line)
        low = [c.lower() for c in cells]
        if header is None:
            if "prospect" in low and "status" in low:
                header = cells
                col_idx = {name: low.index(name) for name in REQUIRED_COLUMNS
                           if name in low}
                missing = [c for c in REQUIRED_COLUMNS if c not in low]
                if missing:
                    problems.append(f"line {lineno}: header missing required "
                                    f"column(s): {', '.join(missing)}")
            continue
        if is_separator(cells):
            continue
        nrows += 1

        if len(cells) != len(header):
            problems.append(f"line {lineno}: {len(cells)} cells but header has "
                            f"{len(header)} -- row structure does not match")
            continue

        def col(name):
            i = col_idx.get(name)
            return cells[i] if i is not None and i < len(cells) else ""

        prospect = col("prospect")
        if not prospect:
            problems.append(f"line {lineno}: blank prospect name")
        else:
            key = norm(prospect)
            if key in seen_names:
                problems.append(f"line {lineno}: duplicate prospect '{prospect}' "
                                f"(also at line {seen_names[key]})")
            else:
                seen_names[key] = lineno

        status = col("status").lower().strip()
        if not status:
            problems.append(f"line {lineno}: blank status for '{prospect}'")
        elif status not in allowed:
            problems.append(f"line {lineno}: status '{status}' not in allowed set "
                            f"{sorted(allowed)}")

        last_touch = col("last touch")
        if not has_valid_iso(last_touch):
            problems.append(f"line {lineno}: 'last touch' has no valid ISO "
                            f"YYYY-MM-DD date for '{prospect}' (got: "
                            f"'{last_touch[:40]}')")

        next_step = col("next step")
        if not next_step or next_step.lower() in {"-", "tbd", "n/a"}:
            problems.append(f"line {lineno}: blank next step for '{prospect}' -- "
                            f"every open row needs an action")

    if header is None:
        problems.append(f"{path}: no pipeline table found (expected a header row "
                        f"with 'prospect' and 'status' columns)")
    elif nrows == 0:
        problems.append(f"{path}: table header found but no data rows")
    return problems, nrows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lint the outreach pipeline table.")
    ap.add_argument("pipeline", help="path to pipeline.md")
    ap.add_argument("--allow-status", default=None,
                    help="comma-separated allowed statuses (default the standard set)")
    args = ap.parse_args(argv)

    allowed = ({s.strip().lower() for s in args.allow_status.split(",")}
               if args.allow_status else set(ALLOWED_STATUSES))
    try:
        problems, nrows = lint(args.pipeline, allowed)
    except OSError as exc:
        print(f"pipeline_lint: cannot read {args.pipeline}: {exc}", file=sys.stderr)
        return 2

    if problems:
        for p in problems:
            print(f"pipeline_lint: FAIL - {p}", file=sys.stderr)
        return 1
    print(f"pipeline_lint: OK - {nrows} pipeline row(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
