# Skill: the relationship CRM

The store is `departments/personal/crm/people.json`, one record per person who matters.

Record shape (from `crm/README.md`; `crm/crm.py` is the CLI):

```json
{
  "id": "slug",
  "name": "Full Name",
  "relationship": "father | advisor | friend | mentor | ...",
  "contact_info": { "email": "...", "phone": "...", "affiliation": "..." },
  "birthday": "YYYY-MM-DD",
  "last_contact": "YYYY-MM-DD",
  "notes": "...",
  "tags": ["family", "priority"]
}
```

Rules that come from how the records are actually used, not from theory:

- **`id` is the address.** Use it in file names, reports and promises so a draft can be
  traced back without repeating a name. First name is fine in prose; a full name copied
  out of the CRM is not fine in an issue comment.
- **`last_contact` is only updated by a human action.** `crm.py touch <id>` is Lakshya's
  call. Never touch a record because you drafted something - the draft was not sent, so
  the contact did not happen. A stale date after a drafting run is a bug you introduced.
- **`birthday` may be month-day with an unknown year.** Some records carry `1990-01-01`
  purely to make the month readable. Compute age only when the year came from the Owner;
  otherwise write "birthday on 1 January" and never an age.
- **`contact_info` never leaves the CRM.** It is the one field with real harm potential.
  Drafts are addressed to Lakshya, who already has the number; putting it in the draft
  body gives a model lane a reason to repeat it.
- **`notes` is the source of specificity.** The difference between a good draft and a
  template is one detail from `notes` - the exam he was worried about, the surgery, the
  trip. Read it; if it is empty, ask Lakshya for the detail rather than writing "hope you
  are well".
- **`tags: priority`** means the stale threshold is halved (7 days, not 14).
- Absent is not zero. A missing `last_contact` means "unknown", which the sweep reports
  separately from "180 days" - do not sort unknowns to the bottom and lose them.

Seeded records that exist today: `father`, `advisor-1` (research advisor), `collaborator-1`
(PhD scholar, a conference paper paper), `contact-1` (an education foundation contact). The last two are
official-relationship contacts: their *content* belongs to Career, their *timing* here.
