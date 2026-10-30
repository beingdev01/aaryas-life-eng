#!/usr/bin/env python3
"""study_plan_check: validate a study plan against the academic calendar.

A study plan is markdown with at least one section whose heading contains "Schedule".
Each session is one bullet or table row in that section that starts with, or contains,
a date YYYY-MM-DD, and names the course it is for, e.g.

  | 2099-11-03 | 18:00-19:30 IST | MLP | Revision: weeks 1-4 notes, PYQ set 1 |
  - 2099-11-04 19:00 IST MLP practice: timed past paper (for iitm-mlp-quiz-2099-11-15)

An optional line "Period: YYYY-MM-DD to YYYY-MM-DD" bounds the plan; otherwise the
period runs from the first to the last session.

Checks:
  1. The plan has a dated schedule, and every date in it is a real date.
  2. Every exam and quiz in the calendar that falls inside the period has at least
     --min-sessions revision sessions (default 2) before it. A revision session names
     the course and uses a revision word (revise, revision, review, recap, practice,
     mock, PYQ, past paper, flashcards, re-read, consolidate). It counts toward the
     exam it names by id, else toward that course's next exam after the session.
  3. No session for a course sits on the day of that course's exam, and no session that
     names an exam id is on or after that exam. No revision session for a course falls
     after that course's last exam in the period.
  4. No coursework-solving language anywhere in the document ("solve assignment",
     "answers to quiz", "answer key", "submit", and similar). The department plans and
     reminds; Lakshya does graded work himself.

Modes: --calendar PATH, or --find-calendar (calendar.json or *calendar*.json beside the
plan, then up to two parent folders), or --integrity-only (check 4 only, no calendar).

Exit codes: 0 pass, 1 check failed or calendar malformed, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import term_tracker  # noqa: E402

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
DATE = re.compile(r"(?<![\w-])(\d{4})-(\d{2})-(\d{2})(?!\d)")  # not inside an entry id
PERIOD = re.compile(r"(?i)\bperiod\b\**\s*:?\**\s*(\d{4}-\d{2}-\d{2})\s*(?:to|until|-|\u2013)\s*"
                    r"(\d{4}-\d{2}-\d{2})")
REVISION = re.compile(r"(?i)\b(revis\w*|review\w*|recap\w*|practi[cs]\w*|mock\w*|pyqs?|"
                      r"past\s+papers?|flashcards?|re-?read\w*|consolidat\w*)\b")

# Phrases that mean doing graded work instead of planning it. Each is (regex, label).
_GRADED = r"(?:graded\s+)?(?:assignments?|GAs?|quiz(?:zes)?|OPPEs?|exams?|end[- ]?terms?)"
INTEGRITY = [
    (re.compile(r"(?i)\bsolv(?:e|es|ed|ing)\s+(?:the\s+|this\s+|his\s+|my\s+|lakshya'?s\s+)?"
                r"(?:week\s*\d+\s+)?" + _GRADED + r"\b"), "solving graded work"),
    (re.compile(r"(?i)\bsolv(?:e|es|ing)\s+graded\b"), "solving graded work"),
    (re.compile(r"(?i)\banswers?\s+(?:to|for)\s+(?:the\s+)?(?:week\s*\d+\s+)?" + _GRADED
                + r"\b"), "answers to graded work"),
    (re.compile(r"(?i)\b(?:assignment|GA|quiz|OPPE|exam)\s+(?:answers|solutions)\b"),
     "answers to graded work"),
    (re.compile(r"(?i)\bsolutions?\s+(?:to|for)\s+(?:the\s+)?(?:week\s*\d+\s+)?" + _GRADED
                + r"\b"), "solutions to graded work"),
    (re.compile(r"(?i)\banswer\s+keys?\b"), "answer key"),
    (re.compile(r"(?i)\bsubmit(?:s|ting)?\b"), "submitting"),
    (re.compile(r"(?i)\b(?:write|draft|complete|do|attempt|take)\s+(?:the\s+|his\s+|"
                r"lakshya'?s\s+)?(?:week\s*\d+\s+)?" + _GRADED + r"\s+for\s+(?:him|lakshya)\b"),
     "doing graded work for Lakshya"),
    (re.compile(r"(?i)\bon\s+(?:his|lakshya'?s)\s+behalf\b"), "acting on Lakshya's behalf"),
]


def integrity_problems(lines: list[str]) -> list[tuple[int, str]]:
    out = []
    for i, line in enumerate(lines):
        for rx, label in INTEGRITY:
            m = rx.search(line)
            if m:
                out.append((i + 1, f"coursework-solving language ({label}): '{m.group(0)}'. "
                                   f"The department plans and reminds; rephrase, e.g. "
                                   f"'GA 6 due 2099-11-14 23:59 IST'"))
                break
    return out


def parse_sessions(lines: list[str]):
    """Return (sessions, problems, had_schedule_heading)."""
    sessions, problems = [], []
    in_fence = False
    sched_level = None
    had_heading = False
    for i, line in enumerate(lines):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = HEADING.match(line)
        if h:
            level = len(h.group(1))
            if re.search(r"(?i)schedule", h.group(2)):
                sched_level, had_heading = level, True
            elif sched_level is not None and level <= sched_level:
                sched_level = None
            continue
        if sched_level is None:
            continue
        stripped = line.strip()
        is_row = stripped.startswith("|")
        if is_row:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if TABLE_SEP.match(stripped) or TABLE_SEP.match(nxt.strip()):
                continue
        elif not BULLET.match(line):
            continue
        m = DATE.search(stripped)
        if not m:
            continue
        try:
            day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            problems.append((i + 1, f"'{m.group(0)}' is not a real date"))
            continue
        sessions.append({"line": i + 1, "date": day, "text": stripped,
                         "revision": bool(REVISION.search(stripped))})
    return sessions, problems, had_heading


def course_rx(course: str):
    return re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(course) + r"(?![A-Za-z0-9])")


def plan_problems(text: str, calendar: dict, min_sessions: int, kinds) -> tuple[list, dict]:
    lines = text.splitlines()
    problems: list[tuple[int, str]] = []
    sessions, date_probs, had_heading = parse_sessions(lines)
    problems.extend(date_probs)
    stats = {"sessions": len(sessions), "exams": 0}
    if not sessions:
        where = ("the Schedule section has no dated session lines" if had_heading
                 else "no section with 'Schedule' in its heading")
        problems.append((0, f"no dated schedule: {where}. Add '## Schedule' with one "
                            f"bullet or table row per session, each with a YYYY-MM-DD date"))
        return problems, stats

    period = None
    for i, line in enumerate(lines):
        m = PERIOD.search(line)
        if m:
            try:
                a, b = dt.date.fromisoformat(m.group(1)), dt.date.fromisoformat(m.group(2))
            except ValueError:
                problems.append((i + 1, "Period line has an invalid date"))
                break
            if b < a:
                problems.append((i + 1, "Period ends before it starts"))
            period = (a, b)
            break
    if period is None:
        period = (min(s["date"] for s in sessions), max(s["date"] for s in sessions))
    stats["period"] = period
    for s in sessions:
        if not period[0] <= s["date"] <= period[1]:
            problems.append((s["line"], f"session on {s['date']} is outside the plan period "
                                        f"{period[0]} to {period[1]}"))

    entries = term_tracker.sorted_entries(calendar)
    exams = [e for e in entries if e["kind"] in kinds]
    by_id = {e["id"]: e for e in entries if e.get("id")}
    exam_day = {e["id"]: term_tracker.when_ist(e).date() for e in exams}
    courses = sorted({e["course"] for e in exams}, key=len, reverse=True)
    rx = {c: course_rx(c) for c in courses}
    counts = {e["id"]: 0 for e in exams}

    for s in sessions:
        linked = [eid for eid in by_id if re.search(r"(?<![\w-])" + re.escape(eid) + r"(?![\w-])",
                                                    s["text"])]
        for eid in linked:
            if eid not in exam_day:
                continue
            if s["date"] >= exam_day[eid]:
                problems.append((s["line"], f"session on {s['date']} is on or after its exam "
                                            f"{eid} ({exam_day[eid]})"))
            elif s["revision"]:
                counts[eid] += 1
        named = [c for c in courses if rx[c].search(s["text"])]
        for c in named:
            c_exams = [e for e in exams if e["course"] == c]
            same_day = [e for e in c_exams if exam_day[e["id"]] == s["date"]]
            if same_day and not linked:
                problems.append((s["line"], f"{c} session on {s['date']} is on the day of its "
                                            f"exam {same_day[0]['id']}; move it earlier"))
                continue
            if linked or not s["revision"]:
                continue
            nxt = [e for e in c_exams if exam_day[e["id"]] > s["date"]]
            if nxt:
                counts[nxt[0]["id"]] += 1
            else:
                in_period = [e for e in c_exams
                             if period[0] <= exam_day[e["id"]] <= period[1]]
                if in_period:
                    last = in_period[-1]
                    problems.append((s["line"], f"{c} revision on {s['date']} is after {c}'s "
                                                f"last exam {last['id']} ({exam_day[last['id']]})"))

    for e in exams:
        day = exam_day[e["id"]]
        if not period[0] <= day <= period[1]:
            continue
        stats["exams"] += 1
        if counts[e["id"]] < min_sessions:
            tent = " (tentative date)" if e["status"] == "tentative" else ""
            problems.append((0, f"{e['programme']} {e['kind']} {e['id']} on {day}{tent} has "
                                f"{counts[e['id']]} revision session(s) before it; need "
                                f"{min_sessions}"))
    return problems, stats


def find_calendar(plan: Path) -> Path | None:
    folder = plan.resolve().parent
    for _ in range(3):
        exact = folder / "calendar.json"
        if exact.is_file():
            return exact
        others = sorted(p for p in folder.glob("*calendar*.json") if p.is_file())
        if others:
            return others[0]
        if folder.parent == folder:
            break
        folder = folder.parent
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="study_plan_check.py",
        description="Validate a study plan: a dated schedule, revision sessions before "
                    "every exam in the calendar, nothing on or after its exam, and no "
                    "coursework-solving language.")
    parser.add_argument("plan", help="the study plan markdown file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--calendar", help="calendar JSON (term_tracker format)")
    mode.add_argument("--find-calendar", action="store_true",
                      help="use calendar.json (or *calendar*.json) beside the plan")
    mode.add_argument("--integrity-only", action="store_true",
                      help="only scan for coursework-solving language")
    parser.add_argument("--min-sessions", type=int, default=2,
                        help="revision sessions needed before each exam (default 2)")
    parser.add_argument("--kinds", default="exam,quiz",
                        help="calendar kinds that need revision (default exam,quiz)")
    args = parser.parse_args(argv)

    plan = Path(args.plan)
    try:
        text = plan.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"study_plan_check: cannot read {plan}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    if args.min_sessions < 1:
        print("study_plan_check: --min-sessions must be at least 1", file=sys.stderr)
        return 2
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    if not kinds or any(k not in term_tracker.KINDS for k in kinds):
        print(f"study_plan_check: bad --kinds '{args.kinds}'", file=sys.stderr)
        return 2

    problems = integrity_problems(text.splitlines())
    stats: dict = {}
    if not args.integrity_only:
        cal_path = Path(args.calendar) if args.calendar else find_calendar(plan)
        if cal_path is None:
            print(f"study_plan_check: no calendar.json beside {plan} or in its two parent "
                  f"folders; pass --calendar", file=sys.stderr)
            return 2
        try:
            calendar = term_tracker.read_calendar(cal_path)
        except term_tracker.CalendarError as exc:
            print(f"study_plan_check: calendar {exc}", file=sys.stderr)
            return 1
        more, stats = plan_problems(text, calendar, args.min_sessions, kinds)
        problems.extend(more)
        stats["calendar"] = str(cal_path)

    problems.sort(key=lambda p: p[0])
    if problems:
        for ln, msg in problems:
            print(f"{plan}:{ln}: {msg}" if ln else f"{plan}: {msg}")
        ln, msg = problems[0]
        print(f"study_plan_check: FAIL {plan}: {len(problems)} problem(s); first: "
              f"{'line ' + str(ln) + ': ' if ln else ''}{msg}", file=sys.stderr)
        return 1
    if args.integrity_only:
        print(f"study_plan_check: OK {plan}: integrity scan clean")
    else:
        a, b = stats["period"]
        print(f"study_plan_check: OK {plan}: {stats['sessions']} session(s) {a} to {b}, "
              f"{stats['exams']} exam(s) in period each with >= {args.min_sessions} revision "
              f"session(s), integrity scan clean (calendar {stats['calendar']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
