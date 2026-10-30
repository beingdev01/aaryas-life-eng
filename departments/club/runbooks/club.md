# Club runbook: how a Code.SCRIET task runs through the engine

## 1. Intake
A club task is a Paperclip issue assigned to club-1. The CEO turns it into an engine
spec and runs it:

```
engctl draft --issue AAR-<n>            # draft and validate the spec, stop for review
engctl run   <spec.yaml>                # run it after checking paths and facts
engctl draft --issue AAR-<n> --run      # both in one step for routine drafts
```

Before running, check the drafted spec: deliverables sit under
`/home/ubuntu/aaryas-life/departments/club/work/<slug>/`, draft file names contain
`draft` or `announcement` (so the department gates apply), and `/home/ubuntu/clubsite*`
is in the banned paths. A request that is really a send or a decision comes back as
`RESULT: ESCALATED - <question>` and nothing runs.

## 2. What the engine adds from this kit
- `profile.yaml` loads for club-1 at depth 2: 2 recon slices, 1 review round by a
  different model family, no red team, 1 fix round. Mission, may/never, tools and the
  four skills go into every lane prompt.
- Acceptance templates become gates: every `*draft*.md` runs
  `tools/draft_lint.py --max-words 900`; every `*announcement*.md` runs it with
  `--max-words 300`. A file matching both gets both.
- The final report lists each file with its size and gate result.

## 3. What the gates check
`draft_lint.py` fails a draft that lacks DRAFT FOR CEO REVIEW; has an emoji or a
decorative symbol; has a placeholder ([NAME], {{x}}, TODO, TBD, lorem, XX:XX); states an
unconfirmed date ("to be confirmed", "tentative"); writes codescriet.dev without
https://; claims a send ("I have emailed", "has been sent") or instructs one ("Send this
to"); contains a mobile number, personal email or 12-digit ID; uses hype; or runs over
the word limit. `triage.py` is run by the lane on reports and exits 3 on an incident;
`event_checklist.py` is the date reference for every checklist and message.

## 4. Worked example: Git and GitHub workshop, Saturday 14 November 2026
Issue: "Plan the Git and GitHub workshop on 14 Nov in the SCRIET computer lab; draft the
announcement." Approval of date and lab is on file from the Teacher In-charge.

Spec deliverables in `.../club/work/git-workshop-2026-11-14/`:
- `checklist.md` (min 4000 bytes)
- `git-workshop-announcement-draft.md` (min 600 bytes)
- `git-workshop-run-sheet-draft.md` (min 900 bytes)

Spec acceptance, beside the department gates:
```
python3 <kit>/tools/event_checklist.py --event "Git and GitHub Workshop" --date 2026-11-14 --kind workshop --today 2026-10-30 --out /tmp/check.md
grep -q "Saturday, 24 October 2026" .../checklist.md
grep -q "https://codescriet.dev/events" .../git-workshop-announcement-draft.md
```

Lane work: the build lane runs event_checklist.py (T-21 falls on Saturday 24 October,
T-7 on Saturday 7 November), fills templates/announcement.md and templates/run-sheet.md
with the approved facts. First gate run: draft_lint fails the announcement on
"codescriet.dev/events" (bare) and "Venue to be confirmed" left from the template notes.
The fix lane writes the full URL and removes the line, since the lab is approved. The
reviewer flags that "certificates soon" has no date; it is removed. All gates pass. The
report names the three files with sizes; the issue comment ends with
`RESULT: ESCALATED - the announcement draft is at <path>; release it, and where?`

Triage example: a member writes "The playground is blank after I press Run, on my phone."
`triage.py` returns site-bug, route Engineering; club-1 opens a child issue titled
"Handoff from club-1: site bug - playground blank after Run on mobile" and drafts a
two-line acknowledgement. Had the report said "the judge is down for everyone in round
2", triage.py would exit 3 and the CEO is told at once.

## 5. Failure modes and what to do
| symptom | cause | action |
|---|---|---|
| draft_lint: marker missing | template header deleted | put DRAFT FOR CEO REVIEW back at the top |
| draft_lint: placeholder | template field left | fill it with a confirmed fact, or escalate the missing fact |
| draft_lint: unconfirmed date | approval not on file | do not guess; escalate the exact question |
| draft_lint: bare codescriet.dev | short URL | write https://codescriet.dev/<page> |
| draft_lint: private data | number or email copied in | replace with a role; never use --allow-contact without the CEO |
| draft_lint: send claim | "we have shared" or "Sent:" | rewrite as a draft; release is the CEO's |
| event_checklist exit 1 | event date in the past | check the year; ask the CEO for the right date |
| late phases in the checklist | started under 21 days out | do late items first; tell the CEO what cannot be done |
| triage exit 3 | incident | CEO immediately; nothing else first |
| triage says other but it is urgent | rules missed it | read it yourself; treat a plain incident as one |
| request to fix the site | not club work | hand to Engineering; never edit the repository |
