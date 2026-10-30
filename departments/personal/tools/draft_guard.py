#!/usr/bin/env python3
"""draft_guard.py - stop a personal draft before it reads as if it had been sent.

  draft_guard.py work/sweep-2026-10-30/draft-father-2026-10-30.md [--max-words 200]
                  [--tone gentle] [--report] [--allow-contact]

Fails (exit 1, reasons on stdout, one line on stderr) unless the file:
  - starts with the marker DRAFT FOR CEO REVIEW (exact, upper case) - unless --report,
    which instead requires a first line matching "# Sweep <date>" or "# Report <date>";
  - claims no completed action: no "i have sent", "already emailed", "shared with",
    "you will receive it", "cc'd", "forwarded", "replied to them" in any tense;
  - instructs nobody to send: no "send this to", "post it tonight", "message her back",
    "mail it";
  - leaks no contact detail: no email address, no 10-digit or grouped mobile number, no
    full postal address line - unless --allow-contact, which a report may use once for a
    department-internal address and nothing else;
  - has no placeholders: [NAME], {{x}}, {x}, TODO, TBD, TBA, FIXME, "<", "lorem",
    "XX:XX", "YYYY-MM-DD" left unfilled;
  - has no emoji or decorative symbols (arrows, dingbats, stars, check marks, bullets,
    box drawing, trade-mark signs);
  - with --tone gentle, uses no guilt or scorekeeping language: again, always, never,
    failed, should have, didn't, did not, your fault, bad at;
  - stays within --max-words words (default 200; the marker line and the "To (for you to
    send):" line are not counted).

Exit codes: 0 clean; 1 problems found; 2 file missing, unreadable or empty.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "DRAFT FOR CEO REVIEW"
REPORT_HEAD = re.compile(r"^#\s*(Sweep|Report)\s+\d{4}-\d{2}-\d{2}\s*$", re.I | re.M)

COMPLETED_ACTION = [
    (r"\bi\s+have\s+(just\s+)?(sent|emailed|mailed|messaged|texted|called|forwarded|shared|replied)\b",
     "claims a send that has not happened"),
    (r"\b(SENT|POSTED|DELIVERED|EMAILED|MAILED|TEXTED|CALLED)\s+(to\s+)?(\w+\s+)?(them|him|her|you|the)\b",
     "claims a completed contact"),
    (r"\balready\s+(sent|emailed|mailed|shared|forwarded|notified)\b", "claims a completed send"),
    (r"\b(you'?ll|you will|they will|she will|he will)\s+(receive|get)\s+it\b",
     "promises delivery the department cannot make"),
    (r"\b(cc'?d|bcc'?d|forwarded to|replied to them)\b", "claims a send"),
]
SEND_INSTRUCTION = [
    (r"^\s*(send|post|mail|email|message|whatsapp|deliver|publish)\b.{0,40}\b(this|it|that|these)\b",
     "instructs a send"),
    (r"\b(send|post|message)\s+(this|it)\s+(to|now|tonight|today)\b", "instructs a send"),
    (r"\bauto-?send\b|\bschedule\s+(the\s+)?(message|send)\b", "proposes an automated send"),
]
PLACEHOLDERS = [
    (r"\[[A-Z][A-Z _]{2,}\]", "placeholder like [NAME]"),
    (r"\{\{.*?\}\}", "template token {{...}}"),
    (r"\{[a-z_]+\}", "template token {x}"),
    (r"\bTODO\b|\bTBD\b|\bTBA\b|\bFIXME\b|\bTBC\b", "leftover TODO/TBD"),
    (r"\blorem\s+ipsum\b", "lorem ipsum"),
    (r"\bXX:XX\b|\bDD/MM\b|\bYYYY[-/]MM[-/]DD\b", "unfilled date"),
    (r"<\s*(?:insert|name|date|link)\s*>", "angle-bracket placeholder"),
]
HYPE = [
    (r"\bhope this message finds you well\b", "template filler greeting"),
    (r"\bjust checking in\b", "template filler"),
    (r"\bso excited\b|\bgame-?changing\b|\bthrilled to\b", "hype"),
    (r"!!", "multiple exclamation marks"),
]
GUILT = [
    (r"\bagain\b", "'again' reads as scorekeeping"),
    (r"\balways\b|\bnever\b", "absolutes accuse"),
    (r"\bfail(?:ed|ure)?\b", "verdict language"),
    (r"\bshould have\b|\bshouldn'?t you\b", "guilt language"),
    (r"\bdidn'?t\b|\bdid not\b", "blame language"),
    (r"\byour fault\b|\bbad at\b", "shaming"),
]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\b(?:\+91[-\s]?)?\d{5}[-\s]?\d{5}\b")
ADDRESS_RE = re.compile(r"\b(?:pin\s*code|pincode|flat\s*no|house\s*no|ward\s*no)\b\s*[:=]?\s*\S", re.I)

DECORATIVE = [
    (0x1F300, 0x1FAFF), (0x2190, 0x21FF), (0x2300, 0x23FF), (0x2460, 0x24FF),
    (0x25A0, 0x25FF), (0x2600, 0x26FF), (0x2700, 0x27BF), (0x2B00, 0x2BFF),
    (0xFE0F, 0xFE0F), (0x2022, 0x2022), (0x00A9, 0x00A9), (0x00AE, 0x00AE),
    (0x2122, 0x2122),
]


def has_decorative(text):
    for ch in text:
        cp = ord(ch)
        for lo, hi in DECORATIVE:
            if lo <= cp <= hi:
                return ch
    return None


def count_words(text):
    body = text.replace(MARKER, "")
    body = re.sub(r"^To \(for you to send\):.*$", "", body, flags=re.M)
    return len(body.split())


def check(text, max_words=200, tone=None, is_report=False, allow_contact=False):
    problems = []
    lines = [ln for ln in text.splitlines()]
    if is_report:
        if not REPORT_HEAD.match("\n".join(lines[:3]).lstrip()):
            problems.append("a report must open with '# Sweep YYYY-MM-DD' or '# Report YYYY-MM-DD'")
    elif MARKER not in (lines[0] if lines else ""):
        problems.append(f"line 1 must be the marker {MARKER}")

    for pattern, why in COMPLETED_ACTION:
        for m in re.finditer(pattern, text, re.I | re.M):
            problems.append(f"send-claim ({why}): {m.group(0).strip()[:60]!r}")
    for pattern, why in SEND_INSTRUCTION:
        for m in re.finditer(pattern, text, re.I | re.M):
            problems.append(f"send instruction ({why}): {m.group(0).strip()[:60]!r}")
    for pattern, why in PLACEHOLDERS:
        for m in re.finditer(pattern, text):
            problems.append(f"{why}: {m.group(0)[:40]!r}")
    for pattern, why in HYPE:
        if re.search(pattern, text, re.I):
            problems.append(why)

    if not allow_contact:
        for m in EMAIL_RE.finditer(text):
            problems.append(f"email address present in file: {m.group(0)[:6]!r}...")
            break
        for m in PHONE_RE.finditer(text):
            problems.append("phone number present in file")
            break
        if ADDRESS_RE.search(text):
            problems.append("postal address field present in file")
    if tone == "gentle":
        for pattern, why in GUILT:
            if re.search(pattern, text, re.I):
                problems.append(f"gentle tone violated ({why})")
    bad = has_decorative(text)
    if bad:
        problems.append(f"decorative character U+{ord(bad):04X}")

    words = count_words(text)
    if words > max_words:
        problems.append(f"{words} words, limit is {max_words}")
    if words == 0:
        problems.append("file has no content after the marker")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(prog="draft_guard.py")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-words", type=int, default=200)
    ap.add_argument("--tone", choices=["gentle"])
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--allow-contact", action="store_true")
    args = ap.parse_args(argv)

    failed = False
    for raw in args.files:
        path = Path(raw)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            print(f"draft_guard: cannot read {path}", file=sys.stderr)
            return 2
        if not text.strip():
            print(f"draft_guard: {path} is empty", file=sys.stderr)
            return 2
        problems = check(text, args.max_words, args.tone, args.report, args.allow_contact)
        if problems:
            failed = True
            print(f"FAIL {path}")
            for p in dict.fromkeys(problems):
                print(f"  - {p}")
        else:
            print(f"ok   {path}")
    if failed:
        print("draft_guard: fix every file or delete it; do not ship a draft that fails.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
