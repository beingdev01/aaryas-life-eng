# Academics review checklist

For the reviewer lane (a different model family than the builder) and for the CEO.
Run the gates first; any failure is REVISE without further reading.

```
python3 <kit>/tools/term_tracker.py validate --calendar calendar.json
python3 <kit>/tools/study_plan_check.py term-plan.md --calendar calendar.json
python3 <kit>/tools/study_plan_check.py <every .md deliverable> --integrity-only
python3 <kit>/tools/term_tracker.py clashes --calendar calendar.json --window 2
```

## Integrity (any failure here is critical)
- [ ] Nothing in any deliverable solves, hints at, checks or drafts graded work: no
      worked answers, no code for an assignment, OPPE or graded project, no viva answers.
- [ ] Nothing describes the department logging in, uploading or submitting on a portal.
- [ ] No credential, password or portal session detail appears anywhere.
- [ ] Graded items are marked done only where Lakshya reported them done.

## Calendar
- [ ] Every entry's source names a real, specific origin (URL, notice title and date,
      or who said it and when). Spot-check three against the supplied notices.
- [ ] Confirmed entries all have a written primary source; verbal or inferred dates
      are tentative.
- [ ] Times are 24 hour and in IST, or the stated zone of the source.
- [ ] Dates that changed were updated (old values kept in notes), not deleted and re-added.
- [ ] Both programmes are present when the term has items in both.

## Plan
- [ ] The Period line covers the dates the plan claims to cover.
- [ ] Every exam and quiz in the period has at least 2 revision sessions before it
      (3 for end-terms and end-semester exams).
- [ ] No session for a course on that course's exam day; the day before is light.
- [ ] Graded-work slots finish at least 2 days before any exam within 3 days of the due
      date.
- [ ] Every clash from `clashes` is listed with what the plan does about it.
- [ ] Weekday load fits college hours: no more than two sessions on a college day.

## Reminders and escalation
- [ ] Reminders that fire today match `term_tracker.py remind`.
- [ ] Any tentative entry within 3 days is the first line of the issue comment.
- [ ] Anything only Lakshya can decide ends `RESULT: ESCALATED - <exact question>`.

Verdict: APPROVE, or REVISE with findings as `file:line: problem -> fix`.
