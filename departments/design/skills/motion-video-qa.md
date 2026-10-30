# Motion and video QA

Motion serves the reading order. Allowed: fades, 4-12 px drifts,
one slow camera settle that ends before the hold. Banned: blinking, flashes, shimmer
sweeps, sparkle particles, bounces, a zoom still running at the end.

Shape (10-20 s): fade up from black in about 1 s; the spec's beats; the complete card
held still 2-3 s; a gentle fade to black over about 1 s.

Stage 1 before any full render: closing card PNG plus a 3-5 s sample of the busiest beat.
The CEO approves the look on these; a full render costs minutes on 2 vCPUs.

Order: WhatsApp 720x1280 first (H.264, yuv420p, AAC); the 1080x1920 master only after
the CEO approves the 720p. `nice -n 19 ffmpeg ... -threads 2`, one render at a time.

Audio: one balanced bed, peak below -1 dBFS, mean near -20 dB,
`-af "afade=t=in:d=1,afade=t=out:st=<duration-1.5>:d=1.5"`. No hard start, no clipping.

QA every render:
`tools/frame_check.py out-720.mp4 qa-720/ --profile whatsapp --require-audio --hold 2`
(`--profile master` for 1080x1920). It writes frame_000/025/050/075/100.png,
frame_closing.png and FRAME_CHECK.json, and fails on wrong resolution, too short, motion
at the end, no fade or a hard cut, blinking regions, clipping, missing audio fades.
Then look at the six frames: crest crisp, no ghost text, nothing cut at the edges,
small text legible on a phone, closing frame is the complete card.
Exceptions (silent by brief) use `--allow-no-fade` / `--allow-flicker`, reason in the receipt.

Receipt per mp4: absolute path, bytes, duration, resolution, the six frame paths, the
exact commands, all in RENDER_RECEIPT.md, which the issue comment names.
