# Invitation jobs: the four-lane Design Team

An invitation is never a solo job (ROUTING section 16). If one arrives as one task:
`RESULT: ESCALATED - this invitation needs the four-lane split (A spec, B build, C style, D render); please dispatch it that way.`

Lane A, analyze (research lane; gates the build). Read the brief, references, earlier
CRITIQUE.md and style verdicts. Write DESIGN_SPEC.md from templates/DESIGN_SPEC.md:
concept in 3 lines, exact #RRGGBB palette with each text pair as "#fg on #bg",
typography with sizes, layering bottom to top, movement in seconds ending in a 2-3 s
hold, audio with fades, do-not-reuse. Gate: `tools/design_spec_lint.py` exits 0.
Receipt within 15 min. No render.

Lane B, build (design-1). Only from the spec, in `work/<slug>-build/`; conflicts go to
the CEO, never re-decided. Stage 1 first: closing card preview PNG plus a
3-5 s motion sample. Gates: `tools/contrast_check.py` on the HTML, `tools/png_check.py`
on the preview. Receipt 15 min after the spec; hard clock 45 min.

Lane C, style (another model family). Verdict on Lane B's first preview from
templates/STYLE_VERDICT.md: layer order, contrast, phone legibility, ghosting, crest.
APPROVE or a FIX-LIST with file:line and exact fixes. Never rebuilds or rules on taste.

Lane D, render and QA. Own workdir; the only writer of the delivery folder.
WhatsApp 720x1280 first; 1080x1920 master only after the CEO approves the 720p.
`tools/frame_check.py` on each; RENDER_RECEIPT.md with paths and byte sizes.

Rules:
- Separate workdirs, one integrator (Lane D), single-flight, no reused issue titles.
- A heartbeat or "still working" comment is not a receipt.
- No receipt by 45 min: the CEO takes the pen. No third retry of an unchanged plan.
- At most 3 art-direction rounds, then
  `RESULT: ESCALATED - round 3 not approved; CEO to take the pen or change the brief.`
