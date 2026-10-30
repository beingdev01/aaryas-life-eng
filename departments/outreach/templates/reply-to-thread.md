# Template: reply to a sponsor thread (DRAFT — never sent from here)

Use when the CEO hands over a reply to draft. Fictional example. Answer their
questions directly, stay honest about scope, commit to no number, price, or
deliverable the club has not approved, and give exactly one next step.

DRAFT marker line above the email: `Reply draft (draft-and-hold)`.

---

Subject: Re: [original subject]

Hi [Name],

Thanks for getting back to us. [Answer their first question directly and honestly.]
[Answer the next; where we cannot confirm something, say what we can confirm and
what we will check before a call — never invent a figure.]

On [their specific ask]: [agree only to what is in our real offer catalogue —
branding on https://codescriet.dev and posters, a named session or contest, a short
team slot, certificate mentions, social features, hiring access to members. For
anything about money, pricing, contracts, exclusivity, or deliverables: do not
answer in the draft — stop and escalate to the CEO.]

Next step: [one clear, concrete action — e.g. "we'll fill the form you linked with
our next contest details" or "does a 15-minute call this week work?"].

Best,
[Name], [signature_title], Code.SCRIET
https://codescriet.dev

---

Save as `work/prospects/reply-YYYY-MM-DD-<company>.md`, then update the pipeline row
status to `replied` and set the `next step` cell. Gate: `email_gate.py` must exit 0.
If the thread raised commercial terms, the correct output is an ESCALATION note to
the CEO, not a sendable reply.
