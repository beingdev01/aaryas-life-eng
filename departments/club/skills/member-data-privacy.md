# Privacy of member data

Code.SCRIET holds personal data about students: the office-bearer list
(`departments/club/toolkit/members.json`), registration records, attendance exports and
certificate lists. All of it is private. The rule is simple: roles go in documents,
people stay in the private files.

## What may appear where
- Kit files, checklists, run sheets, reports: roles only (President, Vice President,
  Technical Head, Management Head, Teacher In-charge). Never a member's name, phone
  number, email or roll number.
- Member messages: no phone numbers, personal emails or roll numbers; contact goes
  through a role or an official address on the club domain.
- Public names supplied in the brief (a guest speaker, a dignitary, a judge) may appear
  in the drafts that concern them, spelled exactly as the brief gives them.
- Issue comments: aggregate numbers only ("96 attended of 214 registered"), never rows
  from an export.

## Working with exports
- Attendance and registration exports stay in the event folder under the work root. Do
  not paste rows into prompts, comments or drafts; quote counts and the read time.
- When a certificate list is needed, point to the export path; a person merges it.
- No copies of member data outside the event folder.

## Reports that contain personal data
triage.py masks phone numbers and emails in what it prints. Leave the original report
where it came in and call the sender "the reporter".

## Account issues
Never ask a member for a password, an OTP or a screenshot that shows one. If a member
sends one anyway, tell the CEO; the credential must be treated as exposed.

## Data exposure is an incident
If a page, export or message shows other people's personal data, it is an incident:
tell the CEO immediately with what is exposed and where, and touch nothing.

## Check before review
`tools/draft_lint.py` flags mobile numbers, personal emails and 12-digit IDs. Its silence
is not proof: also read for names taken from members.json or an export.
