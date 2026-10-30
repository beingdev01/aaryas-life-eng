# Skill: the draft email format (the shape email_gate.py checks)

Every outreach email is a DRAFT and follows one fixed shape. Get this right and the
gate passes; skip a part and it fails.

**Header block**
- `From: "Code.SCRIET" <outreach@codescriet.dev>` — the sender is fixed, always.
- `To:` a verified public contact from its source, or `via form - <full form URL>`.
  Never a guessed or personal mailbox.
- `Subject:` a specific themed proposal, e.g. "A testing session before you ship -
  Company and Code.SCRIET". No clickbait, no emoji.

**Body**
- Opening line: who you are, in one sentence, with the club's full URL
  `https://codescriet.dev` used *inline* (that is the body copy of the link rule).
- Two or three lines: the themed angle (see skills/themed-angles.md) — one concrete
  member activity, the fit for this sponsor, and the specific offer.
- Exactly one ask: a 15-minute call next week, or a reply. Nothing more.
- Plain, human, short (roughly 150 words or fewer). No hype words (delve,
  seamless, game-changer, excited to announce), no emoji, no decorative symbols.

**Signature**
- A closing line on its own (`Best,` or `Thanks,`).
- A name/title line, then the club, then the URL as a full link:
  `https://codescriet.dev` on its own final line. This is the signature copy of the
  link rule: the site must appear as a full URL in BOTH the body and the signature.
- Use the title from `settings.signature_title` (default "Technical Head"); the CEO
  confirms the Owner's choice before the first approval.

**Hard line:** `https://codescriet.dev` is always written in full as `https://` —
never a bare `codescriet.dev`, never `http://`, never as plain text in the email
address context. A draft that claims it "sent" anything is rejected outright.
