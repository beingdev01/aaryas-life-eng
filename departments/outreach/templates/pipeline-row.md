# Template: pipeline row (work/pipeline.md)

`work/pipeline.md` is the single source of truth. Fictional example. Copy the header
exactly so `pipeline_lint.py` and `seen_check.py` can find the columns by name.

Columns (fixed order): `prospect | tier | contact | angle | status | last touch |
next step | notes`

Allowed status values (nothing else): `new`, `approved`, `sent`, `replied`,
`meeting`, `sponsored`, `declined`, `parked`.

Rules the lint enforces: every row has all 8 cells, a non-empty prospect, a status
from the list, a valid ISO `YYYY-MM-DD` in `last touch`, and a non-blank `next
step`. No company appears twice.

---

```
| prospect | tier | contact | angle | status | last touch | next step | notes |
|---|---|---|---|---|---|---|---|
| Fictional Sponsor Corp | startup | partnerships@example.test (read 2027-11-01) | data-modelling workshop with branding on material and certificates | new | 2027-11-01 | CEO review digest; Owner approval before any send | Added by outreach-1 daily prospecting; draft at work/prospects/2027-11-01.md; nothing sent |
```

---

Field notes:
- **contact** carries the source or `via form`, never a guessed address.
- **last touch** is the ISO date of the most recent action (draft, send, reply) — the
  `seen_check.py` cooloff and the 5-day follow-up spacing both read from it.
- **next step** is the exact action and owner (e.g. "book slot, then move to
  meeting"), never blank. A row with no next step is a dropped thread.
- Only the CEO updates a row to `sent`, and logs the date. This department only ever
  writes `new`/`replied`-context drafts and `declined` on follow-up exhaustion.

Validate after every edit:
`python3 <kit>/tools/pipeline_lint.py work/pipeline.md` must exit 0.
