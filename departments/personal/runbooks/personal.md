# Personal runbook

How work actually gets done in this department, step by step, with the exact commands.
All paths are absolute so a lane in a fresh workdir cannot guess them.

CRM root: `/home/ubuntu/aaryas-life/departments/personal/crm`
Work root: `/home/ubuntu/aaryas-life/departments/personal/work`
Kit root: `/home/ubuntu/aaryas-life/departments/personal` (after install)

---

## 1. Sunday relationship sweep

Trigger: weekly, or an issue titled `sweep: relationships`.

1. `mkdir -p /home/ubuntu/aaryas-life/departments/personal/work/sweep-<YYYY-MM-DD>`
2. `python3 /home/ubuntu/aaryas-life/departments/personal/tools/crm_sweep.py \
     --stale-days 14 --occasion-days 14 --json > work/sweep-<date>/sweep.json`
   - exit 0 means the sweep ran; exit 3 means it ran *and* something is due. Both are
     successes. Exit 2 means the CRM file is missing or unreadable - that is a BLOCKED,
     not an empty day.
3. Read `sweep.json`. For every stale person and every occasion inside the window, write
   one draft at `work/sweep-<date>/draft-<person-id>-<date>.md` using
   `templates/message-draft.md`. Two or three sentences, in Lakshya's voice, specific to
   that person's last note. Never a generic "it has been a while".
4. `python3 .../tools/draft_guard.py work/sweep-<date>/draft-*.md --max-words 200` for
   each file. Fix until clean; a draft that cannot be made clean is deleted, not shipped.
5. Write `sweep-<date>-report.md`: due count, one line per person (`id - relationship -
   days since - draft path`), and the list of people skipped with the reason. No emails,
   no phone numbers.
6. Close overdue promises with `tools/promise_log.py overdue` and append them to the
   report.
7. `RESULT: DONE` plus the report path and every draft path.

If the sweep returns zero due items, the report says "nothing due" with the counts it
checked, and no draft is invented to justify the run.

## 2. Daily occasion radar

Trigger: daily.

1. `python3 .../tools/crm_sweep.py --occasion-days 14 --json`
2. Anything inside 7 days: write the draft now. Inside 8-14 days: add a dated note in
   the report only, no draft yet.
3. A birthday with no year, or a birthday in an impossible month, is a **data defect**:
   report it, do not silently use the year, do not "fix" the record from memory.
4. Never order a gift, book a table, or add a calendar event. Write the suggestion.

## 3. Official follow-up (professors, advisors, faculty)

Trigger: a calendar event with a professor or mentor ended, or the CEO forwards a thread.

1. Check whether Career owns the substance. If the message is about a paper, an
   application, a recommendation letter or a grade, hand the content to Career and keep
   only the relationship timing here.
2. Draft within 24 hours of the meeting. Thank the specific thing that happened, restate
   the concrete next step from their side, one sentence, no flattery.
3. `draft_guard.py` must pass. Then stop: the Owner sends it from his own account after
   he reads it.

## 4. Promise log

Promises are the failures nobody notices. When Lakshya says "tell X I'll send the
draft", record it:

```
python3 .../tools/promise_log.py add --person father --text "send the aarambh draft" --due 2026-11-02
```

Read it before writing anything for a person:

```
python3 .../tools/promise_log.py list --today 2026-10-30
python3 .../tools/promise_log.py overdue
```

Close with `done <id>`. Never delete entries; an unmet promise that was deleted is worse
than one that is overdue.

## 5. Health nudge

Trigger: daily, at most one per topic.

1. Write `nudge-<topic>-<date>.md` at 120 words or fewer, `--tone gentle`: an offer, not
   a verdict. "A 20-minute walk before the evening session would help" - not "you
   skipped again".
2. Skip the day entirely if the data shows nothing worth saying. Silence is a valid
   output; nagging is a defect.
3. No diagnosis, no medication advice, no calorie or weight moralising, no sharing with
   any other department.

## 6. Handing work to Engineering

A CRM bug or a new field is an issue with: the exact file, the exact command that
fails, what it printed, what it should print, the files owned (`departments/personal/`),
and "no send path may be added". Do not patch `crm.py` here.

## 7. What BLOCKED looks like

- the CRM file is missing or unparseable (exit 2 from the sweep);
- the issue asks for a real send, call or purchase;
- the person named in the issue is not in the CRM and there is no record to write from;
- the request needs another department's private data.

Say which, name the file or field, and stop. Never guess a person into existence.
