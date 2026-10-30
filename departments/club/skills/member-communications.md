# Member communications

Every message is a draft for the CEO: club-1 writes it, lints it, and stops. It never
sends, posts or schedules, and never says it did.

## Tone
Plain, warm, specific. Write as a club officer talking to a classmate, not as a brand.
One message, one purpose, one ask.

## Announcement structure (templates/announcement.md, under 300 words)
1. Subject: event name and weekday date.
2. First line: what, when (weekday, date, start and end time), where.
3. What people will do or leave with, in one or two concrete sentences.
4. Who it is for and what to bring.
5. How to register, with the full URL (https://codescriet.dev/<page>) and the deadline.
6. Certificates or follow-up only if the date is already fixed.
7. Contact by role, signed by a role: "Technical Head, Code.SCRIET".

Reminder (T-7 or T-1): under 120 words, time and place first. Thank-you (T+1): one specific thing that happened, the real count from the
database export, the next step only if it exists. Certificate notice: only after the CEO
fixes the release date.

## Never in a message
- Private data: phone numbers, personal emails, roll numbers, anyone's attendance.
- An unconfirmed date, time or venue. If it is not approved in writing, the draft waits.
- A bare "codescriet.dev". Always https://codescriet.dev.
- Promises without a date ("certificates soon"), hype ("excited to announce", "don't
  miss out"), emojis, decorative symbols, exclamation runs.
- "Team Code.SCRIET" as a signature, or any line saying it was sent or posted.

## Lines that work, and lines that do not
- Works: "Bring your college ID; the lab machines are ready, so no laptop is needed."
- Does not: "Get ready for an epic session!! Details soon."

## WhatsApp versus email
WhatsApp: plain text, no tables or headings; the first two lines carry the message,
as that is all the preview shows. Email: a subject line, short paragraphs, same facts.

## Gate
`tools/draft_lint.py <draft> --max-words 300` for announcements (900 for reports). Name
drafts `<event>-announcement-draft.md`, `<event>-reminder-draft.md`,
`<event>-thanks-draft.md` so the engine's gates find them. Fix every reported line;
never pass `--allow-contact` unless the CEO asked for a contact line.
