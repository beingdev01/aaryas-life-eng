# Term plan: IITM BS term 26t3 and CCSU BTech IT (3rd year)

<!-- How to use: copy this file to the task workdir as term-plan.md, put the term's
     calendar.json beside it, and replace every example row. The example rows use
     invented 2099 dates that match templates/sample-calendar.json, so this file passes
     study_plan_check.py as shipped. Real plans use real dates from calendar.json only. -->

Period: 2099-11-01 to 2099-11-28
Prepared by: academics-1, for Lakshya. Calendar: calendar.json (same folder).
This plan schedules Lakshya's own study time. It contains no answers, solutions or
drafts of any graded work, and the department does nothing on any portal.

## Courses this period

| Programme | Course | Graded items in this period | Calendar ids |
|---|---|---|---|
| IITM | MLP | Week 6 GA, Quiz 2 | iitm-mlp-deadline-2099-11-08, iitm-mlp-quiz-2099-11-15 |
| IITM | TDS | Project 1, project viva | iitm-tds-deadline-2099-11-15, iitm-tds-other-2099-11-20 |
| CCSU | Computer Networks | Sessional 2 (tentative date) | ccsu-computer-networks-exam-2099-11-15 |
| CCSU | Software Engineering | Sessional 2 | ccsu-software-engineering-exam-2099-11-18 |

Next period: MLP end term (iitm-mlp-exam-2099-11-29, tentative, no time yet) gets its
own plan; one MLP session below already counts toward it.

## Fixed dates (from `term_tracker.py list --calendar calendar.json`)
- 2099-11-08 23:59 IST: MLP Week 6 graded assignment due (confirmed)
- 2099-11-15 10:00 IST: Computer Networks Sessional 2 (tentative)
- 2099-11-15 14:00 IST: MLP Quiz 2 (confirmed)
- 2099-11-15 23:59 IST: TDS Project 1 due (confirmed)
- 2099-11-18 10:00 IST: Software Engineering Sessional 2 (confirmed)

## Clashes and buffers
- `term_tracker.py clashes` reports 2099-11-15: MLP Quiz 2 and TDS Project 1 (IITM)
  fall on the same day as the Computer Networks sessional (CCSU).
- Buffer rule applied: TDS Project 1 is planned to be finished by 2099-11-12, three days
  early, so 2099-11-13 and 2099-11-14 are revision only.
- 2099-11-15 itself has no study session. 2099-11-16 is light, before the Software
  Engineering sessional on 2099-11-18.
- Escalated to Lakshya: none needed; if the CN sessional date is confirmed as
  2099-11-15, the plan stands. If it moves to 2099-11-14, re-run the check.

## Schedule

| Date | Time (IST) | Course | Session | For |
|---|---|---|---|---|
| 2099-11-02 | 18:00-19:30 | MLP | Revision: weeks 1-3 notes and lecture summaries | iitm-mlp-quiz-2099-11-15 |
| 2099-11-03 | 18:00-19:30 | Computer Networks | Revision: units 1-2, own notes | |
| 2099-11-04 | 19:00-21:00 | TDS | Project 1: Lakshya's own build block | due 2099-11-15 23:59 IST |
| 2099-11-06 | 18:00-19:30 | MLP | Week 6 GA: Lakshya's own time slot, due 2099-11-08 23:59 IST | |
| 2099-11-07 | 17:00-18:30 | Software Engineering | Review: SDLC models and testing chapter | |
| 2099-11-09 | 18:00-19:30 | MLP | Practice: past quiz papers, timed, self-marked | iitm-mlp-quiz-2099-11-15 |
| 2099-11-10 | 09:30-11:00 | Computer Networks | Extra class (attend) | |
| 2099-11-11 | 18:00-19:30 | Computer Networks | Review: unit 3 and numericals | |
| 2099-11-12 | 19:00-21:00 | TDS | Project 1: Lakshya's own finishing block | |
| 2099-11-13 | 17:00-19:00 | Computer Networks | Past papers: two previous sessionals, timed | |
| 2099-11-14 | 10:00-12:00 | MLP | Recap: own formula sheet and mistakes list | iitm-mlp-quiz-2099-11-15 |
| 2099-11-16 | 18:00-19:00 | Software Engineering | Recap: UML diagrams, light | |
| 2099-11-17 | 17:00-19:00 | Software Engineering | Practice: previous sessional paper, timed | |
| 2099-11-21 | 18:00-19:30 | MLP | Revision: weeks 5-8 for the end term | iitm-mlp-exam-2099-11-29 |
| 2099-11-23 | 18:00-19:00 | TDS | Viva preparation: Lakshya explains his own project out loud | |

## Weekly review
Every Sunday at 20:00 IST, fill `templates/weekly-review.md`: planned vs done per
session, slips, and changes to this plan. A slip of two sessions for one course moves
that course's next session forward, never onto an exam day.

## Sources
- calendar.json in this folder (term_tracker validate: OK)
- Example only: dates are invented 2099 dates, not taken from any portal or notice.
