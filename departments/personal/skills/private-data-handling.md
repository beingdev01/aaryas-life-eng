# Skill: handling private data in a shared organisation

The Personal department's data is the only data on this VM that can hurt someone outside
the company. Everything else - club members, prospects, applications - is professional.
This is family, friends, a partner, and health. Treat it as radioactive.

## The one rule that produces all the others

**A model lane must never read a private file.** Lanes are shared infrastructure: replies
are written into `.reply.md` files, echoed into issue comments, and summarized in reports.
Once a phone number enters a lane's reply it propagates. So the rule is mechanical:
private state is read by *this department's Python tool*, which prints an aggregate or an
id-level summary, and the tool's output is what the lane sees. Never `cat people.json`.
Never paste a record into a prompt. Never ask a lane to "look at the CRM file".

## What must never appear outside `departments/personal/`

- `contact_info` values: email, phone, address, personal affiliation.
- `notes` verbatim. Paraphrase the *action* ("ask how the surgery went"), not the content.
- anything in the romantic sub-department at all - not in reports, not in comments, not
  in a summary given to another agent.
- health data beyond the single nudge sentence being shown to Lakshya.
- a named person's relationship status, illness, family conflict, or finances.

## What is safe to write in an issue comment

Counts, ids, first names where a name is unavoidable, file paths, and the date range
checked. "3 stale contacts, 1 birthday inside 14 days, drafts at
`work/sweep-2026-10-30/draft-father-2026-10-30.md`" is safe. "Dad's number is 98xxxx,
he had a stent in July" is not.

## Leaks are incidents

If you notice private data already outside the department - in a comment, a report,
another department's file, a lane reply - do three things and nothing else:
1. stop the current task;
2. write down the exact path and which field leaked, without repeating the value;
3. escalate to the CEO with `RESULT: BLOCKED - private data leak at <path>`.

Do not "fix" it by rewriting the file and continuing; the copy is already in Paperclip's
comment history and in the lane reply logs, and the CEO has to decide what gets purged.

## Cross-department requests

Career asks "when did Lakshya last speak to an advisor?" - answer with the date, not the
record. Club asks for a phone number to add to a member list - refuse and escalate; the
club has its own member list, and personal contacts are not a data source.

## Fixtures

Every test in this kit uses invented names (`Asha Verma`, `Rohit Nanda`), obviously fake
numbers (`9999900001`), and the domain `example.test`. Never seed a test, an example, a
template or a demo with a real CRM record, not even with the fields blanked.
