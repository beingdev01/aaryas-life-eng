# STYLE VERDICT - [fill: job name] (Lane C)

DRAFT FOR CEO REVIEW. Lane C is an independent check on Lane B's first preview. It
never rebuilds and never approves its own build. The CEO stays creative director.

- Issue: [fill: board issue id]
- Reviewer: [fill: agent name] (model family different from the builder's)
- Artifact reviewed: [fill: exact path of preview PNG or frame], [fill: width x height]
- Spec checked against: [fill: exact path of DESIGN_SPEC.md]
- Viewing: preview PNG at 100 % and at phone width (about 400 px), browser zoom 100 %
  confirmed before judging anything that looks soft or misaligned.

## Verdict: [fill: APPROVE or FIX-LIST]

## Must-fix (blocks the render)
Each item names the file, the line or region, what is wrong, and the exact fix.
- [fill: F1 - file:line or x,y region - defect - exact fix]

## Should-fix (CEO decides)
- [fill: item, or "none"]

## Checks run

| check | result | evidence |
|---|---|---|
| Layer order matches the spec | [fill: pass / fail] | [fill: z-index values or layer list] |
| Text contrast (WCAG AA) | [fill: pass / fail] | `contrast_check.py index.html` exit [fill: code], worst [fill: ratio] |
| Phone legibility (smallest text at 720 px wide) | [fill: pass / fail] | [fill: smallest size and how it reads at 400 px] |
| Ghosting or overlap (old text, double edges, collisions) | [fill: pass / fail] | [fill: regions inspected] |
| Crest integrity (official PNG, no box, no halo, not redrawn) | [fill: pass / fail] | `png_check.py <crest> --require-alpha --same-as <official>` exit [fill: code] |
| Spacing rhythm (gaps between text blocks even, measured) | [fill: pass / fail] | [fill: measured gaps in px] |
| No blinking, no decorative accents outside the spec | [fill: pass / fail] | [fill: what was looked at] |
| Aarambh only: no Code.SCRIET branding, "The SCRIET Family" wording | [fill: pass / fail / n.a.] | [fill: text found] |

## Not in scope (taste, for the CEO)
- [fill: hierarchy or density questions Lane C noticed but must not decide]

RESULT: [fill: DONE with this verdict on disk at its exact path]
