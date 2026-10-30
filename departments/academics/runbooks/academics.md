# Runbook: academics

How academic work flows through the engine and this kit's gates. The engine does the
lane work; the kit's tools decide what passes.

## Kinds of task
| Task | Deliverables (in the run workdir) | Gates that run |
|---|---|---|
| Term setup | `calendar.json`, `term-plan.md` | calendar-valid, study-plan, integrity |
| Date change | `calendar.json` | calendar-valid |
| Weekly review | `weekly-review-YYYY-MM-DD.md` | integrity |
| Revision plan for one exam | `calendar.json`, `revision-plan-<course>.md` | calendar-valid, study-plan, integrity |

The run workdir is under `/home/ubuntu/aaryas-life/departments/academics/work/<slug>/`.
A plan's calendar sits beside it as `calendar.json`, because the study-plan gate uses
`--find-calendar`.

## 0. Intake
- The issue asks for planning, tracking or reminding: continue.
- It asks for any graded work, an answer, a hint, a code fix for an assignment, or any
  portal action: no engine run. End
  `RESULT: BLOCKED - academic integrity boundary: <what was asked>. The department can
  instead: <allowed alternative>.`
- A term setup with no course list from Lakshya: `RESULT: BLOCKED - need the course
  list for <programme> this term`.

## 1. Draft and run
```
/home/ubuntu/aaryas-life/organisation-rebuild/departments/engineering/pipeline/engctl draft --issue <ISSUE-ID> --run
```
The engine drafts a spec from the issue, has a second model family attack its
checkability, and validates it. This kit's acceptance templates then add engine-run
gates for each matching deliverable:

| Gate | Applies to | Command | Fails when |
|---|---|---|---|
| `dept:calendar-valid:<f>` | `*calendar*.json` | `term_tracker.py validate --calendar <f>` | bad programme, kind, status, date or time; no source; a confirmed entry with no time; duplicate ids; unknown fields |
| `dept:study-plan:<f>` | `*plan*.md` | `study_plan_check.py <f> --find-calendar` | no dated schedule; an exam with fewer than 2 revision sessions before it; a session on or after its exam; integrity phrases |
| `dept:integrity:<f>` | `*.md` | `study_plan_check.py <f> --integrity-only` | "solve assignment", "answers to quiz", "answer key", "submit" and similar |

academics-1 runs at depth 2: two recon slices, one review round by a different model
family, one fix round. Lanes have no web access; recon reads the supplied notices and
the existing calendar. Every lane prompt carries the three skills, the never list and
the constraints from `profile.yaml`.

## 2. After the engine reports DONE
1. Copy the verified files to the department's live location, normally
   `/home/ubuntu/aaryas-life/departments/academics/work/current/`.
2. Re-run the gates there:
   ```
   K=/home/ubuntu/aaryas-life/organisation-rebuild/departments/academics/tools
   W=/home/ubuntu/aaryas-life/departments/academics/work/current
   python3 $K/term_tracker.py validate --calendar $W/calendar.json
   python3 $K/study_plan_check.py $W/term-plan.md --calendar $W/calendar.json
   python3 $K/term_tracker.py upcoming --calendar $W/calendar.json --days 14
   python3 $K/term_tracker.py remind --calendar $W/calendar.json
   ```
3. Comment on the issue: each file path and byte size, each gate's OK line, the
   reminders firing today, and any clash. End `RESULT: DONE`, or
   `RESULT: ESCALATED - <question>` when a clash or shortfall needs Lakshya.

## Worked example (dates are invented, 2099)
Issue: "Set up the November plan. CCSU says CN sessional 2 is probably 15 Nov."
1. Recon reads the forwarded notices. The MLP Quiz 2 date comes from a written course
   announcement, so it is confirmed; the CN date was spoken in class, so it is
   tentative with source "CN teacher in class, 2099-11-01, no written notice yet".
2. Build writes `calendar.json` and `term-plan.md` from `templates/term-plan.md`.
3. First gate run: `dept:study-plan` fails with
   `ccsu-computer-networks-exam-2099-11-15 on 2099-11-15 (tentative date) has 1 revision
   session(s) before it; need 2`. The fix round adds a past-papers session on 2099-11-13.
4. `term_tracker.py clashes` shows MLP Quiz 2 and the CN sessional on the same day. The
   times do not overlap (10:00 and 14:00 IST), so the plan clears 2099-11-15 of study
   sessions and keeps both. Whether he can reach the IITM exam centre after a 10:00
   sessional is his call, so the run ends `RESULT: ESCALATED - CN sessional (10:00, not
   yet confirmed) and MLP Quiz 2 (14:00) are both on 2099-11-15; can you reach your
   quiz centre in time, or should the CN teacher be asked for another slot?`
5. Verify passes; files copied; comment posted with paths, sizes, OK lines and the
   escalation.

## Common failure modes
- "a confirmed entry needs a time": the source gave a date only. Mark it tentative, or
  find the time in the written notice.
- "is on the day of its exam": move the session at least one day earlier. A same-day
  recap is not allowed by the gate; the buffer rule says the day before, 90 minutes.
- "no calendar.json beside the plan": the plan and calendar must sit in one folder.
- Integrity gate flags "submit": rephrase as "due <date> <time> IST". Never remove the
  gate or rename the file to avoid it.
- Two notices give different dates: record the newer written one as confirmed and
  keep the other in notes via `term_tracker.py update`; if neither is written, both stay
  tentative and the clash or plan question is escalated 3 days before.
- No live lanes (`RESULT: BLOCKED - no live drafting lane`): reminders still matter.
  The CEO can run `term_tracker.py remind` and `upcoming` directly; they need no model.
