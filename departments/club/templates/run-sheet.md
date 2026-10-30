DRAFT FOR CEO REVIEW

# Run sheet: [EVENT NAME], [WEEKDAY, DAY MONTH YEAR]

Venue: [VENUE]. Event lead: [ROLE]. One person answers questions on the floor: the event
lead. Every change to this sheet is written on the printed copy, not only said aloud.

Start time (T) = [START TIME]. All times below are clock times.

| time | what | owner role | done |
|---|---|---|---|
| [T minus 60 min] | Venue open, setup, projector, audio and mic check | Management Head | [ ] |
| [T minus 45 min] | Registration desk live; attendee export printed as the backup list | Technical Head | [ ] |
| [T minus 30 min] | Volunteer huddle: printed sheet in every hand, one-lead rule | President | [ ] |
| [T minus 15 min] | Doors open; first-years and guests greeted | Vice President | [ ] |
| [T] | Opening, housekeeping, agenda | [ROLE] | [ ] |
| [TIME] | [SESSION OR ROUND] | [ROLE] | [ ] |
| [TIME] | [SESSION OR ROUND] | [ROLE] | [ ] |
| [TIME] | Closing: group photo, feedback link, certificates only with a fixed date | President | [ ] |
| [END plus 30 min] | Venue cleared, equipment counted, photos handed to the content owner | Management Head | [ ] |

## Rules while it runs
- Attendance is marked in the database as people arrive, never typed up later.
- Nothing is deployed, restarted or "quickly fixed" on the site during the event.
- A site or API failure during the event is a production incident: the Technical Head
  tells the CEO at once. Nobody touches servers from the floor.
- Registration down: switch to the printed sheet; backfill the database the same day.

## Emergency contacts (roles only; numbers live in the private member list)
- Teacher In-charge: approvals, anything official or financial
- Management Head: venue, power, audio, seating
- Technical Head: registration, attendance, the site

<!--
Fill every [BRACKET] with a confirmed time, item or role. Gate:
python3 tools/draft_lint.py run-sheet-draft.md --max-words 700
-->
