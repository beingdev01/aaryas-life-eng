# Template: first-touch email (DRAFT — never sent from here)

Fictional example only. Replace every bracketed field. A real contact must be a
published public address with its source, or `via form`. Nothing here is sent: the
CEO sends from outreach@codescriet.dev only after the Owner approves.

DRAFT marker (keep on the line above the email): `First-touch draft (draft-and-hold)`.

---

Subject: [One specific themed proposal] with Code.SCRIET, SCRIET Meerut

Hi [Team],

I'm [Name], [signature_title] at Code.SCRIET (https://codescriet.dev), the coding
club of SCRIET, CCSU Meerut.

[Two or three lines: the themed angle. One concrete thing our members do, the exact
fit for this sponsor's product or program, and the specific, tier-appropriate offer.
No invented numbers, no money, no hype words, no emoji.]

We'd like to explore one small partnership: [concrete, single offer — e.g. "a
co-branded [Topic] session with your branding on the material and certificates, and
the session listed on https://codescriet.dev"].

Would you be open to a 15-minute call next week?

Best,
[Name], [signature_title], Code.SCRIET
https://codescriet.dev

---

Envelope block to include with the draft:

```
From: "Code.SCRIET" <outreach@codescriet.dev>
To: [partnerships@company.example - published on company.example/partners (read 2027-11-01)]  OR  via form - [full form URL]
Subject: [same subject line as above]
```

Gate it before offering for approval:
`python3 <kit>/tools/email_gate.py <draft.md>` — it must exit 0.
