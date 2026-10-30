# Weekly review: week of [YYYY-MM-DD] (Monday) to [YYYY-MM-DD] (Sunday)

<!-- Filled by academics-1 every Sunday evening, from calendar.json, the term plan and
     what Lakshya reports. File as weekly-review-YYYY-MM-DD.md (the Sunday's date).
     This is a tracking document: it records what was planned and what happened. It
     never contains answers, solutions or drafts of graded work. -->

Prepared by: academics-1. Term plan: term-plan.md. Calendar: calendar.json.

## 1. Planned vs done

| Date | Course | Planned session | Done? | Note from Lakshya |
|---|---|---|---|---|
| [YYYY-MM-DD] | [course] | [session from the term plan] | yes / partly / no | [his words, short] |

Sessions planned: [n]. Done: [n]. Partly: [n]. Missed: [n].

## 2. Graded items that fell due this week

| Due (IST) | Programme | Course | Item | Status reported by Lakshya |
|---|---|---|---|---|
| [YYYY-MM-DD HH:MM] | IITM / CCSU | [course] | [e.g. Week 6 GA] | done / not done / not reported |

Only Lakshya marks an item done. "Not reported" is recorded as such, never guessed.

## 3. Next 14 days
Output of `term_tracker.py upcoming --calendar calendar.json --days 14`, pasted as is:

```
[paste the upcoming output here]
```

Tentative entries in that window and what would confirm them:
- [entry id]: [what source is awaited, e.g. the written CCSU date sheet]

## 4. Clashes and buffers
Output of `term_tracker.py clashes --calendar calendar.json --window 2 --days 28`:

```
[paste the clashes output here]
```

What the plan does about each one: [moved session, earlier finish, or escalation].

## 5. Changes to the plan
- [session moved from date to date, and why]

Re-check after editing the plan:
`study_plan_check.py term-plan.md --calendar calendar.json` must print OK.

## 6. Decisions only Lakshya can make
- [none] or `RESULT: ESCALATED - [exact question, e.g. "The CN sessional and MLP Quiz 2 are both on the same day; do you want to ask the CN teacher for a different slot?"]`
