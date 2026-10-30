# Outreach Runbook — how the work actually gets done

Paths used throughout:
- Kit: `/home/ubuntu/aaryas-life/organisation-rebuild/departments/outreach`
- Work root: `/home/ubuntu/aaryas-life/departments/outreach/work`
- Pipeline (single source of truth): `/home/ubuntu/aaryas-life/departments/outreach/work/pipeline.md`
- Dated prospect files: `/home/ubuntu/aaryas-life/departments/outreach/work/prospects/YYYY-MM-DD.md`
- Reply drafts: `/home/ubuntu/aaryas-life/departments/outreach/work/prospects/reply-YYYY-MM-DD-<company>.md`

Everything this department produces is a DRAFT. Nothing here sends anything. Sends
go via the CEO (Muse) from `outreach@codescriet.dev` only after the Owner approves.

## 1. Daily prospecting (outreach-1)

1. Read the charter and the current pipeline before choosing anyone:
   ```bash
   sed -n '1,40p' /home/ubuntu/aaryas-life/departments/outreach/work/pipeline.md
   ```
2. Pick three NEW companies, one per step of the tier rotation below. For each,
   research the company on the public web, decide the themed angle, and find a
   *public* contact (see skills/contact-verification.md). Never guess a mailbox.
3. Before drafting, confirm each company is not already known:
   ```bash
   python3 /home/ubuntu/aaryas-life/organisation-rebuild/departments/outreach/tools/seen_check.py \
     --company "<Company>" \
     --pipeline /home/ubuntu/aaryas-life/departments/outreach/work/pipeline.md \
     --days 180
   ```
   Any non-zero result means: drop that company and choose another.
4. Write the dated file `work/prospects/YYYY-MM-DD.md` using
   `templates/prospect-file.md`. One record per company: company, tier, contact
   (with its source or `via form`), a 2-3 line angle, and a first-touch draft from
   `templates/first-touch.md`.

## 2. Tier rotation

Across the week keep the four charter tiers balanced: large, startup, dev-tools,
local (Meerut / NCR). Count each tier in the pipeline and pick the thinnest tier
today so no tier goes stale. Note the running mix at the top of the dated file.

## 3. Contact verification

For every prospect, prove the address is public: name the exact page you read it
from. Prefer a `partnerships@` / `marketing@` / `community@` company address. If
only a contact form exists, use `contact: via form - <form URL>`. If nothing is
public, still use the `via form` fallback against the site's contact page — never
invent a person or address.

## 4. First-touch drafting

Fill `templates/first-touch.md`. Hard rules (all enforced by `email_gate.py`):
- `From: "Code.SCRIET" <outreach@codescriet.dev>`.
- The full `https://codescriet.dev` URL appears in the body AND the signature.
- Short (one ask: a 15-minute call or a reply), no emoji, no hype.
- Sign with the title in `settings.signature_title` (currently `Technical Head`);
  the CEO confirms the Owner's decision before the first approval (see checklist).
Then gate the file:
```bash
python3 /home/ubuntu/aaryas-life/organisation-rebuild/departments/outreach/tools/email_gate.py \
  /home/ubuntu/aaryas-life/departments/outreach/work/prospects/YYYY-MM-DD.md
```
Fix every FAIL before the batch is offered to the CEO.

## 5. Reply handling (outreach-2)

On dispatch, read the full thread (the CEO provides it) and the company's pipeline
row. Draft a reply in thread context with `templates/reply-to-thread.md`: answer
their questions directly, stay honest about scope, commit to no unapproved number
or term, and give one next step. If they raise money, pricing, or contract terms,
stop drafting an answer and escalate to the CEO. Save to
`work/prospects/reply-YYYY-MM-DD-<company>.md` and run `email_gate.py` on it.

## 6. Pipeline hygiene

Add or update one row per prospect in `work/pipeline.md` using
`templates/pipeline-row.md` (columns: prospect | tier | contact | angle | status |
last touch | next step | notes). Statuses are only: new, approved, sent, replied,
meeting, sponsored, declined, parked. Validate before finishing:
```bash
python3 /home/ubuntu/aaryas-life/organisation-rebuild/departments/outreach/tools/pipeline_lint.py \
  /home/ubuntu/aaryas-life/departments/outreach/work/pipeline.md
```
Every send the CEO makes is logged here with its date. Never edit another
department's files.

## 7. Follow-up sequencing

One thread per prospect. At most 2 follow-ups, at least 5 days apart, then mark
`declined` (cooloff 180 days, re-checked by `seen_check.py --days 180`). Draft
follow-ups from `templates/follow-up.md`; never re-open a `declined` company inside
the window. Set `next step` to the exact date and action for the next touch.

## 8. Done

End every run with `RESULT: DONE` and the paths written (and the gate commands that
passed), or `RESULT: BLOCKED - <reason>`. Drafts go to the CEO for the Owner's
digest; this department never presses send.
