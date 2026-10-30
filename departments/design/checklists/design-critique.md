# Checklist: design critique (every draft, before the CEO sees it)

Run this on the rendered preview PNG at 100 % and at about 400 px wide, with browser zoom
confirmed at 100 %. Every failed line becomes a note in CRITIQUE.md in the form
`[axis] location - what is wrong, measured - exact fix`. Mark the file DRAFT FOR CEO REVIEW.

## Mechanical gates (all must exit 0; paste the output)
- [ ] `tools/png_check.py preview.png --width W --height H` (or `--preset ...`)
- [ ] `tools/contrast_check.py index.html`
- [ ] `tools/png_check.py <crest copy> --require-alpha --same-as <official crest>` if the crest appears
- [ ] The preview regenerates from source with the recorded `render_preview.py` command

## Hierarchy
- [ ] One loudest element, at least 1.5x the next size
- [ ] Reading order matches the brief's order of information
- [ ] Nothing competes with the hero in weight or colour

## Spacing
- [ ] Gaps inside each text group equal (measured, in px)
- [ ] Gaps between groups larger than gaps inside groups
- [ ] Safe margin: 10 mm on print, 64 px on screen; nothing touches the frame

## Type
- [ ] At most 3 families, about 4 sizes, all loaded from local files
- [ ] Smallest text 30 px or more on 1080x1920 (legible on the 720p copy)
- [ ] Caps tracked 0.12-0.2em; body text not tracked; no orphaned single word on a line

## Colour
- [ ] Only the spec's hex values; 2-3 colours plus neutrals
- [ ] Gold used for text only where the pair passes AA

## Brand and integrity
- [ ] Crest is the official PNG: no box, halo, glow, redraw or recolour; not above 100 % scale
- [ ] NAAC A++ badge only if it fits cleanly
- [ ] Aarambh: no Code.SCRIET branding; host line reads "The SCRIET Family"
- [ ] Lakshya's photo untouched
- [ ] Copy matches the brief word for word; no invented dates, names or times
- [ ] Any URL to the club site is written in full as https://codescriet.dev

## Taste guards
- [ ] No blinking, no decorative accents the spec does not list, no fake-foil gradients
- [ ] Nothing looks AI-polished; when in doubt it was removed
- [ ] Taste questions listed under "Not in scope (taste, for the CEO)", not decided

## Round record
- [ ] Round number (1, 2 or 3 of 3) and what changed since the last round
- [ ] Exact paths of source, preview and critique in the issue comment
