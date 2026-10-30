# Term planning across two degrees

Lakshya is on two programmes at once: IIT Madras BS in Data Science (term 26t3) and
BTech IT, 3rd year, at SCRIET, CCSU Meerut. A term plan fits both into one schedule.

## Inputs (refuse to plan without them)
1. The course list per programme, from Lakshya (IITM courses he registered for this
   term; CCSU subjects this semester). Do not assume a course list from an old file.
2. `calendar.json` holding every known exam, quiz and deadline, built with
   `term_tracker.py add`, each with a source. Sources: the IITM BS academic calendar
   (https://study.iitm.ac.in/ds/academic_calendar.html), course announcements Lakshya
   forwards, CCSU or SCRIET written notices and date sheets.
3. His fixed weekly commitments he states (college hours, club work).

## Steps
1. `term_tracker.py validate --calendar calendar.json` must print OK.
2. `term_tracker.py clashes --calendar calendar.json` (same day), then again with
   `--window 2`. List each one in the plan's "Clashes and buffers" section.
3. Put a `Period: YYYY-MM-DD to YYYY-MM-DD` line at the top.
4. For each exam or quiz in the period, schedule revision sessions before it: at least
   2 (the gate default), 3 for an end-term or a university end-semester exam.
5. Place graded-work time slots (Lakshya's own time for GAs, projects) so the work is
   finished at least 2 days before any exam within 3 days of its deadline.
6. Write the schedule as one table row per session:
   `| 2099-11-09 | 18:00-19:30 | MLP | Practice: past quiz papers | iitm-mlp-quiz-2099-11-15 |`
   Name the course exactly as in calendar.json; put the exam id in the last column when
   the session is for a specific exam; use a revision word (revision, review, recap,
   practice, mock, PYQ, past paper) for revision sessions.
7. `study_plan_check.py term-plan.md --calendar calendar.json` must print OK.

## Buffer rules
- Exam day: no session for that course. Day before: one light recap, 90 minutes at most.
- No new topic in the last 2 days before an exam; recap and timed practice only.
- Two exams within 2 days: alternate courses, never two heavy sessions on one day.
- On weekdays with college, at most two sessions; weekends carry the longer blocks.

## Workload balance
Share revision time by how close and how heavy each exam is: an end-term counts double
a quiz or sessional. If the hours Lakshya states cannot fit the minimum sessions, do not
squeeze: show the shortfall in hours and end
`RESULT: ESCALATED - <which course gets fewer sessions, or which commitment moves?>`.

## Clashes
A same-day IITM and CCSU exam is a clash even if the times differ: IITM quizzes and
end-terms are taken at an exam centre, and travel matters. If the times overlap, or
both cannot be reached, escalate: only Lakshya can ask either side for a change. A clash
on a tentative date is noted, then re-checked when the date is confirmed.
