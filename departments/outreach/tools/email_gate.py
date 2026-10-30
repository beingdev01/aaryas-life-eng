#!/usr/bin/env python3
"""Outreach draft gate.

A first-touch / follow-up / reply draft is only ever a DRAFT: this tool is the
department's hard stop against the three real risks of the Outreach lane --
a fabricated contact, a missing website link, and an accidental send.

It reads one draft file. If the file contains fenced code blocks (```), each
block is treated as one email; otherwise the whole file is one email. Every
email must pass ALL of these or the tool exits non-zero with a one-line reason
per failure on stderr:

  * carries an explicit DRAFT marker (the word "draft" appears);
  * is sent from "Code.SCRIET" <outreach@codescriet.dev>;
  * states a contact that is EITHER the literal "via form" fallback OR a
    plausible public company address (never a guessed personal mailbox);
  * shows https://codescriet.dev as a FULL url in BOTH the body and the
    signature, and fails on any bare / non-https codescriet.dev mention;
  * has a signature block with a closing line and a name/title line;
  * is short (word cap), has no emoji or AI-hype phrasing, and never claims
    the message was or will be sent.

Stdlib only. Read-only: it never contacts or sends anything.

Usage:
  python3 email_gate.py DRAFT.md [--max-words N] [--json]
"""
from __future__ import annotations

import argparse
import re
import sys

FULL_URL = "https://codescriet.dev"
# Strip any correctly written full-https codescriet.dev url, then anything left
# that still says the host is a bare / non-https mention.
GOOD_URL_RE = re.compile(r"https://[A-Za-z0-9._-]*codescriet\.dev(/[^\s<>\"'()\[\]]*)?",
                         re.IGNORECASE)

FROM_ADDR = "outreach@codescriet.dev"

SIGNOFF_RE = re.compile(
    r"(?im)^[ \t]*(best|best regards|kind regards|thanks|thank you|regards|cheers|warm regards)[ \t]*,[ \t]*$")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Free / personal mailboxes: an address here is a guessed personal contact, not
# a published company door, so it must be replaced by the "via form" fallback.
FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
    "outlook.com", "live.com", "aol.com", "icloud.com", "me.com", "proton.me",
    "protonmail.com", "gmx.com", "gmx.net", "mail.com", "yandex.com",
    "yandex.ru", "mail.ru", "zoho.com",
}

# Characters in these Unicode blocks are emoji / pictographs / decorative arrows.
EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # pictographs, emoticons, transport, supplemental
    "←-\u21FF"      # arrows
    "⬀-\u2BFF"      # misc symbols and arrows / dingbats block
    "️\u200d"        # variation selector + zero-width joiner
    "\U00002600-\U000027BF"   # misc symbols + dingbats
    "]"
)

HYPE = [
    "delve", "game-changer", "game changer", "revolutionize", "revolutionary",
    "cutting-edge", "seamlessly", "unleash", "empower", "elevate",
    "fast-paced world", "next-level", "next level", "supercharge",
    "world-class", "best-in-class", "synergy", "unlock the", "harness the power",
    "excited to announce", "thrilled to", "transformative", "revolutionising",
    "revolutionizing", "state-of-the-art", "unparalleled", "effortlessly",
]
HYPE_RES = [(p, re.compile(r"(?i)\b" + re.escape(p) + r"\b")) for p in HYPE]

SEND_CLAIM = [
    r"(?i)\bi'?ve sent\b", r"(?i)\bi have sent\b", r"(?i)\bwe'?ve sent\b",
    r"(?i)\bwe have sent\b", r"(?i)\bi sent\b", r"(?i)\bwe sent\b",
    r"(?i)\bjust sent\b", r"(?i)\bhas been sent\b", r"(?i)\balready sent\b",
    r"(?i)\bsending (this|it|the email|the mail)\b", r"(?i)\bi'?m sending\b",
    r"(?i)\bi am sending\b", r"(?i)\bwill (send|email|drop)\b",
    r"(?i)\bgoing to send\b", r"(?i)\bi'?ll send\b", r"(?i)\bsent (this|it)\b",
    r"(?i)\bi'?ve emailed\b", r"(?i)\bmailed (this|it|them)\b",
    r"(?i)\bposted it\b",
]


def split_body_sig(block: str):
    m = SIGNOFF_RE.search(block)
    if not m:
        return None, None, None
    body = block[:m.start()]
    sig = block[m.start():]
    return body, sig, m


def check_email(block: str, idx: int, max_words: int):
    errs = []
    tag = f"email #{idx}" if idx else "draft"

    if FROM_ADDR not in block:
        errs.append(f"{tag}: missing sender {FROM_ADDR} "
                    f'(write: From: "Code.SCRIET" <{FROM_ADDR}>)')

    # contact line: take the To: value.
    to_line = None
    for line in block.splitlines():
        if re.match(r"(?i)\s*to\s*:", line):
            to_line = line
            break
    if to_line is None:
        errs.append(f"{tag}: no contact line (add 'To: <public email>' or "
                    f"'To: via form - <form url>')")
    else:
        val = to_line.split(":", 1)[1]
        low = val.lower()
        if "via form" in low:
            pass  # documented fallback is always allowed
        else:
            emails = EMAIL_RE.findall(val)
            if not emails:
                errs.append(f"{tag}: contact '{val.strip()[:60]}' is neither a "
                            f"public address nor the 'via form' fallback -- never "
                            f"invent a contact, use 'To: via form - <url>'")
            else:
                dom = emails[0].split("@", 1)[1].lower()
                if dom in FREE_MAIL:
                    errs.append(f"{tag}: contact {emails[0]} is a personal / free "
                                f"mailbox (invented contact); use a published "
                                f"company address or 'via form'")

    # website link: full url in body AND signature, no bare mention anywhere.
    body, sig, _ = split_body_sig(block)
    if sig is None:
        errs.append(f"{tag}: no signature block (end with a closing line like "
                    f"'Best,' then your name, title, Code.SCRIET and the url)")
    else:
        sig_lines = [l.strip() for l in sig.splitlines() if l.strip()]
        if len(sig_lines) < 2:
            errs.append(f"{tag}: signature needs a closing line plus a name/title "
                        f"line")
        if "code.scriet" not in sig.lower():
            errs.append(f"{tag}: signature must name Code.SCRIET")

    stripped = GOOD_URL_RE.sub("", block)
    stripped = re.sub(r"[A-Za-z0-9._%+\-]+@codescriet\.dev", "", stripped,
                      flags=re.IGNORECASE)
    if re.search(r"codescriet\.dev", stripped, re.IGNORECASE):
        errs.append(f"{tag}: bare or non-https 'codescriet.dev' found -- the site "
                    f"is always written in full as {FULL_URL}")
    for region, label in ((body, "body"), (sig, "signature")):
        if region is None:
            continue
        if not re.search(re.escape(FULL_URL), region, re.IGNORECASE):
            errs.append(f"{tag}: {FULL_URL} missing from the {label}")

    if EMOJI_RE.search(block):
        errs.append(f"{tag}: contains emoji / decorative symbols -- no emoji, human tone only")

    for phrase, pat in HYPE_RES:
        if pat.search(block):
            errs.append(f"{tag}: AI-hype phrasing '{phrase}' -- plain, specific, "
                        f"human copy only")

    for pat in SEND_CLAIM:
        m = re.search(pat, block)
        if m:
            errs.append(f"{tag}: claims a send ('{m.group(0)}') -- this lane drafts "
                        f"only; sends go via the CEO after Owner approval")

    words = re.findall(r"[A-Za-z0-9']+", block)
    if len(words) > max_words:
        errs.append(f"{tag}: {len(words)} words, over the {max_words}-word cap -- keep the ask short")

    return errs


def extract_blocks(text: str):
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL)
    if blocks:
        return blocks
    return [text]


def run(path: str, max_words: int):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    errors = []
    blocks = extract_blocks(text)
    if len(blocks) == 1 and not text.strip():
        return [f"{path}: file is empty"]
    if not re.search(r"(?i)\bdraft\b", text):
        errors.append(f"{path}: no DRAFT marker (the word 'draft' must appear; "
                      f"this is a draft-and-hold lane, nothing is ever sent here)")
    for i, block in enumerate(blocks, 1):
        if not block.strip():
            continue
        errors += check_email(block, i if len(blocks) > 1 else 0, max_words)
    if not any(b.strip() for b in blocks):
        return [f"{path}: no email content found"]
    return errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate an Outreach email draft (DRAFT only).")
    ap.add_argument("draft", help="path to the draft file to check")
    ap.add_argument("--max-words", type=int, default=200,
                    help="word cap per email (default 200)")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    args = ap.parse_args(argv)

    try:
        errors = run(args.draft, args.max_words)
    except OSError as exc:
        print(f"email_gate: cannot read {args.draft}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        import json
        print(json.dumps({"pass": not errors, "errors": errors}))
    if errors:
        for e in errors:
            print(f"email_gate: FAIL - {e}", file=sys.stderr)
        return 1
    print("email_gate: OK - draft passes all outreach gates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
