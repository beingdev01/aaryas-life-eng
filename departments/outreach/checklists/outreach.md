# Outreach review checklist — run before a draft is offered for approval

A reviewer (outreach-2 or the CEO) checks every item. If any fails, the batch goes
back to outreach-1 and is NOT offered for Owner approval. This department never
sends; the outcome here is a clean draft handed to the CEO.

- [ ] **Signature title confirmed.** The CEO has confirmed the Owner's decision on
      the signature title (currently defaulted to "Technical Head" per the live
      runbook, in `profile.yaml` `settings.signature_title`). No first-touch draft is
      approved until this is settled — this is an open Owner decision, not ours to
      pick silently.
- [ ] **DRAFT only.** Every artifact is marked draft-and-hold; nothing claims to have
      been sent, and no file says "I've sent this". Sends go only via the CEO from
      outreach@codescriet.dev after Owner approval.
- [ ] **Sender correct.** `From: "Code.SCRIET" <outreach@codescriet.dev>`.
- [ ] **Contact is real or is the fallback.** Each contact is a published public
      address with its source page and read-date, or the literal `via form` against
      a form URL. No guessed pattern (`first@company`), no personal mailbox
      (gmail/outlook/etc), no scraped directory number.
- [ ] **Website link.** The full URL `https://codescriet.dev` appears in BOTH the body
      and the signature. No bare `codescriet.dev`, no `http://`.
- [ ] **Voice is human.** Plain and specific, short (one ask), no emoji, no AI-hype
      phrasing.
- [ ] **Angle is themed, not spam.** One concrete member activity mapped to this
      sponsor's product; the theme is not already owned by another prospect.
- [ ] **Scope is honest.** No member counts, reach, engagement, follower, or
      past-sponsor numbers unless approved and sourced. No promise of money, credits,
      swag, prizes, dates, exclusivity, or deliverables.
- [ ] **No commercial terms.** If a reply raised pricing/money/contract, the output is
      an escalation to the CEO, not a drafted answer.
- [ ] **Not a duplicate.** `seen_check.py` exits 0 against the pipeline (no company
      already contacted or declined within the cooloff).
- [ ] **Gates pass.** `email_gate.py` exits 0 on every draft in the batch, and
      `pipeline_lint.py` exits 0 on `work/pipeline.md`.
- [ ] **Pipeline updated.** A row exists per prospect with an allowed status, an ISO
      `last touch`, and a non-blank `next step`.
- [ ] **Receipt ends right.** `RESULT: DONE` with the exact paths written, or
      `RESULT: BLOCKED - <reason>`.

One consolidated digest to Lakshya each morning via the CEO; one thread per prospect;
at most 2 follow-ups at least 5 days apart, then `declined`.
