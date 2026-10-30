# Sponsor Prospects — 2027-11-01

Prepared by outreach-1 (Prospect Hunter). Fictional example.

Drafts are draft-and-hold only: each needs CEO (Muse) review and Owner (Lakshya)
approval before anything leaves the building. Nothing here has been sent.

- Tier mix today: [startup / dev-tools / local / large]. Pipeline tier counts: [..].
- Theme de-collision: [list which themes are already owned so none is repeated].
- Dedupe: ran `seen_check.py --pipeline work/pipeline.md --days 180` for each company;
  all exited 0 (clear) before drafting.

---

## 1. [Fictional Sponsor Corp]

- **Company:** [what they do, in one line, with the page you read it from].
- **Tier:** [large | startup | dev-tools | local]
- **Contact:** [partnerships@example.test — published on example.test/partners
  (read 2027-11-01)]  OR  [via form - https://example.test/contact]. Never a guessed
  or personal mailbox.
- **Angle:** [2-3 lines: the concrete member activity, the exact fit for this
  sponsor, the single tier-appropriate offer. No invented numbers, no money.]

**First-touch draft** (draft-and-hold)

```
From: "Code.SCRIET" <outreach@codescriet.dev>
To: partnerships@example.test (published on example.test/partners, read 2027-11-01)
Subject: [One specific themed proposal] with Code.SCRIET, SCRIET Meerut

Hi [Team],

I'm [Name], [signature_title] at Code.SCRIET (https://codescriet.dev), the coding club of SCRIET, CCSU Meerut.

[Themed angle body — one concrete thing our members do, the fit, the single offer.]

Would you be open to a 15-minute call next week?

Best,
[Name], [signature_title], Code.SCRIET
https://codescriet.dev
```

---

## 2. [Second Fictional Company]
[repeat the same four fields and draft block]

## 3. [Third Fictional Company]
[repeat the same four fields and draft block]

---

Gate the whole file before handing to the CEO:
`python3 <kit>/tools/email_gate.py work/prospects/2027-11-01.md` must exit 0,
and `seen_check.py` on this file's companies must exit 0.
