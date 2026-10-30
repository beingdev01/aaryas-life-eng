#!/usr/bin/env python3
"""event_checklist.py - a dated Code.SCRIET event checklist from T-21 to T+2.

  event_checklist.py --event "Git and GitHub Workshop" --date 2026-11-14 --kind workshop
  event_checklist.py --event "Aarambh 2027" --date 2027-08-20 --kind orientation \\
      --venue "Netaji Subhash Chandra Bose Auditorium, CCSU" --out work/aarambh-2027/checklist.md

Phases: T-21, T-14, T-10, T-7, T-3, T-1, T-0 (event day), T+1, T+2. Each phase gets its
real calendar date and weekday, computed from --date. Every line names an owner by club
role (never by personal name; names live only in the private member list). Kinds add
their own lines: workshop, hackathon, talk, orientation.

Office work (permission letters, bookings, signatures) cannot happen on a Sunday at
SCRIET/CCSU, so such lines that fall on a Sunday say to do them on the Saturday before.
Phases already in the past (against --today, default the real date) are marked late,
and the output says the timeline is compressed. An event date in the past is refused.

The output is a DRAFT FOR CEO REVIEW markdown checklist on stdout, or in --out.
Exit codes: 0 written; 1 the event date is in the past; 2 bad arguments.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

KINDS = ("workshop", "hackathon", "talk", "orientation")
PHASES = [
    (-21, "Plan and permissions"),
    (-14, "Book, announce, invite"),
    (-10, "Confirm people"),
    (-7, "Numbers and platform"),
    (-3, "Run sheet and rehearsal"),
    (-1, "Walkthrough and freeze"),
    (0, "Event day"),
    (1, "Attendance, thanks, certificates"),
    (2, "Report and receipts"),
]

# (offset, text, owner role, needs the office open)
COMMON = [
    (-21, "Date and venue proposed to the Teacher In-charge; written approval requested", "Management Head", True),
    (-21, "Venue permission letter drafted for the HoD / Director, SCRIET to sign (club-1 drafts, Management Head carries it)", "Management Head", True),
    (-21, "Clash check: CCSU exam schedule, university holidays, other SCRIET events that week", "Vice President", False),
    (-21, "Budget lines written down with who approves each spend", "Management Head", False),
    (-21, "One named owner for each role: event lead, registration, content and photos, certificates, volunteers", "President", False),
    (-14, "Venue booking confirmed in writing; copy filed in the event folder", "Management Head", True),
    (-14, "Announcement drafted from templates/announcement.md and passed through draft_lint.py", "club-1", False),
    (-14, "Announcement reviewed by the CEO; the CEO decides when and where it is released", "CEO", False),
    (-14, "Registration form on https://codescriet.dev tested end to end with one real record (Engineering)", "Technical Head", False),
    (-14, "Design brief for the poster and certificates handed to Design", "Vice President", False),
    (-10, "Speakers, judges and volunteers confirmed in writing, one reply each", "Vice President", False),
    (-10, "Certificate plan fixed: template, names from the database export only, signatory approved", "Technical Head", False),
    (-10, "Volunteer roster drafted with one task per person", "Management Head", False),
    (-7, "Registration count read from the database (not the dashboard), with the time it was read", "Technical Head", False),
    (-7, "Engineering told the date and expected load; no deploys planned in the last 24 hours", "Technical Head", False),
    (-7, "Reminder message drafted for CEO review", "club-1", False),
    (-7, "Spend so far against budget, in writing", "Management Head", False),
    (-7, "Hardware list: extension boards, chargers, projector adapter, mic, markers, signage", "Management Head", False),
    (-3, "Run sheet drafted from templates/run-sheet.md with times and one owner per row", "club-1", False),
    (-3, "Full rehearsal with the event lead; one person answers questions on the day", "President", False),
    (-3, "Printed backups: run sheet, offline registration sheet, latest attendee export", "Management Head", True),
    (-3, "Final reminder drafted for CEO review", "club-1", False),
    (-1, "Venue walkthrough: power, Wi-Fi, projector and audio, seating, signage", "Management Head", False),
    (-1, "Platform health check recorded by Engineering if the event uses the site; freeze from now", "Technical Head", False),
    (-1, "Printed run sheet in every lead's hand", "President", False),
    (0, "Venue open 60 minutes early; AV and mic check", "Management Head", False),
    (0, "Registration desk live; attendance marked in the database as people arrive", "Technical Head", False),
    (0, "Volunteer huddle 30 minutes before start; one lead answers questions", "President", False),
    (0, "Any schedule change written on the printed run sheet, not only said aloud", "Management Head", False),
    (0, "Closing: group photo and feedback link; certificates promised only with a real date", "President", False),
    (0, "Production incident on the site or API: tell the CEO immediately; nobody fixes servers on the floor", "Technical Head", False),
    (1, "Attendance export from the database with the read time saved in the event folder", "Technical Head", False),
    (1, "Thank-you drafts for participants, speakers, volunteers and faculty, for CEO review", "club-1", False),
    (1, "Certificate name list built from the attendance export; five records spot-checked for spelling", "Technical Head", False),
    (1, "Certificate send decision and timing go to the CEO; nothing is queued without approval", "CEO", False),
    (2, "Event report drafted from templates/event-report.md with numbers from the database export", "club-1", False),
    (2, "Receipts filed: attendance export and time, spend against budget, photo folder, approvals", "Management Head", False),
    (2, "Three blunt change-next-time points while memory is fresh", "President", False),
    (2, "Partner organisations met at the event added to the outreach pipeline as prospects", "Vice President", False),
]

EXTRA = {
    "workshop": [
        (-21, "Computer lab at SCRIET requested with seat count and timing; lab in-charge informed", "Management Head", True),
        (-14, "Prerequisites and software list fixed with the instructor", "Technical Head", False),
        (-7, "Software list handed to the lab in-charge for installation on every machine", "Technical Head", True),
        (-3, "Instructor dry run on one lab machine, including the network", "Technical Head", False),
        (-1, "Every lab machine checked: software opens, login works, internet reachable", "Technical Head", False),
        (1, "Workshop material and links collected for the follow-up draft", "club-1", False),
    ],
    "hackathon": [
        (-21, "Problem statements owner named; judging rubric drafted with weights", "Technical Head", False),
        (-21, "Prize budget approved by the Teacher In-charge in writing", "Management Head", True),
        (-14, "Judges invited formally (faculty and external), with the rubric attached", "Vice President", True),
        (-10, "Submission portal tested end to end by Engineering", "Technical Head", False),
        (-7, "Team registration closes; teams and members counted from the database", "Technical Head", False),
        (-3, "Written permission for late hours from the HoD if the event runs past college time", "Management Head", True),
        (-3, "Food, water and seating plan per team; judging sheets printed", "Management Head", False),
        (0, "Problem statements released on time; judging timeline kept to the minute", "Technical Head", False),
        (1, "Results draft for CEO review, with scores kept in the event folder", "club-1", False),
    ],
    "talk": [
        (-21, "Speaker confirmed in writing with topic, duration and format", "President", False),
        (-14, "Speaker bio and photo approved by the speaker before any use", "Vice President", False),
        (-14, "Travel and hospitality plan approved by the Teacher In-charge", "Management Head", True),
        (-7, "Q&A moderator named; two opening questions prepared", "Vice President", False),
        (-7, "Memento and certificate of appreciation for the speaker arranged", "Management Head", False),
        (-1, "Reminder call to the speaker: time, gate, contact on arrival", "President", False),
        (1, "Thank-you letter drafted for the Teacher In-charge to sign", "club-1", False),
    ],
    "orientation": [
        (-21, "Programme order agreed with faculty: welcome, addresses, sessions, vote of thanks", "President", True),
        (-21, "Invitation design dispatched as the four-lane Design Team (never a solo job)", "CEO", False),
        (-14, "Auditorium booked through the university office; booking letter filed", "Management Head", True),
        (-14, "Dignitary invitations approved by the CEO; delivery handled by the faculty office", "CEO", True),
        (-10, "Protocol fixed: seating order on stage, reception at the gate, welcome by whom", "Management Head", False),
        (-7, "First-year attendance source agreed with the department office", "Technical Head", True),
        (-3, "Volunteer guides placed at the gate, auditorium entry and stage side", "Management Head", False),
        (-1, "Stage walkthrough with the faculty coordinator; nameplates and seating checked", "Management Head", False),
        (0, "Dignitaries received at the gate and seated by protocol; programme order kept", "President", False),
        (1, "Thank-you letters to dignitaries drafted for faculty signature", "club-1", False),
    ],
}


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value}") from exc


def fmt(d: dt.date) -> str:
    return f"{d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}"


def build(event: str, date: dt.date, kind: str, venue: str | None,
          today: dt.date) -> tuple[str, int]:
    items = COMMON + EXTRA[kind]
    late_phases = 0
    lines = [f"# Event checklist: {event} ({kind})", "",
             "DRAFT FOR CEO REVIEW", "",
             f"Event day: {fmt(date)}. Venue: {venue or 'not booked yet; see T-21'}.",
             f"Generated by event_checklist.py on {fmt(today)}. Dates are computed from the "
             "event date; the event date itself is only final once the Teacher In-charge "
             "approves it in writing.",
             "Owners are club roles. Names stay in the private member list, never in this file.",
             ""]
    phase_dates = {off: date + dt.timedelta(days=off) for off, _ in PHASES}
    body = []
    for off, title in PHASES:
        when = phase_dates[off]
        label = "T-0" if off == 0 else (f"T{off}" if off < 0 else f"T+{off}")
        late = when < today
        late_phases += late
        head = f"## {label} - {fmt(when)} - {title}"
        if late:
            head += " (late: this date has passed; do these now)"
        body += [head, ""]
        for item_off, text, owner, office in items:
            if item_off != off:
                continue
            note = ""
            if office and when.weekday() == 6:
                sat = when - dt.timedelta(days=1)
                note = f" (falls on a Sunday; offices are closed, do it on {fmt(sat)})"
            body.append(f"- [ ] {text}. Owner: {owner}.{note}")
        body.append("")
    if late_phases:
        lines += [f"Compressed timeline: {late_phases} phase(s) are already past. Do the late "
                  "items first and tell the CEO what cannot be done in time.", ""]
    return "\n".join(lines + body).rstrip() + "\n", late_phases


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="event_checklist.py",
        description="Generate a dated T-21 to T+2 checklist for a Code.SCRIET event.")
    ap.add_argument("--event", required=True, help="event name as it will appear")
    ap.add_argument("--date", required=True, type=parse_date, help="event day, YYYY-MM-DD")
    ap.add_argument("--kind", choices=KINDS, default="workshop")
    ap.add_argument("--venue", default=None)
    ap.add_argument("--today", type=parse_date, default=None,
                    help="treat this as today (for planning and tests); default is the real date")
    ap.add_argument("--out", default=None, help="write here instead of stdout")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if not args.event.strip():
        print("event_checklist: --event must not be empty", file=sys.stderr)
        return 2
    today = args.today or dt.date.today()
    if args.date < today:
        print(f"event_checklist: event date {args.date} is in the past (today {today})",
              file=sys.stderr)
        return 1
    text, late = build(args.event.strip(), args.date, args.kind, args.venue, today)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote {out} ({len(text.encode())} bytes, {text.count('- [ ]')} items, "
              f"{late} late phase(s))")
    else:
        sys.stdout.write(text)
    if late:
        print(f"event_checklist: warning: {late} phase(s) already past; timeline compressed",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
