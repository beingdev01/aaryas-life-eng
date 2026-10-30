#!/usr/bin/env python3
"""frame_check.py - QA a rendered invitation video before anyone watches it.

  frame_check.py invite-whatsapp.mp4 qa/            720x1280 or 1080x1920 accepted
  frame_check.py invite-whatsapp.mp4 qa/ --profile whatsapp --require-audio
  frame_check.py master.mp4 qa/ --profile master --hold 2.5

What it does (ffprobe + ffmpeg, run under nice -n 19, one thread):
  1. Reads duration, resolution, frame rate, codecs. Fails if the resolution is not
     the profile's (whatsapp 720x1280, master 1080x1920; auto accepts either) or the
     video is shorter than --min-duration.
  2. Writes frames at 0/25/50/75/100 % plus the held closing frame into OUTDIR
     (frame_000.png ... frame_100.png, frame_closing.png) for the CEO and Lane C.
  3. Closing hold: samples the last (--hold + --fade-window) seconds and requires
     the picture to be still. Brightness may fall (a fade keeps the structure, so the
     correlation stays high); a zoom, pan or reveal still in progress does not. This
     is the "no mid-zoom end" rule.
  4. Fade-out: the last frame must be clearly darker than the held frame, and no
     single 1/8 s step may drop more than 60 % of the held brightness (a hard cut).
  5. Blink check: flags any image region that swings bright/dark/bright/dark
     (4+ alternating swings inside 3 s). Lakshya's rule is no blinking.
  6. Audio (if present): no clipping (peak below -0.1 dBFS), mean level between
     -35 and -9 dB, quieter first 0.3 s (fade-in) and last 0.3 s (fade-out).
Results go to stdout and OUTDIR/FRAME_CHECK.json.

Exit codes: 0 all checks pass; 1 a check failed; 2 bad input or ffmpeg missing.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROFILES = {
    "whatsapp": [(720, 1280)],
    "master": [(1080, 1920)],
    "auto": [(720, 1280), (1080, 1920)],
}
SAMPLE_FPS = 8
GRID = 32
BLANK_STD = 3.0


class FrameCheckError(RuntimeError):
    pass


# ------------------------------------------------------------- pure analysis

def parse_probe(data: dict) -> dict:
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FrameCheckError("no video stream")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    rotation = 0
    tags = video.get("tags") or {}
    if str(tags.get("rotate", "")).lstrip("-").isdigit():
        rotation = int(tags["rotate"])
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(side["rotation"])
    if abs(rotation) % 180 == 90:
        width, height = height, width
    duration = 0.0
    for src in (data.get("format") or {}, video):
        try:
            duration = float(src.get("duration"))
            break
        except (TypeError, ValueError):
            continue
    fps = 0.0
    rate = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
    if "/" in rate:
        num, den = rate.split("/", 1)
        fps = float(num) / float(den) if float(den or 0) else 0.0
    return {"width": width, "height": height, "duration": round(duration, 3),
            "fps": round(fps, 3), "vcodec": video.get("codec_name"),
            "pix_fmt": video.get("pix_fmt"), "has_audio": audio is not None,
            "acodec": audio.get("codec_name") if audio else None}


def percent_timestamps(duration: float, fps: float) -> list[tuple[str, float]]:
    last = max(0.0, duration - (1.5 / fps if fps > 0 else 0.05))
    return [("000", 0.0), ("025", duration * 0.25), ("050", duration * 0.50),
            ("075", duration * 0.75), ("100", last)]


def mean(frame: bytes) -> float:
    return sum(frame) / len(frame) if frame else 0.0


def std(frame: bytes) -> float:
    if not frame:
        return 0.0
    m = mean(frame)
    return math.sqrt(sum((v - m) ** 2 for v in frame) / len(frame))


def pearson(a: bytes, b: bytes) -> float:
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return 1.0 if da == db else 0.0
    return num / (da * db)


def split_frames(raw: bytes, size: int = GRID * GRID) -> list[bytes]:
    return [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)]


def analyse_closing(series: list[bytes], sample_fps: float, duration: float,
                    hold: float, fade_window: float) -> dict:
    if not series:
        return {"held": False, "faded": False, "gentle": False,
                "reason": "no frames could be sampled"}
    n = len(series)
    end_t = min(duration, (n - 1) / sample_fps) if duration else (n - 1) / sample_fps
    start_t = max(0.0, end_t - fade_window - hold)
    idx = [i for i in range(n) if i / sample_fps >= start_t - 1e-9]
    usable = [i for i in idx if std(series[i]) >= BLANK_STD]
    out = {"window_start_s": round(start_t, 2), "window_end_s": round(end_t, 2),
           "samples": len(idx)}
    if len(usable) < 2:
        out.update(held=False, faded=False, gentle=False, min_correlation=None,
                   reason="closing window is too short or blank to judge")
        return out
    ref = series[usable[0]]
    ref_std = std(ref)
    # Frames deep in the fade are dim and quantised; judge stillness on the rest.
    judged = [i for i in usable[1:] if std(series[i]) >= 0.25 * ref_std]
    if not judged:
        out.update(held=False, faded=False, gentle=False, min_correlation=None,
                   reason="closing window has no frame bright enough to compare")
        return out
    corr = min(pearson(ref, series[i]) for i in judged)
    ref_lum = mean(ref)
    last_lum = mean(series[-1])
    lums = [mean(series[i]) for i in idx]
    drops = [(lums[k - 1] - lums[k]) / ref_lum for k in range(1, len(lums))] if ref_lum else [0]
    out.update(min_correlation=round(corr, 4), held=corr >= 0.97,
               held_luminance=round(ref_lum, 1), final_luminance=round(last_lum, 1),
               faded=last_lum <= 0.6 * ref_lum or last_lum < 12,
               max_step_drop=round(max(drops + [0.0]), 3))
    out["gentle"] = out["max_step_drop"] <= 0.6
    return out


def detect_flicker(series: list[bytes], sample_fps: float, amp: int = 24,
                   swings: int = 4, window_s: float = 3.0) -> dict:
    if len(series) < 3:
        return {"flagged_regions": 0, "worst_swings": 0, "at_s": None}
    size = len(series[0])
    flagged, worst, worst_t = 0, 0, None
    for p in range(size):
        run: list[tuple[float, int]] = []
        best, best_t = 0, None
        prev = series[0][p]
        for k in range(1, len(series)):
            cur = series[k][p]
            d = cur - prev
            prev = cur
            if abs(d) < amp:
                continue
            t, sign = k / sample_fps, 1 if d > 0 else -1
            if run and run[-1][1] != sign:
                run.append((t, sign))
            else:
                run = [(t, sign)]
            while run and t - run[0][0] > window_s:
                run.pop(0)
            if len(run) > best:
                best, best_t = len(run), t
        if best >= swings:
            flagged += 1
        if best > worst:
            worst, worst_t = best, best_t
    return {"flagged_regions": flagged, "worst_swings": worst,
            "at_s": round(worst_t, 2) if worst_t is not None else None}


def parse_volumedetect(text: str) -> dict:
    def grab(key):
        m = re.search(key + r":\s*(-?inf|-?[\d.]+)\s*dB", text)
        if not m:
            return None
        return -math.inf if "inf" in m.group(1) else float(m.group(1))
    return {"mean_db": grab("mean_volume"), "max_db": grab("max_volume")}


def evaluate_audio(body: dict, head: dict, tail: dict, check_fades: bool = True) -> list[str]:
    problems = []
    if body.get("mean_db") is None or body.get("max_db") is None:
        return ["audio level could not be measured"]
    if body["max_db"] >= -0.1:
        problems.append(f"audio clips (peak {body['max_db']} dBFS)")
    if body["mean_db"] < -35:
        problems.append(f"audio nearly inaudible (mean {body['mean_db']} dB)")
    if body["mean_db"] > -9:
        problems.append(f"audio too hot for phone speakers (mean {body['mean_db']} dB)")
    if check_fades:
        h, t = head.get("mean_db"), tail.get("mean_db")
        if h is not None and h > body["mean_db"] - 3:
            problems.append(f"no audio fade-in (first 0.3 s at {h} dB vs mean "
                            f"{body['mean_db']} dB)")
        if t is not None and t > body["mean_db"] - 6:
            problems.append(f"no audio fade-out (last 0.3 s at {t} dB vs mean "
                            f"{body['mean_db']} dB)")
    return problems


def resolution_ok(info: dict, profile: str, expect: tuple | None) -> tuple[bool, str]:
    allowed = [expect] if expect else PROFILES[profile]
    have = (info["width"], info["height"])
    names = " or ".join(f"{w}x{h}" for w, h in allowed)
    return have in allowed, f"{have[0]}x{have[1]} (expected {names})"


# ------------------------------------------------------------- ffmpeg calls

def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["nice", "-n", "19"] + cmd, capture_output=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise FrameCheckError(f"{cmd[0]} timed out after {timeout}s") from exc


def probe(video: Path, timeout: int) -> dict:
    res = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                "-show_streams", str(video)], timeout)
    if res.returncode != 0:
        msg = res.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["unreadable"]
        raise FrameCheckError(f"ffprobe cannot read {video}: {msg[0][:160]}")
    return parse_probe(json.loads(res.stdout.decode(errors="replace") or "{}"))


def extract_png(video: Path, t: float, out: Path, timeout: int) -> bool:
    for ts in (t, max(0.0, t - 0.25)):
        _run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{ts:.3f}", "-i", str(video),
              "-frames:v", "1", "-threads", "1", str(out)], timeout)
        if out.is_file() and out.stat().st_size > 0:
            return True
    return False


def sample_series(video: Path, timeout: int) -> list[bytes]:
    res = _run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-an", "-threads", "1",
                "-vf", f"fps={SAMPLE_FPS},scale={GRID}:{GRID}:flags=area,format=gray",
                "-f", "rawvideo", "-"], timeout)
    if res.returncode != 0:
        raise FrameCheckError("ffmpeg could not sample frames")
    return split_frames(res.stdout)


def volume(video: Path, start: float, length: float | None, timeout: int) -> dict:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-ss", f"{start:.3f}"]
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-i", str(video), "-vn", "-af", "volumedetect", "-f", "null", "-"]
    res = _run(cmd, timeout)
    return parse_volumedetect(res.stderr.decode(errors="replace"))


# ------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="frame_check.py",
        description="Frame, hold, fade, blink and audio QA for invitation videos.")
    ap.add_argument("video")
    ap.add_argument("outdir")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="auto",
                    help="whatsapp=720x1280, master=1080x1920, auto=either (default)")
    ap.add_argument("--expect", default=None, help="explicit WxH, overrides --profile")
    ap.add_argument("--min-duration", type=float, default=5.0)
    ap.add_argument("--max-duration", type=float, default=None)
    ap.add_argument("--hold", type=float, default=2.0,
                    help="seconds the closing frame must be held before the fade (2-3)")
    ap.add_argument("--fade-window", type=float, default=1.0,
                    help="seconds at the very end allowed for the fade-out")
    ap.add_argument("--require-audio", action="store_true")
    ap.add_argument("--allow-no-fade", action="store_true",
                    help="skip the video and audio fade checks (record why)")
    ap.add_argument("--allow-flicker", action="store_true",
                    help="skip the blink check (record why)")
    ap.add_argument("--timeout", type=int, default=180, help="seconds per ffmpeg call")
    args = ap.parse_args(argv)

    video, outdir = Path(args.video), Path(args.outdir)
    if not video.is_file():
        print(f"frame_check: no such video: {video}", file=sys.stderr)
        return 2
    for tool in ("ffprobe", "ffmpeg", "nice"):
        if shutil.which(tool) is None:
            print(f"frame_check: {tool} is not installed", file=sys.stderr)
            return 2
    expect = None
    if args.expect:
        m = re.fullmatch(r"(\d+)x(\d+)", args.expect)
        if not m:
            print("frame_check: --expect must look like 720x1280", file=sys.stderr)
            return 2
        expect = (int(m.group(1)), int(m.group(2)))

    try:
        info = probe(video, args.timeout)
        outdir.mkdir(parents=True, exist_ok=True)
        results: list[tuple[str, bool, str]] = []
        ok, detail = resolution_ok(info, args.profile, expect)
        results.append(("resolution", ok, detail))
        dur_ok = info["duration"] >= args.min_duration and (
            args.max_duration is None or info["duration"] <= args.max_duration)
        results.append(("duration", dur_ok, f"{info['duration']} s (min {args.min_duration}"
                        + (f", max {args.max_duration}" if args.max_duration else "") + ")"))

        frames = {}
        for label, t in percent_timestamps(info["duration"], info["fps"]):
            target = outdir / f"frame_{label}.png"
            frames[label] = {"t": round(t, 2), "path": str(target),
                             "ok": extract_png(video, t, target, args.timeout)}
        closing_t = max(0.0, info["duration"] - args.fade_window - args.hold / 2)
        target = outdir / "frame_closing.png"
        frames["closing"] = {"t": round(closing_t, 2), "path": str(target),
                             "ok": extract_png(video, closing_t, target, args.timeout)}
        missing = [k for k, v in frames.items() if not v["ok"]]
        results.append(("frames", not missing, "6 frames written" if not missing
                        else f"could not extract: {', '.join(missing)}"))

        series = sample_series(video, args.timeout)
        closing = analyse_closing(series, SAMPLE_FPS, info["duration"], args.hold,
                                  args.fade_window)
        results.append(("closing-hold", closing["held"],
                        f"last {args.hold + args.fade_window:g} s still "
                        f"(min correlation {closing.get('min_correlation')})"
                        if closing["held"] else
                        closing.get("reason") or "picture still moving at the end "
                        f"(min correlation {closing.get('min_correlation')}); hold the "
                        "closing frame and finish the zoom earlier"))
        if not args.allow_no_fade:
            results.append(("fade-out", closing["faded"] and closing["gentle"],
                            f"luminance {closing.get('held_luminance')} -> "
                            f"{closing.get('final_luminance')}, largest step "
                            f"{closing.get('max_step_drop')}"))
        flicker = detect_flicker(series, SAMPLE_FPS)
        if not args.allow_flicker:
            results.append(("no-blink", flicker["flagged_regions"] == 0,
                            "no blinking regions" if not flicker["flagged_regions"] else
                            f"{flicker['flagged_regions']} regions blink "
                            f"({flicker['worst_swings']} swings near {flicker['at_s']} s)"))

        audio = None
        if info["has_audio"]:
            body = volume(video, 0.0, None, args.timeout)
            head = volume(video, 0.0, 0.3, args.timeout)
            tail = volume(video, max(0.0, info["duration"] - 0.3), 0.3, args.timeout)
            audio = {"body": body, "head": head, "tail": tail}
            probs = evaluate_audio(body, head, tail, check_fades=not args.allow_no_fade)
            results.append(("audio", not probs, "; ".join(probs) or
                            f"mean {body['mean_db']} dB, peak {body['max_db']} dB, fades ok"))
        elif args.require_audio:
            results.append(("audio", False, "no audio stream"))
        else:
            results.append(("audio", True, "silent video (no audio stream)"))
    except FrameCheckError as exc:
        print(f"frame_check: {exc}", file=sys.stderr)
        return 2

    report = {"video": str(video), "info": info, "frames": frames, "closing": closing,
              "flicker": flicker, "audio": audio,
              "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in results]}
    (outdir / "FRAME_CHECK.json").write_text(json.dumps(report, indent=2))
    print(f"{video}: {info['width']}x{info['height']}, {info['duration']} s, "
          f"{info['fps']} fps, {info['vcodec']}/{info['pix_fmt']}, "
          f"audio {info['acodec'] or 'none'}, {video.stat().st_size} bytes")
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<13} {detail}")
    print(f"frames and report: {outdir}/")
    failed = [(n, d) for n, o, d in results if not o]
    if failed:
        print(f"frame_check: {len(failed)} check(s) failed: "
              + "; ".join(f"{n}: {d}" for n, d in failed)[:400], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
