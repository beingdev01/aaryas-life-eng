# Checklist: club review (every club-1 output, before it reaches the CEO)

Run on the file itself, not on a summary of it. Any unchecked line goes back to club-1
with the exact fix.

## Gates (must exit 0; paste the output in the issue comment)
- [ ] `tools/draft_lint.py <draft> --max-words <limit>` for every draft, announcement,
      reminder, thank-you and report (300 for announcements, 900 for reports)
- [ ] `tools/triage.py <report>` for every member report; exit 3 went to the CEO at once
- [ ] Checklists generated with `tools/event_checklist.py` for the right kind and date

## Marker and release
- [ ] DRAFT FOR CEO REVIEW at the top
- [ ] Nothing was sent, posted, emailed, messaged or scheduled by club-1
- [ ] No line tells anyone to send or post it; release is the CEO's call

## Facts
- [ ] Every date, time and venue is confirmed in writing (Teacher In-charge approval on file)
- [ ] Weekday matches the date (event_checklist.py output is the reference)
- [ ] The site is written in full as https://codescriet.dev, with the exact page path
- [ ] Numbers come from the database export, with its read time; not from a dashboard

## Privacy
- [ ] No member names in kit files, checklists or reports; roles only
- [ ] No phone numbers, personal emails, roll numbers or ID numbers in any message
- [ ] Nothing copied out of the private member list into a draft
- [ ] Account issues: the reply never asks for a password or OTP

## Voice
- [ ] Plain, warm, specific: what, when, where, who it is for, what to bring
- [ ] No emojis, no decorative symbols, no hype, no exclamation runs
- [ ] Under the word limit; one ask per message
- [ ] Signed by a role, not "Team Code.SCRIET"

## Routing
- [ ] Site bugs and account fixes handed to Engineering with steps to reproduce
- [ ] Content changes written as exact old text and new text with the page URL
- [ ] Production incident: CEO told immediately, with time and symptom
- [ ] Invitations for SCRIET or CCSU occasions routed to the four-lane Design Team
- [ ] Taste, send or spend questions end with `RESULT: ESCALATED - <exact question>`
