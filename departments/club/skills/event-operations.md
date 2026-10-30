# Event operations at SCRIET and CCSU

Start every event with the dated checklist, not from memory:
`tools/event_checklist.py --event "<name>" --date YYYY-MM-DD --kind workshop|hackathon|talk|orientation --out <workdir>/checklist.md`
`tools/...` means this kit's tools; full paths are in the tools list above.

## Timeline (T = event day)
- T-21 permissions: date, venue, budget to the Teacher In-charge in writing; venue letter
  drafted for the HoD / Director, SCRIET; clash check against CCSU exams and holidays.
- T-14 booking confirmed in writing; announcement draft to the CEO; registration on
  https://codescriet.dev tested with one real record by Engineering; brief to Design.
- T-10 confirm people: speakers, judges, volunteers, one written reply each.
- T-7 numbers: registration count from the database with its read time; Engineering
  told the date and load; reminder draft; spend against budget.
- T-3 run sheet (templates/run-sheet.md) rehearsed with the event lead; printed backups.
- T-1 walkthrough: power, Wi-Fi, projector, audio, seating. Freeze: no deploys.
- T+1 attendance export, thank-you drafts, certificate list. T+2 report
  (templates/event-report.md), receipts, three blunt lessons.

## Permissions and faculty
- Nothing is final until the Teacher In-charge approves date, venue and budget in
  writing; keep the approval in the event folder.
- A faculty request is one short note: purpose, date, time, venue, count, the ask.
- Auditorium bookings go through the university office; the SCRIET computer lab through
  the lab in-charge. Offices are shut on Sundays; the checklist moves such tasks to Saturday.
- Dignitaries are invited through the faculty office. Invitation designs are a four-lane
  Design Team job, dispatched by the CEO, never drafted by club-1 as an image.

## Roles
Event lead, registration, content and photos, certificates, volunteers: one person
each, written down. Only the event lead answers questions on the floor.

## Day-of rules
Attendance marked in the database as people arrive. Schedule changes written on the
printed run sheet. Nothing deployed, restarted or "quickly fixed". A site or API failure
is a production incident: the Technical Head tells the CEO at once.

## After
The database is the record; if a dashboard disagrees, log both numbers and read times.
Certificate names come only from the attendance export. Sending them is the CEO's call.
