# Deadline discipline

A wrong date is worse than a missing one: it is trusted. Every date the department
holds lives in `calendar.json`, written only through `term_tracker.py`.

## Recording an entry
```
term_tracker.py add --calendar calendar.json --programme IITM --course MLP \
  --kind deadline --title "Week 6 graded assignment due" --date 2099-11-08 \
  --time 23:59 --timezone IST --status confirmed \
  --source "MLP course announcement forwarded by Lakshya, 2099-10-30"
```
- `--source` says exactly where the date came from: a URL, a notice title and its
  date, or who said it and when. "unknown" is rejected.
- Times are 24 hour in IST. If the source gives another zone, record that zone; the tool
  converts and prints IST.
- "Midnight" or "12 AM on the 15th" is ambiguous. Record 23:59 on the 14th, mark it
  tentative, and say why in `--notes`, until the source is clarified.
- No time known: leave out `--time`; that is allowed only when the status is tentative,
  and the tool treats it as 23:59 IST.

## Confirmed vs tentative
Confirmed means a written primary source states the date and time: the IITM BS
academic calendar or a course announcement, or a CCSU or SCRIET written notice or date
sheet. Everything else is tentative: a verbal announcement, a forwarded message
without the notice, a date inferred from last term's pattern, a "likely" date.
Promote with a new source, never by assumption:
```
term_tracker.py update --calendar calendar.json --id <id> --status confirmed \
  --source "CCSU date sheet notice dated 2099-11-02"
```
`update` keeps the old date, status and source in `notes`, so changes stay traceable.
Never delete an entry because a date moved; update it.

## Reminders
`term_tracker.py remind --calendar calendar.json` lists what fires today:
- exams and quizzes: 14, 7, 3 and 1 days before, and the day itself;
- deadlines: 7, 3 and 1 days before, and the day itself;
- classes and other: 1 day before, and the day itself.
A tentative entry in the reminder says "(tentative)" and what would confirm it.
The department writes reminders into its run output and the issue comment; it does not
message anyone. Delivery to Lakshya is the CEO's.

## Daily and weekly
- Daily: `upcoming --days 14` and `remind`; any entry within 3 days still tentative is
  raised in the comment as the first line.
- Weekly (Sunday): `clashes --window 2 --days 28`, then the weekly review.
- After any change to calendar.json: `validate`, then re-run `study_plan_check.py` on
  the current term plan.
