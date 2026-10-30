#!/usr/bin/env python3
"""draft_lint.py - gate a Code.SCRIET member communication draft before the CEO reads it.

  draft_lint.py work/sfic-2026/announcement-draft.md --max-words 300

Fails (exit 1, one-line reason on stderr, details on stdout) unless the draft:
  - carries the marker DRAFT FOR CEO REVIEW (exact, upper case);
  - has no emojis or decorative symbols (arrows, stars, check marks, bullets like the
    round dot, box drawing, dingbats, trade mark signs);
  - has no leftover placeholders: [NAME] style tokens, {{x}}, {x}, <name>, TODO, TBD,
    TBA, TBC, FIXME, lorem ipsum, XX:XX, DD/MM, YYYY, "insert ... here";
  - states no unconfirmed date ("to be confirmed", "tentative", "date will be announced");
  - never writes the site bare: every codescriet.dev host is preceded by https://
    (email addresses such as someone@codescriet.dev are fine);
  - claims no send or post ("I have emailed", "we posted", "has been sent", "Sent:") and
    gives no send or post instruction ("Send this to ...", "post it now", "auto-send");
  - contains no private data: mobile numbers, personal email addresses (gmail, yahoo,
    outlook and similar), 12-digit ID numbers (skip with --allow-contact only when the
    CEO asked for a contact line);
  - avoids hype ("excited to announce", "don't miss out", "game-changing", "!!");
  - stays at or under --max-words words (default 400; the marker line is not counted).

Exit codes: 0 clean; 1 problems found; 2 file missing, unreadable or empty.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "DRAFT FOR CEO REVIEW"

DECORATIVE_RANGES = [
    (0x1F000, 0x1FAFF, "emoji"), (0x2600, 0x27BF, "symbol or dingbat"),
    (0x2B00, 0x2BFF, "symbol"), (0x2190, 0x21FF, "arrow"), (0x2500, 0x25FF, "box or shape"),
    (0x2300, 0x23FF, "technical symbol"), (0xFE0F, 0xFE0F, "emoji selector"),
    (0x200D, 0x200D, "emoji joiner"), (0x2022, 0x2023, "decorative bullet"),
    (0x2043, 0x2043, "decorative bullet"), (0x2122, 0x2122, "trade mark sign"),
    (0x2729, 0x2767, "dingbat"), (0x3030, 0x3030, "wavy dash"), (0x303D, 0x303D, "symbol"),
    (0x00A4, 0x00A4, "symbol"), (0x2605, 0x2606, "star"),
]

PLACEHOLDERS = [
    (r"\[[A-Z][A-Z0-9 _/-]+\](?!\()", "bracket placeholder"),
    (r"\{\{[^}]*\}\}", "template placeholder"),
    (r"(?<!\{)\{[A-Za-z_][\w ]*\}(?!\})", "brace placeholder"),
    (r"<[A-Za-z][A-Za-z _-]*>", "angle placeholder"),
    (r"\[fill[^\]]*\]", "template placeholder"),
    (r"\b(?:TODO|TBD|TBA|TBC|FIXME)\b", "unfinished marker"),
    (r"\blorem\b|\bipsum\b", "filler text"),
    (r"\bXX:XX\b|\bDD/MM\b|\bYYYY\b|\bX{3,}\b", "unfilled value"),
    (r"\binsert\b[^.\n]{0,30}\bhere\b|\[insert", "unfilled value"),
]
UNCONFIRMED = [
    r"\bto be (?:confirmed|announced|decided|finali[sz]ed)\b", r"\btentative(?:ly)?\b",
    r"\bdate (?:will be|is yet to be) (?:announced|shared|confirmed)\b",
    r"\b(?:probably|likely) on\b",
]
SEND_CLAIMS = [
    r"\b(?:i|we)(?:'ve| have| had)?\s+(?:already\s+|just\s+)?(?:sent|e-?mailed|posted|published|"
    r"messaged|forwarded|mailed|broadcast(?:ed)?|shared|uploaded|tweeted|texted|whatsapped|"
    r"dm'?(?:e)?d)\b",
    r"\b(?:has|have|had)\s+(?:already\s+)?been\s+(?:sent|e-?mailed|posted|published|messaged|"
    r"forwarded|mailed|broadcast|shared)\b",
    r"\balready\s+(?:sent|posted|published|e-?mailed|shared)\b",
    r"\bsent\s+out\b",
    r"^\s*(?:status\s*:\s*)?(?:sent|posted|published|delivered)\s*:",
    r"^\s*status\s*:\s*(?:sent|posted|published|delivered)\b",
]
SEND_INSTRUCTIONS = [
    r"^\s*(?:[-*]\s*|\d+[.)]\s*)?(?:please\s+)?(?:send|post|publish|forward|broadcast|e-?mail|"
    r"message|tweet|upload|schedule)\s+(?:this|it|these|them|the\s+(?:draft|announcement|"
    r"message|post|email|mail|notice|update|reminder|report))\b",
    r"\b(?:auto-?send|send (?:it )?now|click send|hit send|post (?:it|this) now|"
    r"schedule (?:the )?(?:post|send|email|message))\b",
]
PRIVATE = [
    (r"(?<![\d+])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", "mobile number"),
    (r"\b[\w.+-]+@(?:gmail|googlemail|yahoo|ymail|outlook|hotmail|live|rediffmail|icloud|"
     r"proton(?:mail)?|aol)\.[a-z.]+\b", "personal email address"),
    (r"(?<!\d)\d{4}[\s-]\d{4}[\s-]\d{4}(?!\d)", "12-digit ID number"),
]
HYPE = [
    r"\bexcited to (?:announce|share|connect)\b", r"\bthrilled\b", r"\bgame[- ]chang\w*\b",
    r"\brevolutionary\b", r"\bcutting[- ]edge\b", r"\bsynerg\w*\b", r"\bseamless(?:ly)?\b",
    r"\bleverag\w*\b", r"\bdon'?t miss (?:out|it)\b", r"\bunmissable\b", r"\bonce in a lifetime\b",
    r"\bhope this (?:email |message )?finds you well\b", r"!{2,}", r"\bmind[- ]blowing\b",
]
HOST = re.compile(r"(?:[a-z0-9-]+\.)*codescriet\.dev\b", re.I)
WORD = re.compile(r"[A-Za-z0-9\u0900-\u097F]+(?:['\u2019-][A-Za-z0-9]+)*")


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def word_count(text: str) -> int:
    body = "\n".join(ln for ln in text.splitlines() if MARKER not in ln)
    return len(WORD.findall(body))


def lint(text: str, max_words: int = 400, allow_contact: bool = False) -> list[str]:
    problems: list[str] = []
    if MARKER not in text:
        problems.append(f"marker missing: the draft must carry '{MARKER}'")

    for i, ch in enumerate(text):
        cp = ord(ch)
        for lo, hi, kind in DECORATIVE_RANGES:
            if lo <= cp <= hi:
                problems.append(f"line {_line_of(text, i)}: {kind} U+{cp:04X} is not allowed")
                break

    for pattern, kind in PLACEHOLDERS:
        for m in re.finditer(pattern, text):
            problems.append(f"line {_line_of(text, m.start())}: {kind} '{m.group(0)[:30]}'")

    for pattern in UNCONFIRMED:
        for m in re.finditer(pattern, text, re.I):
            problems.append(f"line {_line_of(text, m.start())}: unconfirmed date or detail "
                            f"'{m.group(0)}'; only confirmed facts go in a member message")

    for m in HOST.finditer(text):
        before = text[max(0, m.start() - 8):m.start()]
        if text[m.start() - 1:m.start()] == "@":
            continue
        if not before.lower().endswith("https://"):
            found = re.search(r"(\S*)$", before).group(1) + m.group(0)
            problems.append(f"line {_line_of(text, m.start())}: write the site in full as "
                            f"https://{m.group(0).lower()}, not '{found}'")

    for pattern in SEND_CLAIMS:
        for m in re.finditer(pattern, text, re.I | re.M):
            problems.append(f"line {_line_of(text, m.start())}: send or post claim "
                            f"'{m.group(0).strip()}'; club-1 never sends or posts")
    for pattern in SEND_INSTRUCTIONS:
        for m in re.finditer(pattern, text, re.I | re.M):
            problems.append(f"line {_line_of(text, m.start())}: send or post instruction "
                            f"'{m.group(0).strip()}'; release is the CEO's decision")

    if not allow_contact:
        for pattern, kind in PRIVATE:
            for m in re.finditer(pattern, text, re.I):
                problems.append(f"line {_line_of(text, m.start())}: {kind} in the draft; "
                                "private data never goes in a member message")

    for pattern in HYPE:
        for m in re.finditer(pattern, text, re.I):
            problems.append(f"line {_line_of(text, m.start())}: hype '{m.group(0)}'; say the "
                            "plain fact instead")

    words = word_count(text)
    if words > max_words:
        problems.append(f"{words} words, over the {max_words}-word limit")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="draft_lint.py",
        description="Lint a Code.SCRIET communication draft: marker, no emojis, no "
                    "placeholders, full https://codescriet.dev, no send claims, no private "
                    "data, word limit.")
    ap.add_argument("draft")
    ap.add_argument("--max-words", type=int, default=400)
    ap.add_argument("--allow-contact", action="store_true",
                    help="skip the phone/email check (only when the CEO asked for a contact line)")
    args = ap.parse_args(argv)
    try:
        text = Path(args.draft).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"draft_lint: cannot read {args.draft}: {exc.strerror}", file=sys.stderr)
        return 2
    if not text.strip():
        print(f"draft_lint: {args.draft} is empty", file=sys.stderr)
        return 2
    problems = lint(text, args.max_words, args.allow_contact)
    for p in problems:
        print(f"FAIL  {p}")
    if problems:
        print(f"draft_lint: {args.draft}: {len(problems)} problem(s), first: {problems[0]}",
              file=sys.stderr)
        return 1
    print(f"PASS  {args.draft} ({word_count(text)} words, limit {args.max_words})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
