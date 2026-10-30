# Checklist: invitation QA (four-lane Design Team)

Used by the CEO and Lane C before anything is shown to Lakshya. Each line is a pass or a
fix with an exact location. Nothing is sent or posted by any lane.

## Dispatch (CEO, before any lane starts)
- [ ] Four issues with distinct titles: Lane A spec, Lane B build, Lane C style, Lane D render
- [ ] Every lane agent is healthy and has no other open invitation issue
- [ ] Each issue states: first receipt 15 min, done 45 min, receipt = file on disk + comment
- [ ] Separate workdirs: `<slug>-spec/`, `<slug>-build/`, `<slug>-style/`, `<slug>-render/`

## Lane A: DESIGN_SPEC.md
- [ ] `tools/design_spec_lint.py DESIGN_SPEC.md` exits 0
- [ ] Concept in 3 lines; palette in exact hex with text pairs; sizes for every text role
- [ ] Layering order bottom to top; movement arc in seconds ending in a 2-3 s hold
- [ ] Audio direction with fades; do-not-reuse lists everything rejected before, with dates

## Lane B: Stage 1 (before any full render)
- [ ] Closing-card preview PNG at the master size, `png_check.py` passes
- [ ] `contrast_check.py index.html` passes
- [ ] 3-5 s motion sample of the busiest beat, `frame_check.py ... --min-duration 3` run
- [ ] Built only from the spec; any conflict raised to the CEO, not decided

## Lane C: style verdict on the first preview
- [ ] Layer order matches the spec (no ornament above text)
- [ ] Contrast AA on every text element; smallest text legible at 400 px wide
- [ ] No ghosting: no trace of old text, no doubled edges, no collisions
- [ ] Crest integrity: `png_check.py --require-alpha --same-as <official>` exit 0, no halo
- [ ] Verdict is APPROVE or a FIX-LIST with file:line and exact fixes, in STYLE_VERDICT.md

## Lane D: WhatsApp 720p first
- [ ] 720x1280, H.264 yuv420p, AAC; `frame_check.py --profile whatsapp --require-audio` exit 0
- [ ] Frames at 0/25/50/75/100 % and the closing frame opened and looked at
- [ ] Closing frame held 2-3 s, gentle fade-out, no zoom still running at the end
- [ ] Audio balanced (peak below -1 dBFS), fades in and out, no clipping
- [ ] No blinking anywhere
- [ ] RENDER_RECEIPT.md lists absolute paths, bytes, duration, resolution, frame paths, commands

## Master 1080x1920 (only after the CEO approves the 720p)
- [ ] `frame_check.py --profile master --require-audio` exit 0
- [ ] Same closing frame and timings as the approved 720p

## Brand (every lane)
- [ ] Official CCSU crest only; small clean NAAC A++ badge only if it fits
- [ ] Aarambh: "The SCRIET Family", no Code.SCRIET branding
- [ ] Lakshya's photo untouched
- [ ] Every artifact marked DRAFT FOR CEO REVIEW; nothing sent, posted or published
- [ ] Round count recorded; at round 3 without approval the CEO is asked to take the pen
