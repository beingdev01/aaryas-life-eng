#!/usr/bin/env python3
"""memo_index: rebuild an index of research memos from a memos folder.

Reads every *.md file directly inside --memos (never recursing, never modifying them),
and writes one index to the --out path you pass, as Markdown (default) or JSON. For each
memo it records the date (from the YYYY-MM-DD- file-name prefix, else "undated"), the
title, the question, the first sentence of the recommendation, and whether the memo
passes memo_lint and cite_check today. README.md, INDEX.md and the output file itself
are skipped.

Exit codes: 0 index written, 1 --strict and at least one memo does not conform,
2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cite_check  # noqa: E402
import memo_lint  # noqa: E402

DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
SKIP_NAMES = {"readme.md", "index.md"}


def first_line_of(lines, mask, heads, key) -> str:
    for h in heads:
        if h["level"] <= 2 and memo_lint.classify(h["title"]) == key:
            for i in range(h["line"] + 1, h["end"]):
                if mask[i]:
                    continue
                line = lines[i].strip()
                if (not line or memo_lint.HEADING.match(line) or memo_lint.RULE.match(line)
                        or line.startswith("<!--")):
                    continue
                line = re.sub(r"^[-*+]\s+", "", line)
                return re.sub(r"[*_`]", "", line).strip()
    return ""


def first_sentence(text: str, limit: int = 200) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    out = m.group(1) if m else text
    return out if len(out) <= limit else out[: limit - 3].rstrip() + "..."


def describe(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines, mask, heads = memo_lint.parse(text)
    title = next((h["title"] for h in heads if h["level"] == 1), path.stem)
    title = re.sub(r"^research\s+memo\s*[:\u2014-]\s*", "", title, flags=re.I).strip()
    m = DATE_PREFIX.match(path.name)
    lint = memo_lint.lint_text(text)
    cites = cite_check.check_text(text)["problems"]
    return {
        "file": path.name,
        "date": m.group(1) if m else "undated",
        "title": title,
        "question": first_sentence(first_line_of(lines, mask, heads, "question")),
        "recommendation": first_sentence(first_line_of(lines, mask, heads, "recommendation")),
        "memo_lint_problems": len(lint),
        "cite_check_problems": len(cites),
        "conforms": not lint and not cites,
        "first_problem": (lint or cites or [(0, "")])[0][1],
        "bytes": path.stat().st_size,
    }


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ") or "-"


def render_markdown(rows: list[dict], memos_dir: Path) -> str:
    ok = sum(1 for r in rows if r["conforms"])
    out = ["# Research memo index", "",
           f"Built by `tools/memo_index.py` from `{memos_dir}`. {len(rows)} memo(s), "
           f"{ok} pass memo_lint and cite_check, {len(rows) - ok} do not.",
           "Do not edit by hand; rebuild it.", "",
           "| Date | Memo | Question | Recommendation | Format |",
           "|---|---|---|---|---|"]
    for r in rows:
        fmt = "ok" if r["conforms"] else (
            f"{r['memo_lint_problems']} lint / {r['cite_check_problems']} cite problem(s): "
            f"{r['first_problem'][:80]}")
        out.append(f"| {r['date']} | [{cell(r['title'])}]({r['file']}) | "
                   f"{cell(r['question'])} | {cell(r['recommendation'])} | {cell(fmt)} |")
    return "\n".join(out) + "\n"


def atomic_write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".memo_index.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="memo_index.py",
        description="Rebuild an index of research memos. Reads the memos folder only; "
                    "writes only the --out file.")
    parser.add_argument("--memos", required=True, help="folder holding the memo .md files")
    parser.add_argument("--out", required=True, help="index file to write")
    parser.add_argument("--format", choices=["md", "json"], default="md")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if any memo fails memo_lint or cite_check")
    args = parser.parse_args(argv)

    memos_dir = Path(args.memos)
    out = Path(args.out)
    if not memos_dir.is_dir():
        print(f"memo_index: memos folder not found: {memos_dir}", file=sys.stderr)
        return 2
    out_resolved = out.resolve()
    try:
        files = sorted(p for p in memos_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == ".md"
                       and p.name.lower() not in SKIP_NAMES
                       and p.resolve() != out_resolved)
    except OSError as exc:
        print(f"memo_index: cannot list {memos_dir}: {exc.strerror or exc}", file=sys.stderr)
        return 2

    rows = []
    for p in files:
        try:
            rows.append(describe(p))
        except OSError as exc:
            print(f"memo_index: cannot read {p}: {exc.strerror or exc}", file=sys.stderr)
            return 2
    dated = [r for r in rows if r["date"] != "undated"]
    undated = [r for r in rows if r["date"] == "undated"]
    rows = sorted(dated, key=lambda r: (r["date"], r["file"]), reverse=True) + undated

    body = (json.dumps({"memos_dir": str(memos_dir), "memos": rows}, indent=2) + "\n"
            if args.format == "json" else render_markdown(rows, memos_dir))
    try:
        atomic_write(out, body)
    except OSError as exc:
        print(f"memo_index: cannot write {out}: {exc.strerror or exc}", file=sys.stderr)
        return 2

    bad = [r for r in rows if not r["conforms"]]
    print(f"memo_index: wrote {out}: {len(rows)} memo(s), {len(rows) - len(bad)} conform, "
          f"{len(bad)} do not")
    if args.strict and bad:
        print(f"memo_index: {len(bad)} memo(s) do not conform; first: {bad[0]['file']}: "
              f"{bad[0]['first_problem']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
