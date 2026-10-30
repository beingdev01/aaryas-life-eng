#!/usr/bin/env python3
"""Gate for platform report deliverables (health, incident, change reports).

A platform report passes only if it is non-trivial and ends in something the CEO
can act on:
- at least --min-bytes bytes (default 400) and at least 5 lines of real content;
- a top heading;
- no placeholder text left from a template (TODO, TBD, <fill in>, {{...}}, lorem);
- a "Commands for the CEO" section that is not empty: it holds commands (a fenced
  code block or inline `code`), or says plainly that no commands are needed;
- nothing that looks like a credential (bearer tokens, passwords, private keys,
  database URLs with a password, bcrypt hashes).

Exit codes: 0 pass, 1 the report fails, 2 the file could not be read.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLACEHOLDERS = [
    (re.compile(r"\bTODO\b"), "TODO"),
    (re.compile(r"\bTBD\b"), "TBD"),
    (re.compile(r"\bFIXME\b"), "FIXME"),
    (re.compile(r"<\s*(fill|insert|replace|your|todo)[^>]*>", re.I), "<fill-in> marker"),
    (re.compile(r"\{\{[^}]*\}\}"), "{{template}} marker"),
    (re.compile(r"\blorem ipsum\b", re.I), "lorem ipsum"),
    (re.compile(r"\[placeholder\]", re.I), "[placeholder]"),
]
SECRETS = [
    (re.compile(r"\bBearer\s+(?!\[REDACTED\])[A-Za-z0-9._~+/=-]{12,}"), "a bearer token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{50,}"), "a bcrypt password hash"),
    (re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^:/\s]+:(?!\[REDACTED\])[^@\s]+@", re.I),
     "a database URL with a password"),
    (re.compile(r"(?i)\b(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*(?!\[REDACTED\])[\"']?[A-Za-z0-9/+_.-]{8,}"),
     "a key=value credential"),
    (re.compile(r"\b(nvapi-|sk-|ghp_|github_pat_|xox[abprs]-)[A-Za-z0-9_-]{10,}"), "an API key"),
]
CEO_HEADING = re.compile(r"^(#{1,6})\s*commands\s+for\s+the\s+ceo\b", re.I)
NO_ACTION = re.compile(r"\b(no commands (are )?needed|none required|no action (is )?(needed|required))\b", re.I)


def ceo_section(lines: list) -> tuple[bool, list]:
    for i, line in enumerate(lines):
        m = CEO_HEADING.match(line.strip())
        if not m:
            continue
        level = len(m.group(1))
        body = []
        for nxt in lines[i + 1:]:
            hm = re.match(r"^(#{1,6})\s", nxt.strip())
            if hm and len(hm.group(1)) <= level:
                break
            body.append(nxt)
        return True, body
    return False, []


def lint(text: str, min_bytes: int) -> list:
    problems = []
    size = len(text.encode())
    if size < min_bytes:
        problems.append(f"report is {size} bytes; a usable report is at least {min_bytes}")
    lines = text.splitlines()
    content = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")
               and not re.fullmatch(r"[\s|:-]+", ln)]
    if len(content) < 5:
        problems.append(f"only {len(content)} lines of content; the report says too little")
    if not any(re.match(r"^#{1,2}\s+\S", ln) for ln in lines):
        problems.append("no top heading (# or ##); start with what the report is about")
    for pattern, label in PLACEHOLDERS:
        m = pattern.search(text)
        if m:
            line_no = text[:m.start()].count("\n") + 1
            problems.append(f"placeholder {label} left on line {line_no}")
    for pattern, label in SECRETS:
        m = pattern.search(text)
        if m:
            line_no = text[:m.start()].count("\n") + 1
            problems.append(f"line {line_no} looks like {label}; replace it with [REDACTED]")
    found, body = ceo_section(lines)
    if not found:
        problems.append("no 'Commands for the CEO' section; every platform report ends with "
                        "the exact commands the CEO should run (or says none are needed)")
    else:
        real = [ln for ln in body if ln.strip()]
        joined = "\n".join(real)
        has_cmd = "```" in joined or re.search(r"`[^`\n]{3,}`", joined)
        if not real:
            problems.append("'Commands for the CEO' section is empty")
        elif not has_cmd and not NO_ACTION.search(joined):
            problems.append("'Commands for the CEO' has no command (fenced block or `inline`) "
                            "and does not say that none are needed")
    return problems


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="report_lint.py",
        description="Fail a platform report that is trivial, unfinished, leaks a credential, "
                    "or lacks a 'Commands for the CEO' section.")
    p.add_argument("report", help="markdown report to check")
    p.add_argument("--min-bytes", type=int, default=400)
    args = p.parse_args(argv)
    try:
        text = Path(args.report).read_text(errors="replace")
    except OSError as exc:
        print(f"report_lint: cannot read {args.report}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    problems = lint(text, args.min_bytes)
    if problems:
        for prob in problems:
            print(f"FAIL {prob}")
        print(f"report_lint: {args.report}: {len(problems)} problem(s): {problems[0]}",
              file=sys.stderr)
        return 1
    print(f"report_lint: {args.report}: OK ({len(text.encode())} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
