# Preview and render pipeline

The CEO reviews the preview PNG, never the source. Each round ends with a fresh preview
on disk, its exact path named in the issue comment.

Chrome: look, never guess. `ls -d ~/.cache/puppeteer/chrome/*/chrome-linux*/` gives
`/home/ubuntu/.cache/puppeteer/chrome/linux_arm-155.0.8059.79/chrome-linux-arm64/chrome`
on this VM (30 Oct 2026); chrome-headless-shell is the fallback. render_preview.py does
the lookup.

Commands:
- Card 1080x1920: `tools/render_preview.py index.html preview.png --width 1080 --height 1920`
- WhatsApp check `--width 720 --height 1280`; square 1080x1080; portrait 1080x1350.
- A4 landscape print (`@page { size: A4 landscape; margin: 0 }`):
  `tools/render_preview.py index.html preview.png --mode print --dpi 200 --width 2339 --height 1654 --keep-pdf`
  (pdftoppm may give 2339x1653; 1 px tolerance is built in).
- Pixel-matched A4 screenshot (as cert-aarambh): `--width 1123 --height 794 --scale 2.0846`.
The tool prints the exact niced Chrome command it ran; paste that into the receipt.

Gate every preview: `tools/png_check.py preview.png --width W --height H` and
`tools/contrast_check.py index.html`. Text over a photo or a positioned panel: put
`/* contrast: bg #RRGGBB */` in that rule, naming the worst area under the text.

VM manners: 2 vCPUs, live services. One render at a time, nice -n 19, no Chrome left
running, scratch renders deleted.

Visual complaints: first check and record the viewer's browser zoom (100 %, Ctrl+0).
Soft text at 90 or 110 % is the viewer, not the design. Then compare at 100 % and at
about 400 px wide.

Record the command; the preview must regenerate from source. Finals move to
`departments/design/templates/<slug>/` only on the CEO's decision.
