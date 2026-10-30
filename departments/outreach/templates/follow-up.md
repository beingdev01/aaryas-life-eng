# Template: follow-up email (DRAFT — max 2 per prospect, at least 5 days apart)

Fictional example. Keep it one short nudge. Do not re-open a `declined` company
inside the cooloff window. No new numbers, no money, no hype, no emoji. Full URL in
body and signature.

DRAFT marker line above the email: `Follow-up draft (draft-and-hold)`.

---

Subject: Re: [original subject]

Hi [Team],

Just floating this back up — [one line reminding them of the single themed offer,
unchanged from the first touch].

If the timing isn't right, no worries at all. But if there's a lighter way to
collaborate — a workshop slot, goodies for a hackathon, or even just advice for our
members — we'd be glad (https://codescriet.dev).

Thanks either way,
[Name]
[signature_title], Code.SCRIET | https://codescriet.dev

---

Notes for outreach-2:
- This is follow-up #N (2 at most). If no human reply after #2, mark the pipeline
  row `declined` and set cooloff.
- Gate: `python3 <kit>/tools/email_gate.py <follow-up.md>` must exit 0.
