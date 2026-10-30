# Brand rules and asset integrity

These hold whatever a brief says; if a brief conflicts, stop and escalate. `tools/...`
means this kit's tools (full paths in the tools list above).

## CCSU crest
- Only the official transparent PNG: `/home/ubuntu/clubsite-git/apps/api/public/logos/ccsu-new.png`
  (722x857 RGBA; identical copy in `departments/design/templates/cert-aarambh/assets/ccsu-crest.png`).
  Copy it into your workdir; never edit it in place.
- Never redraw, trace, regenerate, AI-upscale, recolour, or add a box, halo, glow or
  shadow. An AI-redrawn crest was rejected on 20 Oct 2026 because it looked fake.
- Never above 100 % scale. About 260-360 px tall on 1080x1920, about 30 mm on A4.
- Prove it in the receipt: `tools/png_check.py crest.png --require-alpha --same-as <official>`

## NAAC A++ badge
Small and clean, only if it fits without crowding the crest. Drop it before tightening
any spacing to make room.

## Aarambh versus Code.SCRIET
- Aarambh (CCSU orientation) invitations: no Code.SCRIET wordmark, logo or URL. The host
  line "The SCRIET Family" is correct; do not change it.
- Code.SCRIET club work: the cert-normal palette, navy #0f2a4a, gold #c9a227 (rules),
  gold text #7a6114, paper #f7f4ec.

## Lakshya's photo
Use his file exactly: no retouch, cut-out, filter or AI enhancement. Crop only with his OK.

## Copy and data
Names, titles, dates, venues verbatim from the brief. Never invent a date, guest, time
or signatory; flag odd spellings for the CEO instead of fixing them. No phone numbers or
emails on a design unless the brief puts them there.

## Fonts
Local @font-face files in `fonts/` beside the HTML; network fonts fall back silently.

## Taste (binding)
Premium, typographic first, 2-3 colours, generous spacing, subtle purposeful motion. No
blinking, no odd decorative accents, no fake-foil gradients, nothing AI-polished. When
in doubt, remove it.
