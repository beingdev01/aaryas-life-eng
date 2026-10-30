#!/usr/bin/env python3
"""memo_lint: fail a research memo that is not in the department's memo format.

Required sections, in this order (level-1 or level-2 headings; aliases accepted):

  Question
  Why it matters / decision it feeds   (or a "Decision this feeds:" line inside Question)
  Findings
  Options (with trade-offs)
  Recommendation
  Pre-mortem                           (decision memos only)
  Open questions
  Sources

Also fails when the memo has no '# ' title, a required section is empty, the
Recommendation has fewer than five words, or the memo still contains placeholder text:
TODO, TBD, FIXME, XXX, lorem, or "[insert" (fenced and inline code are ignored).

With --filed the file name must also be YYYY-MM-DD-<lowercase-slug>.md with a real date,
which is the convention for departments/research/memos/.

Exit codes: 0 clean, 1 problems (listed on stdout, one-line summary on stderr),
2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")

SECTIONS = {
    "question": re.compile(r"^(the\s+)?question\b", re.I),
    "why it matters": re.compile(
        r"^(why\s+(it|this)\s+matters|decision\s+(it|this)\s+feeds|context\s+and\s+decision)",
        re.I),
    "findings": re.compile(r"^(key\s+)?findings\b", re.I),
    "options": re.compile(r"^(options|alternatives|trade-?offs)\b", re.I),
    "recommendation": re.compile(r"^recommendations?\b", re.I),
    "pre-mortem": re.compile(r"^pre-?\s?mortem\b", re.I),
    "open questions": re.compile(r"^(open\s+questions|unknowns)\b", re.I),
    "sources": re.compile(r"^(sources|references)\b", re.I),
}
QUICK_ORDER = ["question", "why it matters", "findings", "options", "recommendation",
               "open questions", "sources"]
DECISION_ORDER = ["question", "why it matters", "findings", "options", "recommendation",
                  "pre-mortem", "open questions", "sources"]
WHY_INLINE = re.compile(
    r"^\s*[-*]?\s*\**\s*(decision\s+(this|it)\s+feeds|why\s+(it|this)\s+matters)\s*\**\s*:"
    r"\s*\**\s*\S", re.I)
PLACEHOLDERS = [
    (re.compile(r"\bTODO\b"), "TODO"),
    (re.compile(r"\bTBD\b"), "TBD"),
    (re.compile(r"\bFIXME\b"), "FIXME"),
    (re.compile(r"\bXXX+\b"), "XXX"),
    (re.compile(r"\blorem\b", re.I), "lorem"),
    (re.compile(r"\[\s*insert", re.I), "[insert"),
]
FILED_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")


def norm_title(text: str) -> str:
    text = re.sub(r"[*_`]", "", text).strip()
    text = re.sub(r"^(?:\d+[.)]?\s*)+", "", text)
    return text.strip()


def parse(text: str):
    lines = text.splitlines()
    mask, inside = [], False
    for line in lines:
        if FENCE.match(line):
            mask.append(True)
            inside = not inside
            continue
        mask.append(inside)
    heads = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        m = HEADING.match(line)
        if m:
            heads.append({"level": len(m.group(1)), "title": norm_title(m.group(2)),
                          "line": i})
    for k, h in enumerate(heads):
        end = len(lines)
        for later in heads[k + 1:]:
            if later["level"] <= h["level"]:
                end = later["line"]
                break
        h["end"] = end
    return lines, mask, heads


def classify(title: str) -> str | None:
    for key, rx in SECTIONS.items():
        if rx.match(title):
            return key
    return None


def body_words(lines, mask, start, end) -> int:
    words = 0
    for i in range(start, end):
        if mask[i]:
            continue
        line = lines[i]
        if HEADING.match(line) or RULE.match(line) or re.match(r"^\s*RESULT:", line):
            continue
        line = re.sub(r"<!--.*?-->", " ", line)
        words += len(re.findall(r"[A-Za-z0-9][\w'.%/-]*", line))
    return words


def lint_text(text: str, kind: str = "auto", filename: str | None = None) -> list:
    """Return a list of (line_no, message). line_no 0 means whole-document."""
    lines, mask, heads = parse(text)
    problems: list[tuple[int, str]] = []

    if not any(h["level"] == 1 for h in heads):
        problems.append((0, "memo has no title (a '# ' heading on the first lines)"))

    found: dict[str, list[dict]] = {}
    for h in heads:
        if h["level"] > 2:
            continue
        key = classify(h["title"])
        if key:
            found.setdefault(key, []).append(h)

    for key, hs in found.items():
        if len(hs) > 1:
            where = ", ".join(str(h["line"] + 1) for h in hs)
            problems.append((hs[1]["line"] + 1, f"section '{key}' appears {len(hs)} times "
                                                f"(lines {where})"))

    if kind == "auto":
        kind = "decision" if "pre-mortem" in found else "quick"
    order = DECISION_ORDER if kind == "decision" else QUICK_ORDER

    positions: dict[str, int] = {}
    for key in order:
        if key in found:
            positions[key] = found[key][0]["line"]
            continue
        if key == "why it matters" and "question" in found:
            q = found["question"][0]
            for i in range(q["line"] + 1, q["end"]):
                if not mask[i] and WHY_INLINE.match(lines[i]):
                    positions[key] = q["line"]
                    break
            if key in positions:
                continue
            problems.append((0, "missing section 'Why it matters' (add '## Why it matters' "
                                "or a 'Decision this feeds:' line under Question)"))
            continue
        problems.append((0, f"missing section '{key}'"
                            + (" (decision memos need a Pre-mortem)" if key == "pre-mortem"
                               else "")))

    present = [k for k in order if k in positions]
    for a, b in zip(present, present[1:]):
        if positions[b] < positions[a] or (positions[b] == positions[a] and
                                           not (a == "question" and b == "why it matters")):
            problems.append((positions[b] + 1, f"section '{b}' is out of order: it must come "
                                               f"after '{a}' (order: {', '.join(order)})"))

    for key, hs in found.items():
        h = hs[0]
        words = body_words(lines, mask, h["line"] + 1, h["end"])
        if key == "recommendation":
            if words < 5:
                problems.append((h["line"] + 1, f"Recommendation is empty or too thin "
                                                f"({words} word(s)); state one recommendation "
                                                f"and why"))
        elif words == 0:
            problems.append((h["line"] + 1, f"section '{key}' is empty"))

    for i, line in enumerate(lines):
        if mask[i]:
            continue
        visible = re.sub(r"`[^`]*`", " ", line)
        for rx, label in PLACEHOLDERS:
            if rx.search(visible):
                problems.append((i + 1, f"placeholder text '{label}' left in the memo"))

    if filename is not None:
        m = FILED_NAME.match(filename)
        if not m:
            problems.append((0, f"file name '{filename}' is not YYYY-MM-DD-<lowercase-slug>.md"))
        else:
            try:
                dt.date.fromisoformat(m.group(1))
            except ValueError:
                problems.append((0, f"file name date '{m.group(1)}' is not a real date"))

    problems.sort(key=lambda p: p[0])
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="memo_lint.py",
        description="Check a research memo has the required sections in order (Question, "
                    "Why it matters, Findings, Options, Recommendation, [Pre-mortem], Open "
                    "questions, Sources), a real Recommendation, and no placeholder text.")
    parser.add_argument("memo", help="path to the memo (markdown)")
    parser.add_argument("--kind", choices=["auto", "quick", "decision"], default="auto",
                        help="quick = no pre-mortem; decision = pre-mortem required; auto "
                             "(default) = decision if a Pre-mortem heading exists")
    parser.add_argument("--filed", action="store_true",
                        help="also require the YYYY-MM-DD-<slug>.md file name used in memos/")
    args = parser.parse_args(argv)

    path = Path(args.memo)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"memo_lint: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return 2

    problems = lint_text(text, args.kind, path.name if args.filed else None)
    if problems:
        for ln, msg in problems:
            print(f"{path}:{ln}: {msg}" if ln else f"{path}: {msg}")
        ln, msg = problems[0]
        print(f"memo_lint: FAIL {path}: {len(problems)} problem(s); first: "
              f"{'line ' + str(ln) + ': ' if ln else ''}{msg}", file=sys.stderr)
        return 1
    print(f"memo_lint: OK {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
