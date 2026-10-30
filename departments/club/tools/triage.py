#!/usr/bin/env python3
"""triage.py - classify a member's report about Code.SCRIET and say where it goes.

  triage.py report.txt
  triage.py - < report.txt          read from stdin
  triage.py report.txt --json

Classes, by keyword rules (case-insensitive):
  incident  the site or API down for many people, a breach, a leak, defacement,
            phishing, someone else in an account, a failure during a live event
  account   login, password, OTP, verification mail, locked out, profile, username
  site-bug  errors, crashes, broken pages, buttons, judge or playground failures
  content   typos, wrong dates or names on the site, photos, event listings to add
  other     none of the above
An incident wins over everything else. Otherwise the highest score wins; ties go to
account, then site-bug, then content.

Routing:
  incident  CEO immediately. Exit code 3 and a loud stderr line, so an incident is
            never quietly queued.
  site-bug  Engineering (opencode-1, [build] intake) via a child issue; club-1 drafts
            an acknowledgement for the reporter.
  account   Engineering for anything needing database or admin access; club-1 drafts
            the reply. Never ask a member for a password or OTP.
  content   club-1 drafts the exact copy change; the CEO approves; Engineering applies
            it on https://codescriet.dev (the club never edits the site).
  other     club-1 handles it or asks the CEO.

Phone numbers and email addresses in the report are masked in everything printed.
Exit codes: 0 classified; 3 incident; 2 unreadable or empty report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

INCIDENT = [
    (r"\b(?:site|website|codescriet\.dev|server|api|platform|portal|judge|everything|it)\s+"
     r"(?:is|was|went|has gone|seems|looks|appears)\s+(?:to be\s+)?(?:down|offline|unreachable)\b",
     "service down"),
    (r"\bdown\s+for\s+(?:everyone|everybody|all|the whole)\b", "down for everyone"),
    (r"\boutage\b", "outage"),
    (r"\bhack(?:ed|er|ers|ing)?\b", "hacked"),
    (r"\bbreach(?:ed)?\b", "breach"),
    (r"\b(?:data|database|emails?|passwords?|phone numbers?|details)\s+(?:leak(?:ed)?|exposed|"
     r"visible to (?:everyone|anyone|others))\b|\b(?<!memory )leak(?:ed)?\b", "data exposure"),
    (r"\bdefaced\b|\bdefacement\b", "defacement"),
    (r"\bphishing\b|\bfake (?:login|site|page)\b", "phishing"),
    (r"\bmalware\b|\bransomware\b|\bvirus\b", "malware"),
    (r"\bcompromised\b|\bunauthori[sz]ed\b", "compromise"),
    (r"\bsomeone (?:else )?(?:is |has )?(?:logged|logging|signed) in(?:to)? (?:my|to my)\b",
     "account takeover"),
    (r"\b(?:nobody|no one|no-one|none of us|none of the students)\s+(?:can|could|is able)\b",
     "nobody can use it"),
    (r"\b(?:everyone|everybody|all users|all students|all participants|whole class)\b[^.\n]*"
     r"\b(?:can'?t|cannot|unable|error|errors|failing|fails|down|not working|blank)\b",
     "affects everyone"),
    (r"\b(?:during|in the middle of)\s+(?:the\s+)?(?:event|contest|hackathon|workshop|exam|round)\b"
     r"[^.\n]*\b(?:down|crash\w*|not working|stopped|error\w*|fail\w*)\b"
     r"|\b(?:down|crash\w*|not working|stopped|error\w*|fail\w*)\b[^.\n]*\b(?:during|in the middle of)"
     r"\s+(?:the\s+)?(?:event|contest|hackathon|workshop|exam|round)\b", "failure during a live event"),
]
SCORED = {
    "account": [
        (r"\blog ?in\b|\blogin\b|\bsign ?in\b|\bsign-in\b|\blogging in\b|\bsigning in\b", 2),
        (r"\bpassword\b|\botp\b|\bone[- ]time (?:code|password)\b|\bverification (?:code|mail|email|link)\b", 2),
        (r"\baccount\b|\bprofile\b|\busername\b|\blocked out\b|\breset link\b|\btwo[- ]factor\b|\b2fa\b", 2),
        (r"\bverify my (?:email|mail|account)\b|\bchange my (?:email|name|username)\b", 2),
    ],
    "site-bug": [
        (r"\berror\b|\bbug\b|\bcrash(?:es|ed|ing)?\b|\bbroken\b|\bglitch\w*\b", 2),
        (r"\bnot (?:working|loading|opening|submitting)\b|\bdoes(?:n'?t| not) (?:work|load|open)\b", 2),
        (r"\b404\b|\b50[0-4]\b|\bblank (?:page|screen)\b|\btime[sd]? ?out\b|\bfreez\w*\b|\bstuck\b", 2),
        (r"\b(?:is|goes|went|turns|shows?)\s+(?:blank|empty|white)\b|\bnothing happens\b", 2),
        (r"\bpage\b|\bbutton\b|\blink\b|\blayout\b|\bmobile\b|\bslow\b|\bloading\b|\bsubmit\w*\b", 1),
        (r"\bjudge\b|\bplayground\b|\bcompil\w*\b|\bleaderboard\b|\bverdict\b|\btest cases?\b", 1),
    ],
    "content": [
        (r"\btypo\b|\bspelling\b|\bmisspel\w*\b|\bgrammar\b", 2),
        (r"\bwrong (?:date|time|venue|name|title|photo|link|spelling)\b|\boutdated\b|\bold (?:info|information|date)\b", 2),
        (r"\b(?:add|list|put up|feature)\s+(?:the|our|an?|this)\s+(?:event|workshop|session|talk|hackathon|photo|photos|blog)\b", 2),
        (r"\b(?:update|change|correct|fix)\s+the\s+(?:text|description|content|wording|date|time|bio|name|photo)\b", 2),
        (r"\bphotos?\b|\bpictures?\b|\bimages?\b|\bbanner\b|\bannouncement\b|\bdescription\b|\bbio\b", 1),
    ],
}
ROUTES = {
    "incident": ("CEO, immediately",
                 "Stop. Tell the CEO now with the report and the time it came in. Do not "
                 "queue it, do not reply to the reporter with a promise, do not touch any "
                 "service. The CEO pulls in Engineering."),
    "site-bug": ("engineering (opencode-1, [build] intake) via a child issue",
                 "Open the hand-off below. Draft a short acknowledgement for the reporter "
                 "(DRAFT FOR CEO REVIEW) that thanks them and gives no fix date."),
    "account": ("engineering for anything needing database or admin access",
                "Draft the reply to the member (DRAFT FOR CEO REVIEW). Never ask for a "
                "password or an OTP. Hand database or admin steps to Engineering."),
    "content": ("club-1 drafts the change, CEO approves, engineering applies it on the site",
                "Write the exact old text and the exact new text, with the page URL on "
                "https://codescriet.dev. The club never edits the site itself."),
    "other": ("club-1, or the CEO if it needs a decision",
              "Read it again; if it needs an Owner decision, ask the CEO with one exact "
              "question."),
}
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE = re.compile(r"(?<![\d+])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")


def redact(text: str) -> str:
    return PHONE.sub("(phone removed)", EMAIL.sub("(email removed)", text))


def clip_words(text: str, limit: int) -> str:
    """Shorten to at most `limit` characters without cutting a word in half."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + " ..."


def classify(text: str) -> dict:
    low = text.lower()
    incident_hits = [label for pattern, label in INCIDENT if re.search(pattern, low)]
    scores, matched = {}, {}
    for cls, rules in SCORED.items():
        total, words = 0, []
        for pattern, weight in rules:
            found = re.findall(pattern, low)
            if found:
                total += weight * len(found)
                words += [f if isinstance(f, str) else f[0] for f in found]
        scores[cls], matched[cls] = total, words
    if incident_hits:
        cls = "incident"
    else:
        order = ["account", "site-bug", "content"]
        best = max(order, key=lambda c: (scores[c], -order.index(c)))
        cls = best if scores[best] > 0 else "other"
    route, action = ROUTES[cls]
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    summary = clip_words(redact(first), 80)
    return {"class": cls, "scores": scores, "incident_signals": incident_hits,
            "matched": sorted(set(matched.get(cls, []))) if cls != "incident" else incident_hits,
            "route": route, "club_action": action, "summary": summary}


def handoff(result: dict, source: str) -> str:
    if result["class"] not in ("site-bug", "account", "content"):
        return ""
    kind = {"site-bug": "site bug", "account": "account issue",
            "content": "content change"}[result["class"]]
    return "\n".join([
        f"Title: Handoff from club-1: {kind} - {clip_words(result['summary'], 60)}",
        f"Source report: {source}",
        f"Classified as {result['class']} by triage.py (signals: "
        f"{', '.join(result['matched']) or 'none'}).",
        "Needed from Engineering: reproduce, fix or apply, and reply on this issue with what "
        "changed and where.",
        "Already done by club-1: report read and classified; no reply sent to the member; "
        "the site was not touched.",
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="triage.py",
        description="Classify a member report (site-bug, account, content, incident, other) "
                    "and print the routing. Exits 3 on an incident.")
    ap.add_argument("report", help="report text file, or - for stdin")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.report == "-" else \
            Path(args.report).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"triage: cannot read {args.report}: {exc.strerror}", file=sys.stderr)
        return 2
    if not text.strip():
        print("triage: the report is empty", file=sys.stderr)
        return 2
    result = classify(text)
    result["handoff"] = handoff(result, args.report)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"report    : {result['summary']}")
        print(f"class     : {result['class']}")
        print(f"signals   : {', '.join(result['matched']) or 'none'}")
        print(f"scores    : " + ", ".join(f"{k} {v}" for k, v in result["scores"].items()))
        print(f"route to  : {result['route']}")
        print(f"club does : {result['club_action']}")
        if result["handoff"]:
            print("hand-off draft:")
            for line in result["handoff"].splitlines():
                print(f"  {line}")
    if result["class"] == "incident":
        print(f"INCIDENT: {', '.join(result['incident_signals'])} - route to the CEO now; "
              f"do not queue this report", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
