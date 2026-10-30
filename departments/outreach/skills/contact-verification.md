# Skill: contact verification — never invent a contact

A contact you cannot point at a public source is a fabrication. This is the single
biggest integrity risk in the department, so treat "verified" as a claim you must
back up.

**How to prove an address is public.** Record, in the prospect record, the exact
page where the address appears and what it is labelled. Acceptable evidence:
- a role address printed on the company's own site — e.g. a "Contact", "Partners",
  "Community", "Events", or footer address (`partnerships@`, `marketing@`,
  `community@`, `hello@`), cited as `published on <full page URL>`;
- an address shown in a program page's Q&A ("Where can I reach out?" -> address);
- a page footer or "become a partner" block that names the inbox.
Write the fetch date next to it. If you read it off a search snippet rather than
the company page, say so and re-open the page; a snippet is not proof.

**What "via form" means and when to use it.** When the only public door is a web
form, or nothing community/education-specific is published, the contact is the
contact form, not a guessed person. Write:
`Contact: via form - <full form URL>` (secondary addresses may follow, labelled).
Never convert a form into an invented mailbox. The literal token `via form` is the
documented fallback and is what `email_gate.py` accepts in place of an address.

**Red flags — stop and mark via form (or BLOCKED):** a "guessed" pattern like
`firstname@company.com` you did not see published; a personal free-mail address
(gmail/outlook/etc) presented as a company contact; a number scraped from a
directory. Any of these is invented. The draft is wrong until the contact is a
published address or `via form`.

Worked contrast — good: `partners@corp.example - published on corp.example/partners
(read 2027-11-01)`. Bad: `maybe-ceo@corp.example (guess)`. The second is never
drafted.
