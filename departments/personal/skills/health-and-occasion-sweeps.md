# Skill: sweeps - occasions, staleness, and health nudges

A sweep is a *measurement*, not an opinion. Its whole job is to answer "who is due, and
how do I know" from the CRM dates, and to be boring enough that Lakshya trusts it every
week. A sweep that surprises him once stops being read.

## Staleness

`days_since = today - last_contact`, day-rounded, using the CRM date only.

| tier | trigger | why |
|---|---|---|
| priority | 7+ days | `tags` contains `priority` (family, mentor with an open thread) |
| normal | 14+ days | default threshold, matches the Sunday runbook |
| quiet | 45+ days | friendships that are simply lower frequency; still listed, never nagged |

- `last_contact` missing: report as `unknown`, always shown, never ranked as 0 days.
- `last_contact` in the future: a data defect. Report it; do not compute negative days.
- A person inside two tiers counts once, at the tighter threshold.

## Occasions

Window is 14 days by default. Inside 7 days drafts now; 8-14 days gets a line in the
report only.

- Birthdays: month and day from the record. Age only if the year was given by the Owner.
- Exams and submissions that a person has told him about: those are in `notes`, and the
  right message is after the event, not before - drafting "good luck" the day before an
  exam he never mentioned is invention.
- Festivals and family dates are not in the CRM. If an issue names one, use the date from
  the issue; never derive a festival date from a model's memory of a calendar.

## Health nudges

The only lane where the department speaks about Lakshya himself.

- One per topic per day, 120 words maximum, `draft_guard.py --tone gentle`.
- An offer, not a verdict: "A short walk before the 8pm session would help" - not "you
  skipped your walk again".
- The gentle check bans guilt and scorekeeping language: `again`, `always`, `never`,
  `failed`, `should have`, `you didn't`, `your fault`.
- No diagnosis. No medication, dose or supplement advice. No calorie, weight or body
  commentary. No "doctor would say".
- If the data says nothing is off, produce no file. Silence is the default; the absence of
  a nudge file is not a missing deliverable.

## Report format

```
# Sweep 2026-10-30
Checked: 4 records. Stale: 2. Occasions <=14d: 1. Data defects: 0. Promises overdue: 1.

| id | relationship | days since | draft |
|---|---|---|---|
| father | family | 19 | work/sweep-2026-10-30/draft-father-2026-10-30.md |
| advisor-1 | advisor | 21 | (Career owns content - handed off) |

Skipped: collaborator-1 (waiting on their reply since 12 Oct).
```

Counts first, then the table, then skips with reasons. No emails, no phone numbers, no
`notes` text. The numbers must match `crm_sweep.py --json` exactly - if they disagree,
the tool is right and the prose is wrong.
