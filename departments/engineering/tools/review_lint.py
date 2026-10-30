#!/usr/bin/env python3
"""Validate a code review report (markdown or JSON) before anyone acts on it.

A review is only useful if a builder can act on every finding without asking a
question. This gate fails a review when:

- there is no verdict, or more than one different verdict (APPROVE or REVISE);
- a finding has no severity (critical, high, medium, low, info);
- a finding has no file:line location ("vague": "the error handling is weak");
- a finding has no problem statement or no concrete fix;
- the verdict is APPROVE while a critical or high finding is open;
- the verdict is REVISE with no findings at all (REVISE must say what to change);
- the reviewer is the builder (a builder never reviews its own build).

APPROVE with zero findings is valid. Markdown findings go under a "Findings" heading,
either as a table with severity | location | problem | fix columns or as list items
like `- high engine/gate.py:41 - problem. Fix: change.` JSON follows the engine's
review shape: {"verdict": ..., "findings": [{"severity", "location", "problem", "fix"}]}.

Exit codes: 0 valid, 1 invalid review, 2 unreadable or unparseable file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITIES = ("critical", "high", "medium", "low", "info")
SEV_RE = re.compile(r"\b(critical|high|medium|low|info)\b", re.I)
LOC_RE = re.compile(r"(?P<file>(?:[\w.~-]+/)*[\w.-]*\w\.[A-Za-z0-9]{1,8}|(?:[\w.~-]+/)*"
                    r"(?:Makefile|Dockerfile|Caddyfile|Procfile|engctl))"
                    r":(?P<line>\d+)(?:[-:]\d+)?")
FIX_RE = re.compile(r"\b(?:suggested fix|fix|remedy)\b\s*(?:\(optional\))?\s*"
                    r"(?::|=|[\u2014\u2013]|-(?=\s))\s*(?P<fix>.+)", re.I | re.S)
VERDICT_RE = re.compile(r"verdict\W{0,6}(?:\w+\W{1,4}){0,2}?(APPROVE|REVISE)\b", re.I)
PERSON_RE = r"^\W*{role}\W*[:\-]\W*([A-Za-z0-9][\w.-]*)"
MIN_PROBLEM = 15
MIN_FIX = 8


def finding_problems(idx: int, sev, loc, problem, fix) -> list:
    out = []
    tag = f"finding {idx}"
    if not sev:
        out.append(f"{tag}: no severity (critical, high, medium, low or info)")
    elif str(sev).lower() not in SEVERITIES:
        out.append(f"{tag}: severity {sev!r} is not one of {', '.join(SEVERITIES)}")
    if not loc or not LOC_RE.search(str(loc)):
        out.append(f"{tag}: vague - no file:line location (write path/to/file.py:42)")
    if not problem or len(str(problem).strip()) < MIN_PROBLEM:
        out.append(f"{tag}: problem statement missing or too short to act on")
    if not fix or len(str(fix).strip()) < MIN_FIX:
        out.append(f"{tag}: no concrete fix")
    return out


def parse_json(data) -> tuple:
    if not isinstance(data, dict):
        raise ValueError("review JSON must be an object")
    verdicts = [str(data.get("verdict", "")).upper()] if data.get("verdict") else []
    findings = []
    for f in data.get("findings") or []:
        if not isinstance(f, dict):
            findings.append({"severity": None, "location": None, "problem": str(f), "fix": None})
            continue
        loc = f.get("location")
        if not loc and f.get("file") and f.get("line"):
            loc = f"{f['file']}:{f['line']}"
        findings.append({"severity": f.get("severity"), "location": loc,
                         "problem": f.get("problem") or f.get("issue"), "fix": f.get("fix")})
    meta = {"reviewer": data.get("reviewer"), "builder": data.get("builder")}
    return verdicts, findings, meta, True


def section(lines: list, title_re: str) -> tuple[bool, list]:
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s*(.*)$", line.strip())
        if m and re.match(title_re, m.group(2).strip(), re.I):
            level, body = len(m.group(1)), []
            for nxt in lines[i + 1:]:
                hm = re.match(r"^(#{1,6})\s", nxt.strip())
                if hm and len(hm.group(1)) <= level:
                    break
                body.append(nxt)
            return True, body
    return False, []


def split_row(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_table(rows: list) -> list:
    header = [h.lower() for h in split_row(rows[0])]

    def col(*names):
        for n in names:
            for i, h in enumerate(header):
                if h == n or h.startswith(n):
                    return i
        return None

    ci = {"severity": col("severity", "sev"), "location": col("location", "file:line", "where"),
          "file": col("file"), "line": col("line"),
          "problem": col("problem", "issue", "finding"), "fix": col("fix", "suggested fix")}
    out = []
    for row in rows[1:]:
        cells = split_row(row)
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue

        def get(key):
            i = ci[key]
            return cells[i] if i is not None and i < len(cells) else None

        loc = get("location")
        if not loc and get("file") and get("line"):
            loc = f"{get('file')}:{get('line')}"
        out.append({"severity": get("severity"), "location": loc,
                    "problem": get("problem"), "fix": get("fix")})
    return out


def parse_item(text: str) -> dict:
    sev_m = SEV_RE.search(text)
    loc_m = LOC_RE.search(text)
    fix_m = FIX_RE.search(text)
    fix = fix_m.group("fix").strip() if fix_m else None
    problem = text
    for m in (fix_m, loc_m, sev_m):
        if m:
            problem = problem.replace(m.group(0), " ")
    problem = re.sub(r"[`*_|]+|\s+", " ", problem).strip(" -:.\u2014\u2013")
    return {"severity": sev_m.group(1) if sev_m else None,
            "location": loc_m.group(0) if loc_m else None, "problem": problem, "fix": fix}


def parse_markdown(text: str) -> tuple:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)     # template guidance is not content
    lines = text.splitlines()
    verdicts = []
    for line in lines:
        m = VERDICT_RE.search(line)
        if m:
            verdicts.append(m.group(1).upper())
    found, body = section(lines, r"findings\b")
    findings = []
    if found:
        content = [ln for ln in body if ln.strip()]
        if content and re.fullmatch(r"\W*(none|no findings)\b.*", content[0].strip(), re.I) \
                and len(content) == 1:
            content = []
        table = [ln for ln in content if ln.strip().startswith("|")]
        if table:
            findings += parse_table(table)
        items, cur = [], None
        for ln in content:
            if ln.strip().startswith("|"):
                continue
            if re.match(r"^\s?(?:[-*+]|\d+[.)])\s+", ln):
                cur = [re.sub(r"^\s?(?:[-*+]|\d+[.)])\s+", "", ln)]
                items.append(cur)
            elif cur is not None:
                cur.append(ln.strip())     # continuation line or indented sub-bullet
        findings += [parse_item(" ".join(i)) for i in items]
    meta = {}
    for role in ("reviewer", "builder"):
        m = re.search(PERSON_RE.format(role=role), text, re.I | re.M)
        meta[role] = m.group(1) if m else None
    return verdicts, findings, meta, found


def validate(verdicts, findings, meta, has_section) -> list:
    problems = []
    distinct = sorted(set(verdicts))
    if not distinct:
        problems.append("no verdict: write 'Verdict: APPROVE' or 'Verdict: REVISE'")
    elif len(distinct) > 1:
        problems.append(f"conflicting verdicts: {', '.join(distinct)}")
    for i, f in enumerate(findings, 1):
        problems += finding_problems(i, f["severity"], f["location"], f["problem"], f["fix"])
    verdict = distinct[0] if len(distinct) == 1 else None
    serious = [f for f in findings if str(f.get("severity") or "").lower() in ("critical", "high")]
    if verdict == "APPROVE" and serious:
        problems.append(f"verdict APPROVE with {len(serious)} critical/high finding(s) open; "
                        "approve only when none remain")
    if verdict == "REVISE" and not findings:
        problems.append("verdict REVISE with no findings; say exactly what must change"
                        + ("" if has_section else " under a 'Findings' heading"))
    r, b = meta.get("reviewer"), meta.get("builder")
    if r and b and r.lower() == b.lower():
        problems.append(f"reviewer {r} is also the builder; a builder never reviews its own build")
    return problems


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="review_lint.py",
        description="Validate a review report: verdict APPROVE or REVISE, and every finding "
                    "has severity, file:line, problem and fix.")
    p.add_argument("review", help="review.md or review.json")
    p.add_argument("--json", action="store_true", help="print the parsed result as JSON")
    args = p.parse_args(argv)
    path = Path(args.review)
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        print(f"review_lint: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    try:
        if path.suffix == ".json" or text.lstrip().startswith("{"):
            parsed = parse_json(json.loads(text))
        else:
            parsed = parse_markdown(text)
    except ValueError as exc:
        print(f"review_lint: {path} does not parse: {str(exc)[:200]}", file=sys.stderr)
        return 2
    verdicts, findings, meta, has_section = parsed
    problems = validate(*parsed)
    if args.json:
        print(json.dumps({"verdicts": verdicts, "findings": findings, "meta": meta,
                          "problems": problems}, indent=2))
    else:
        for prob in problems:
            print(f"FAIL {prob}")
        verdict = "/".join(sorted(set(verdicts))) or "none"
        print(f"{path}: verdict {verdict}, {len(findings)} finding(s), {len(problems)} problem(s)")
    if problems:
        print(f"review_lint: {path}: {len(problems)} problem(s): {problems[0][:200]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
