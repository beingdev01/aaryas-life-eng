# Design runbook: how a design task runs through the engine

## 1. Intake
A design task starts as a Paperclip issue assigned to design-1, or as four issues for an
invitation (one per lane, distinct titles). The CEO turns it into an engine spec:

```
engctl draft --issue AAR-<n>            # draft and validate the spec, stop for review
engctl run   <spec.yaml>                # run it once the paths look right
engctl draft --issue AAR-<n> --run      # both in one step, for routine jobs
```

Check the drafted spec before running a design job: every deliverable path must sit
under `/home/ubuntu/aaryas-life/departments/design/work/<slug>/`, and the preview's
exact size must be in an acceptance command (the department templates check that a PNG
is real, not that it is 1080x1920). If the request is really a taste question, the
drafter returns `RESULT: ESCALATED - <question>` and nothing runs.

## 2. What the engine adds from this kit
- `profile.yaml` is loaded for design-1 (depth 3: 3 recon slices, 1 review round, red
  team on, 2 fix rounds). The mission, may/never lists, tool list and the five skills
  are injected into every lane prompt.
- Acceptance templates become engine-run gates on matching deliverables:
  `*.png` -> `tools/png_check.py`, `DESIGN_SPEC*.md` -> `tools/design_spec_lint.py`,
  `*.html` -> `tools/contrast_check.py`. A gate is an exit code, not an opinion.
- Stages: recon -> plan -> red team -> parallel build -> gates -> cross-family review ->
  fix -> integrate -> verify -> report. The report is generated from the ledger.

## 3. What each gate checks
| gate | passes only if |
|---|---|
| png_check | real PNG: signature, IHDR first, every CRC valid, IDAT present, IEND last, at least 1 KB; plus any size, preset, byte, alpha or `--same-as` flags in the spec |
| contrast_check | every visible text element meets 4.5:1 against the background behind it (3:1 at 24 px+, or 18.66 px+ bold); aria-hidden ornaments skipped |
| design_spec_lint | concept, exact hex palette with "#fg on #bg" pairs passing AA, typography with sizes, 3+ ordered layers, timed movement with a closing hold, audio with fades, do-not-reuse list; no blinking, no altered crest, no Code.SCRIET on Aarambh, no template leftovers |
| frame_check (add to video specs) | 720x1280 or 1080x1920, long enough, six frames written, still at the end, gentle fade, no blinking, audio unclipped with fades |

## 4. Worked example: Code.SCRIET Git workshop poster, 1080x1350
Issue: "Poster for the Code.SCRIET Git and GitHub workshop, Instagram portrait". The
brief gives exact copy, date, the SCRIET computer lab, and https://codescriet.dev.

Spec deliverables (workdir `.../design/work/git-workshop-poster/`):
`index.html` (min 3000 bytes), `preview.png` (min 40000 bytes), `CRITIQUE.md` (min 800).
Engine-expanded gates: `png_check.py .../preview.png`, `contrast_check.py .../index.html`.
Spec-added checks:
```
python3 <kit>/tools/png_check.py .../preview.png --preset portrait-1080x1350
python3 <kit>/tools/render_preview.py .../index.html /tmp/regen.png --width 1080 --height 1350
grep -q "DRAFT FOR CEO REVIEW" .../CRITIQUE.md
```
Build lane: copies the cert-normal palette (navy #0f2a4a, gold text #7a6114, paper
#f7f4ec), local fonts, writes index.html, renders preview.png. First gate run:
contrast_check fails `p.date "Saturday 14 November"` at 3.44:1 (navy at 55 % opacity).
The fix lane raises it to solid #42566e (6.82:1), re-renders, all gates pass. The
reviewer (another model family) flags the 22/48 px gaps around the venue line; fixed
to 36/36 px. Report: three files with sizes, gate transcripts, round 1 of 3. The CEO
reviews preview.png and replies with art direction or approval.

Invitation version of the same flow: four issues. Lane A's spec deliverable is
`DESIGN_SPEC.md` (lint gate). Lane B's are `index.html` and `preview.png` plus a 3-5 s
sample mp4. Lane C's is `STYLE_VERDICT.md`. Lane D's are the 720p mp4 and
`FRAME_CHECK.json` (frame_check gate with `--profile whatsapp --require-audio`); the
master is a separate run after the CEO approves the 720p.

## 5. Failure modes and what to do
| symptom | cause | action |
|---|---|---|
| contrast_check FAIL on gold body text | gold used below 24 px | darken to the spec's text gold or enlarge to display size; never add glow |
| png_check width/height off by a few px | wrong `--scale` or window size | recompute W x scale; print mode allows 1 px |
| render_preview "no Chrome found" | cache moved | `ls -d ~/.cache/puppeteer/*/*/`; pass `--chrome` |
| render_preview timeout | VM busy or a network font | wait for load to drop; local fonts only |
| frame_check closing-hold FAIL | zoom or reveal runs to the end | end motion earlier; hold the full card 2-3 s |
| frame_check no-blink FAIL | a pulse, sparkle or shimmer | remove the effect; the rule is no blinking |
| design_spec_lint FAIL | spec vague or a template leftover | Lane A fixes the spec; Lane B does not start |
| CEO says the preview is blurry | browser zoom not 100 % | ask, record the zoom, then compare at 100 % |
| no receipt after 45 min | lane stalled | CEO takes the pen; never a third retry of the same plan |
| comment write returns 403 | known board-write issue (AAR-103 class) | keep the receipt file on disk; name its path in the RESULT line |
| round 3 not approved | taste gap | `RESULT: ESCALATED - round 3 not approved; CEO to take the pen or change the brief` |
