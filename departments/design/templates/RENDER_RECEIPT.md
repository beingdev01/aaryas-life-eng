# RENDER RECEIPT - [fill: job name] (Lane D)

DRAFT FOR CEO REVIEW. A receipt is files on disk at exact paths with sizes, plus the
commands that made and checked them. A heartbeat or a "still rendering" comment is
not a receipt.

- Issue: [fill: board issue id]
- Spec: [fill: exact path of DESIGN_SPEC.md]  Style verdict: [fill: exact path of STYLE_VERDICT.md]
- Round: [fill: 1, 2 or 3 of 3]
- Delivery folder (Lane D only writes here): [fill: absolute path]

## Stage 1 - preview frames and motion sample (before any full render)

| file | size (bytes) | dimensions | check |
|---|---|---|---|
| [fill: preview PNG path] | [fill] | [fill] | `png_check.py` exit [fill] |
| [fill: 3-5 s motion sample path] | [fill] | [fill] | `frame_check.py ... --min-duration 3` exit [fill] |

CEO response to Stage 1: [fill: approved / changes requested, with the comment id]

## Stage 2 - WhatsApp 720p (rendered first)

| file | size (bytes) | duration | resolution |
|---|---|---|---|
| [fill: absolute path of the 720x1280 mp4] | [fill] | [fill] s | 720x1280 |

`frame_check.py <mp4> <qa-dir> --profile whatsapp --require-audio` exit [fill: code]

| frame | time (s) | path |
|---|---|---|
| 0 % | [fill] | [fill: qa-dir/frame_000.png] |
| 25 % | [fill] | [fill: qa-dir/frame_025.png] |
| 50 % | [fill] | [fill: qa-dir/frame_050.png] |
| 75 % | [fill] | [fill: qa-dir/frame_075.png] |
| 100 % | [fill] | [fill: qa-dir/frame_100.png] |
| closing hold | [fill] | [fill: qa-dir/frame_closing.png] |

Closing frame held [fill: seconds] s, then fade-out over [fill: seconds] s. Audio mean
[fill] dB, peak [fill] dBFS, fade in [fill] s, fade out [fill] s.

## Stage 3 - master 1080x1920 (only after the CEO approves Stage 2)

| file | size (bytes) | duration | resolution |
|---|---|---|---|
| [fill: absolute path of the 1080x1920 mp4] | [fill] | [fill] s | 1080x1920 |

`frame_check.py <mp4> <qa-dir> --profile master --require-audio` exit [fill: code]

## Commands used
```
[fill: the exact render and check commands, copied from the shell, with nice -n 19]
```

## Not done
- Nothing was sent, posted or published. The CEO decides what goes out and when.
