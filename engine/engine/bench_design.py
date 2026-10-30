#!/usr/bin/env python3
"""Design department benchmark suite: real, rendered, gate-checked artefacts.

This mirrors the `quality` suite in bench.py, but answers the design question: can the
engine drive a free model to produce not text but *rendered* artefacts — an HTML/CSS
source, a preview PNG the CEO can actually look at, and for an invitation an mp4 whose
frames can be inspected?

Grading is fully deterministic. No model judges visuals. The gates are:

  source-file          the source exists and exceeds a byte floor
  required-copy        every mandated copy string appears verbatim in the source
  preview-png          preview.png is a real PNG with at least the required dimensions
  preview-nonblank     the decoded preview pixels have variance (a white/black card fails)
  video-exists         the mp4 exists and exceeds a byte floor (a zero-byte file fails)
  video-duration       ffprobe-measured duration is within [min, max]
  video-resolution     the frame size equals the target size
  frame-NNN-nonblank   frames extracted at 0/25/50/75/100 % each have pixel variance
                       (a rendered black frame fails even when duration and resolution
                       pass — this is what separates 'a file exists' from 'a design was
                       drawn')

run_negative_proofs() is what makes the gates worth anything: it assembles deliberately
bad artefacts (missing preview, zero-byte mp4, black video, source with wrong copy) and
asserts the correct gate fails on each, while a positive control passes everything.
The live baseline-vs-engine run refuses to start if that self-check fails.

Stdlib only, no engine internals, so a task spec can embed this as an engine-run gate:
    python3 engine/bench_design.py grade <workdir> <DESIGN_GATES.json>
"""

from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FRAME_PERCENTS = (0, 25, 50, 75, 100)
PIPELINE_DIR = Path(__file__).resolve().parent.parent


class GateError(RuntimeError):
    pass


# ---------------------------------------------------------------------- the tasks
# Fictional brands only. The poster is the static task, the invitation is the
# animated one; the invitation mirrors Lane B + Lane D of the four-lane chain
# (source + preview + mp4 + frame checks).

DESIGN_TASKS = [
    {
        "id": "poster-lumen-founders",
        "title": "Founders Night poster: a static announcement graphic from a brief",
        "kind": "poster",
        "copy": ["Founders Night", "Lumen Labs", "Saturday 14 November",
                 "Atria Hall, Riverside Campus", "RSVP by 7 November"],
        "source": {"path": "index.html", "min_bytes": 1500},
        "preview": {"path": "preview.png", "min_width": 1000, "min_height": 1200,
                    "min_std": 2.0},
        "video": None,
        "brief": """Build ONE self-contained announcement poster as a single HTML file
(index.html) for a fictional company, then render a preview PNG of it.

Poster copy — each line below must appear verbatim, inside one text element each,
never split across tags:
- Title: Founders Night
- Host: Lumen Labs
- Date line: Saturday 14 November
- Venue line: Atria Hall, Riverside Campus
- Deadline line: RSVP by 7 November
Plus one supporting sentence of your own about the evening.

Design requirements: a palette of two or three colours plus neutrals (exact hex in
the CSS), a clear type hierarchy (large title, readable body), generous spacing,
nothing smaller than 20 px at 1080 width, no blinking, no decorative accents outside
the stated palette.

Technical requirements: CSS only, no JavaScript, no external assets, no network
fetches, no remote fonts (system font stacks only: DejaVu Sans, Liberation Sans or
generic sans-serif/serif). The poster is 1080x1350 portrait: size the body to exactly
that and set the viewport meta so a headless render at 1080x1350 fills the frame.

Deliverables, in the working directory you are given:
- index.html  — the complete source
- preview.png — the poster rendered from index.html at 1080x1350 (minimum accepted
  1000x1200). It must show the actual design: an all-white or all-black preview fails.
Do not publish, send or upload anything. Do not install software.""",
    },
    {
        "id": "invite-northwind-demo",
        "title": "Northwind Demo Night animated invitation: source, preview PNG, mp4",
        "kind": "invitation",
        "copy": ["Northwind Robotics", "Demo Night", "Friday 6 November",
                 "6:30 PM", "Innovation Park", "Free entry"],
        "source": {"path": "index.html", "min_bytes": 2000},
        "preview": {"path": "preview.png", "min_width": 720, "min_height": 1280,
                    "min_std": 2.0},
        "video": {"path": "invite.mp4", "min_bytes": 4096, "min_duration": 5.0,
                  "max_duration": 60.0, "width": 720, "height": 1280, "min_std": 3.0},
        "brief": """Build ONE self-contained ANIMATED invitation card as a single HTML
file (index.html), render a preview PNG of it, and produce an mp4 of the animation.
This mirrors the real Design Team chain: source and first preview (Lane B), then
motion render with frame checks (Lane D).

Invitation copy — each line below must appear verbatim, inside one text element each,
never split across tags, and all of it must be visible in the final frame of the video:
- Club: Northwind Robotics
- Title: Demo Night
- Date line: Friday 6 November
- Time line: 6:30 PM
- Venue line: Innovation Park
- Footer line: Free entry
Plus one supporting sentence of your own about what will be shown.

Motion requirements: a slow fade in, text entering in reading order (club, title,
date and time, venue, footer), then the complete card held still for the last ~2
seconds. CSS keyframes only. No blinking, no flashing, no bounces, no particle
effects, no external assets, no network, system font stacks only.

Deliverables, in the working directory you are given:
- index.html  — the animated source, sized 720x1280 portrait exactly
- preview.png — the complete card rendered from index.html (minimum accepted
  720x1280). The render must settle the animation to its final visible state.
- invite.mp4  — the invitation animated video, EXACTLY 720x1280, between 5 and
  60 seconds, silent is fine. Machine checks extract frames at 0/25/50/75/100 % and
  measure pixel variance per frame: a black or blank frame fails, so the design must
  actually be visible in every sampled frame, including the first.
Do not publish, send or upload anything. Do not install software.""",
    },
]


def by_id(task_id: str) -> dict:
    for task in DESIGN_TASKS:
        if task["id"] == task_id:
            return task
    raise KeyError(f"unknown design task: {task_id}")


def manifest_for(task: dict) -> dict:
    """The machine-readable gate definition for one task (stored as DESIGN_GATES.json)."""
    return {
        "task": task["id"],
        "source": dict(task["source"]),
        "copy": list(task["copy"]),
        "preview": dict(task["preview"]) if task.get("preview") else None,
        "video": dict(task["video"]) if task.get("video") else None,
    }


def expected_gates(manifest: dict) -> list[str]:
    gates = ["source-file", "required-copy"]
    if manifest.get("preview"):
        gates += ["preview-png", "preview-nonblank"]
    if manifest.get("video"):
        gates += ["video-exists", "video-duration", "video-resolution"]
        gates += [f"frame-{p:03d}-nonblank" for p in FRAME_PERCENTS]
    return gates


# ---------------------------------------------------------------------- PNG tools

def png_write_gray(path: Path, width: int, height: int, rows) -> None:
    """Write an 8-bit grayscale PNG. rows is an iterable of width-byte rows."""
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_MAGIC + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _png_chunks(data: bytes):
    pos = 8
    while pos + 12 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        yield kind, body
        if kind == b"IEND":
            return


def png_header(data: bytes) -> dict:
    for kind, body in _png_chunks(data):
        if kind == b"IHDR":
            w, h, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", body[:13])
            return {"width": w, "height": h, "bit_depth": depth, "colour_type": ctype,
                    "interlace": interlace}
    raise GateError("PNG has no IHDR chunk")


CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def png_decode_luma(data: bytes) -> tuple[int, int, bytes]:
    """Decode a non-interlaced PNG to 8-bit luma bytes. Pure stdlib.

    Handles colour types 0/2/3/4/6 at 8-bit depth (16-bit depth is truncated to the
    high byte). Chrome and ffmpeg screenshots are all inside this set."""
    if not data.startswith(PNG_MAGIC):
        raise GateError("not a PNG (bad magic)")
    header = png_header(data)
    if header["interlace"]:
        raise GateError("interlaced PNG not supported")
    if header["bit_depth"] not in (8, 16):
        raise GateError(f"unsupported bit depth {header['bit_depth']}")
    ctype = header["colour_type"]
    if ctype not in CHANNELS:
        raise GateError(f"unsupported colour type {ctype}")
    width, height, depth = header["width"], header["height"], header["bit_depth"]
    channels = CHANNELS[ctype]
    plte = b""
    idat = bytearray()
    for kind, body in _png_chunks(data):
        if kind == b"PLTE":
            plte = body
        elif kind == b"IDAT":
            idat += body
    if ctype == 3 and not plte:
        raise GateError("palette PNG without PLTE")
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise GateError(f"IDAT inflate failed: {exc}") from exc

    stride = (width * channels * depth + 7) // 8
    expected = stride * height + height  # one filter byte per row
    if len(raw) < expected:
        raise GateError("PNG data truncated")
    bpp = max(1, channels * depth // 8)
    out = bytearray(stride * height)
    for y in range(height):
        base = y * (stride + 1)
        ftype = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        prev_base = (y - 1) * stride
        if ftype == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ftype == 2:
            if y:
                for x in range(stride):
                    line[x] = (line[x] + out[prev_base + x]) & 0xFF
        elif ftype == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                up = out[prev_base + x] if y else 0
                line[x] = (line[x] + ((left + up) >> 1)) & 0xFF
        elif ftype == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = out[prev_base + x] if y else 0
                c = out[prev_base + x - bpp] if (y and x >= bpp) else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        elif ftype != 0:
            raise GateError(f"unknown filter type {ftype}")
        out[y * stride:(y + 1) * stride] = line

    step = 2 if depth == 16 else 1
    luma = bytearray(width * height)
    if ctype == 0:
        for i in range(width * height):
            luma[i] = out[i * step]
    elif ctype == 4:
        for i in range(width * height):
            luma[i] = out[i * 2 * step]
    elif ctype == 2:
        for i in range(width * height):
            o = i * 3 * step
            luma[i] = (out[o] * 77 + out[o + step] * 151 + out[o + 2 * step] * 28) >> 8
    elif ctype == 6:
        # composite over white so an invisible transparent frame scores as blank,
        # the way it would look on the CEO's screen
        for i in range(width * height):
            o = i * 4 * step
            r, g, b, a = out[o], out[o + step], out[o + 2 * step], out[o + 3 * step]
            r = (r * a + 255 * (255 - a)) // 255
            g = (g * a + 255 * (255 - a)) // 255
            b = (b * a + 255 * (255 - a)) // 255
            luma[i] = (r * 77 + g * 151 + b * 28) >> 8
    elif ctype == 3:
        for i in range(width * height):
            idx = out[i] * 3
            if idx + 2 >= len(plte):
                raise GateError("palette index out of range")
            luma[i] = (plte[idx] * 77 + plte[idx + 1] * 151 + plte[idx + 2] * 28) >> 8
    return width, height, bytes(luma)


def png_stats(path: Path, sample_cols: int = 128, sample_rows: int = 64) -> dict:
    """Dimensions, byte size and luma mean/std of a PNG. std is the blank detector.

    Stats are measured on a regular subsample (about 128x64 luma values) so a huge
    screenshot does not stall the gate; blank is blank at any sampling."""
    data = Path(path).read_bytes()
    width, height, luma = png_decode_luma(data)
    cs = max(1, width // sample_cols)
    rs = max(1, height // sample_rows)
    values = b"".join(luma[y * width:(y + 1) * width:cs] for y in range(0, height, rs))
    n = len(values) or 1
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return {"width": width, "height": height, "bytes": len(data),
            "mean": round(mean, 1), "std": round(math.sqrt(var), 2)}


# ---------------------------------------------------------------------- video tools

def video_info(path: Path, timeout: int = 60) -> dict:
    if shutil.which("ffprobe") is None:
        raise GateError("ffprobe is not installed on this host")
    res = subprocess.run(
        ["nice", "-n", "19", "ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,duration",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=timeout, errors="replace")
    if res.returncode != 0:
        tail = (res.stderr or "").strip().splitlines()[-1:] or ["unreadable file"]
        raise GateError(f"ffprobe cannot read {Path(path).name}: {tail[0][:140]}")
    data = json.loads(res.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise GateError(f"{Path(path).name} has no video stream")
    st = streams[0]
    duration = None
    for src in (st, data.get("format") or {}):
        try:
            duration = float(src.get("duration"))
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue
    fps = 0.0
    rate = str(st.get("r_frame_rate") or "0/1")
    if "/" in rate:
        num, den = rate.split("/", 1)
        fps = float(num) / float(den) if float(den or 0) else 0.0
    if duration is None:
        raise GateError(f"ffprobe reported no duration for {Path(path).name}")
    return {"width": int(st.get("width") or 0), "height": int(st.get("height") or 0),
            "duration": round(duration, 3), "fps": round(fps, 3)}


def frame_times(duration: float, fps: float) -> list[tuple[str, float]]:
    """0/25/50/75 % and just-before-the-end, like Lane D's frame checks."""
    last = max(0.0, duration - (1.5 / fps if fps > 0 else 0.05))
    return [(f"{p:03d}", 0.0 if p == 0 else duration * p / 100.0)
            for p in FRAME_PERCENTS[:-1]] + [("100", last)]


def extract_frame(video: Path, t: float, out: Path, timeout: int = 60) -> str:
    """Write one frame; returns ok or the ffmpeg failure reason."""
    if shutil.which("ffmpeg") is None:
        return "ffmpeg is not installed on this host"
    for ts in (t, max(0.0, t - 0.25)):
        res = subprocess.run(
            ["nice", "-n", "19", "ffmpeg", "-v", "error", "-nostdin", "-y",
             "-ss", f"{ts:.3f}", "-i", str(video), "-frames:v", "1", "-threads", "1",
             str(out)],
            capture_output=True, text=True, timeout=timeout, errors="replace")
        if res.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            return ""
    return ((res.stderr or "").strip().splitlines()[-1:] or ["frame not written"])[0][:140]


# ------------------------------------------------------------------------- grading

def grade(workdir: Path, manifest: dict) -> list[dict]:
    """Every gate for one task, in a stable order. Returns rows of name/passed/detail."""
    workdir = Path(workdir)
    rows: list[dict] = []

    def row(name: str, passed, detail: str):
        rows.append({"name": name, "passed": bool(passed), "detail": str(detail)[:400]})

    src_rel = manifest["source"]["path"]
    src = workdir / src_rel
    min_bytes = int(manifest["source"].get("min_bytes", 500))
    exists = src.is_file()
    size = src.stat().st_size if exists else 0
    row("source-file", exists and size >= min_bytes,
        f"{src_rel}: {size} bytes (min {min_bytes})" if exists else f"{src_rel} missing")

    html = ""
    if exists:
        try:
            html = src.read_text(errors="replace")
        except OSError as exc:
            row("required-copy", False, f"{src_rel} unreadable: {exc}")
            return rows
    missing = [c for c in (manifest.get("copy") or []) if c not in html]
    if not exists:
        missing = manifest.get("copy") or missing
    row("required-copy", exists and not missing,
        f"all {len(manifest.get('copy') or [])} copy strings present verbatim"
        if not missing else f"missing copy: {json.dumps(missing)}")

    prev = manifest.get("preview")
    if prev:
        p = workdir / prev["path"]
        stats, why = None, ""
        if not p.is_file():
            why = f"{prev['path']} missing"
        elif p.stat().st_size < 100:
            why = f"{prev['path']} is only {p.stat().st_size} bytes"
        else:
            try:
                stats = png_stats(p)
            except GateError as exc:
                why = f"{prev['path']}: {exc}"
            except (OSError, IndexError, ValueError) as exc:
                why = f"{prev['path']}: unreadable PNG ({exc})"
        dims_ok = bool(stats) and (stats["width"] >= int(prev.get("min_width", 1))
                                   and stats["height"] >= int(prev.get("min_height", 1)))
        row("preview-png", dims_ok, why or
            (f"{stats['width']}x{stats['height']}, {stats['bytes']} bytes "
             f"(min {prev.get('min_width', 0)}x{prev.get('min_height', 0)})"))
        if stats is None:
            row("preview-nonblank", False, f"not judged: {why or 'no decodable preview'}")
        else:
            std = stats["std"]
            row("preview-nonblank", std >= float(prev.get("min_std", 2.0)),
                f"luma mean {stats['mean']}, std {std} "
                f"(min {prev.get('min_std', 2.0)}); blank frames have std ~0")

    vid = manifest.get("video")
    if vid:
        v = workdir / vid["path"]
        present = v.is_file() and v.stat().st_size >= int(vid.get("min_bytes", 1))
        row("video-exists", present,
            f"{vid['path']}: {v.stat().st_size if v.is_file() else 0} bytes "
            f"(min {vid.get('min_bytes', 1)})")
        info, err = None, ""
        if not v.is_file():
            err = f"{vid['path']} missing"
        elif not present:
            err = f"{vid['path']} too small to be a real render"
        else:
            try:
                info = video_info(v)
            except (GateError, OSError, ValueError, subprocess.SubprocessError) as exc:
                err = str(exc)
        dur = (info or {}).get("duration")
        lo, hi = float(vid.get("min_duration", 1)), float(vid.get("max_duration") or 1e9)
        row("video-duration", bool(info) and lo <= dur <= hi,
            err or f"duration {dur}s (floor {lo}s, max {hi}s)")
        want = (int(vid.get("width", 0)), int(vid.get("height", 0)))
        got = ((info or {}).get("width"), (info or {}).get("height"))
        row("video-resolution", bool(info) and (want == (0, 0)) or got == want,
            err or f"{got[0]}x{got[1]} (want {want[0]}x{want[1]})")
        frames_dir = workdir / "_gate_frames"
        min_std = float(vid.get("min_std", 3.0))
        for label, t in (frame_times(info["duration"], info["fps"]) if info else []):
            name = f"frame-{label}-nonblank"
            if info is None:
                rows_ok = False
                detail = f"not judged: no probeable video ({err})"
                row(name, rows_ok, detail)
                continue
            frames_dir.mkdir(parents=True, exist_ok=True)
            out = frames_dir / f"frame_{label}.png"
            reason = extract_frame(v, t, out)
            if reason:
                row(name, False, f"t={t:.2f}s: {reason}")
                continue
            try:
                fs = png_stats(out)
                row(name, fs["std"] >= min_std,
                    f"t={t:.2f}s {fs['width']}x{fs['height']}: luma mean {fs['mean']}, "
                    f"std {fs['std']} (min {min_std}); a black frame has std ~0")
            except GateError as exc:
                row(name, False, f"t={t:.2f}s: {exc}")

    # keep the row order stable and complete whatever happened
    present_names = {r["name"] for r in rows}
    for name in expected_gates(manifest):
        if name not in present_names:
            row(name, False, "not evaluated (an earlier gate on the same artefact failed)")
    return rows


def grade_file(workdir: Path, gates_path: Path) -> tuple[bool, list[dict]]:
    manifest = json.loads(Path(gates_path).read_text())
    rows = grade(Path(workdir), manifest)
    return all(r["passed"] for r in rows), rows


# --------------------------------------------------------------- spec construction

def build_spec(task: dict, workdir: Path, depth: int) -> dict:
    """The design-engine task spec: department kit plus deterministic design gates.

    The parts are frozen so the bench measures the pipeline around one well-defined
    build contract, exactly as the real chain dispatches Lane B with a written spec."""
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    manifest = manifest_for(task)
    (workdir / "DESIGN_GATES.json").write_text(json.dumps(manifest, indent=2))
    cmd = grade_cmd(workdir)

    deliverables = [{"path": str(workdir / task["source"]["path"]),
                     "min_bytes": task["source"].get("min_bytes", 500),
                     "description": "the complete HTML/CSS source"}]
    if task.get("preview"):
        deliverables.append({"path": str(workdir / task["preview"]["path"]),
                             "min_bytes": 20000,
                             "description": "the rendered preview PNG the CEO reviews"})
    if task.get("video"):
        deliverables.append({"path": str(workdir / task["video"]["path"]),
                             "min_bytes": task["video"].get("min_bytes", 4096),
                             "description": "the rendered invitation mp4"})

    copy_lines = "\n".join(f"- {c}" for c in task["copy"])
    contract = (
        f"Produce, at exactly {workdir}: "
        f"{task['source']['path']} (source, min {task['source'].get('min_bytes', 500)} bytes), "
        + (f"{task['preview']['path']} (preview PNG >= "
           f"{task['preview'].get('min_width')}x{task['preview'].get('min_height')}, "
           f"non-blank), " if task.get("preview") else "")
        + (f"{task['video']['path']} (mp4 exactly "
           f"{task['video'].get('width')}x{task['video'].get('height')}, "
           f"{task['video'].get('min_duration')}-{task['video'].get('max_duration')}s, "
           f"every frame non-black), " if task.get("video") else "")
        + f"with these copy strings verbatim:\n{copy_lines}\n"
        "Verify your own work by running the design gate command below and iterating "
        "until it prints DESIGN_GATE_OK.")

    context_sources = []
    dept_root = Path(os.environ.get("ENG_DEPARTMENTS", "")) if \
        os.environ.get("ENG_DEPARTMENTS") else None
    if dept_root and (dept_root / "design").is_dir():
        for rel in ("runbooks/design.md", "skills/preview-render-pipeline.md",
                    "skills/motion-video-qa.md", "tools", "templates"):
            p = dept_root / "design" / rel
            if p.exists():
                context_sources.append(str(p))

    return {
        "id": f"design-{task['id']}",
        "title": task["title"],
        "department": "design",
        "depth": depth,
        "goal": (task["brief"]
                 + "\n\nCompletion is decided by deterministic machine gates (source size,"
                 " copy strings, PNG dimensions and pixel variance, video duration and"
                 " per-frame variance) — not by anyone's opinion. Frames at 0/25/50/75/100%"
                 " of the video are extracted and measured; a black frame fails."),
        "deliverables": deliverables,
        "acceptance": [{"name": "design-gates", "cmd": cmd,
                        "expect_exit": 0, "expect_stdout": "DESIGN_GATE_OK",
                        "timeout_sec": 300}],
        "authorized_paths": [str(workdir)],
        "banned_paths": [str(PIPELINE_DIR / "engine"), "/home/ubuntu/.config",
                         "/home/ubuntu/.ssh"],
        "context_sources": context_sources,
        "constraints": [
            "Run Chrome and ffmpeg under nice -n 19, one render at a time; the VM has "
            "2 vCPUs and live services.",
            "Never fetch anything from the network and never install software.",
        ],
        "parts": [{
            "id": "build",
            "title": task["title"],
            "owns_files": [d["path"] for d in deliverables],
            "depends_on": [],
            "contract": contract,
            "deliverables": deliverables,
            "verify_cmd": cmd,
            "difficulty": "high",
            "notes": ("Preview and video must be rendered FROM the HTML/CSS source, not "
                      "drawn by a separate path: the copy strings are read out of the "
                      "source file and the pixels are measured from the render. "
                      "Use the department tools (render_preview.py, png_check.py, "
                      "frame_check.py) when they are available."),
        }],
    }


def grade_cmd(workdir: Path) -> str:
    return (f"python3 {Path(__file__).resolve()} grade {Path(workdir).resolve()} "
            f"{Path(workdir).resolve() / 'DESIGN_GATES.json'}")


BASELINE_PROMPT = """You are the sole designer for this job. Work in the current
directory and finish with the files on disk; nothing you describe counts, only files.

{brief}

Every copy string listed in the brief must appear verbatim in the source.
The files are graded by deterministic machine checks (byte floors, copy strings, PNG
dimensions, decoded pixel variance, video duration and per-frame variance at
0/25/50/75/100 %). Run your own checks before finishing: a headless Chrome binary
exists under ~/.cache/puppeteer for previews, and ffmpeg/ffprobe are installed for
video work.

Do not fetch anything from the network. Do not install software. Do not publish or
send anything."""


# ------------------------------------------------------------------ negative proofs
# The gates are only worth something if they reject bad output. These fixtures are
# machine-made (no model), and each deliberately breaks exactly one gate.

def _fixture_manifest() -> dict:
    return {
        "task": "negatives",
        "source": {"path": "index.html", "min_bytes": 300},
        "copy": ["Northwind Robotics", "Demo Night", "Friday 6 November",
                 "6:30 PM", "Innovation Park", "Free entry"],
        "preview": {"path": "preview.png", "min_width": 720, "min_height": 1280,
                    "min_std": 2.0},
        "video": {"path": "invite.mp4", "min_bytes": 4096, "min_duration": 5.0,
                  "max_duration": 60.0, "width": 720, "height": 1280, "min_std": 3.0},
    }


def _fixture_html(copy: list[str]) -> str:
    body = "\n".join(f"<p>{c}</p>" for c in copy)
    return ("<html><head><style>body{{width:720px;height:1280px;background:#101820;"
            "color:#f2f2f2;font-family:sans-serif}}</style></head><body>"
            + body + "</body></html>\n") * 3


def _run_ffmpeg(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["nice", "-n", "19", "ffmpeg", "-v", "error", "-nostdin",
                           "-y"] + args, capture_output=True, text=True,
                          timeout=timeout, errors="replace")


def run_negative_proofs(out_dir: Path) -> dict:
    """Every bad artefact must fail its gate, and the positive control must pass all.

    Returns {"passed": bool, "cases": [rows...]} — the receipt table.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = _fixture_manifest()
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return {"suite": "design-negatives", "passed": False,
                "error": "ffmpeg/ffprobe not installed: the video gates cannot be "
                         "self-checked on this host", "cases": []}

    fixtures = out_dir / "_fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    good_html = _fixture_html(manifest["copy"])
    (fixtures / "index.html").write_text(good_html)
    png_write_gray(fixtures / "preview.png", 720, 1280,
                   (bytes([(x + y) % 256 for x in range(720)]) for y in range(1280)))
    content = fixtures / "content.mp4"
    black = fixtures / "black.mp4"
    if not content.is_file():
        res = _run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=24:duration=6",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                           str(content)])
        if res.returncode != 0:
            return {"suite": "design-negatives", "passed": False,
                    "error": f"ffmpeg could not build the content fixture: "
                             f"{(res.stderr or '')[-200:]}", "cases": []}
    if not black.is_file():
        _run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=720x1280:r=24:d=6",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                     str(black)])

    import shutil as _sh
    import os

    def case(name: str, *, html=None, preview="copy", video="content"):
        cdir = out_dir / name
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "index.html").write_text(html if html is not None else good_html)
        if preview == "copy":
            _sh.copy(fixtures / "preview.png", cdir / "preview.png")
        elif preview == "blank":
            png_write_gray(cdir / "preview.png", 720, 1280,
                           (bytes([255] * 720) for _ in range(1280)))
        if video == "content":
            _sh.copy(content, cdir / "invite.mp4")
        elif video == "black":
            _sh.copy(black, cdir / "invite.mp4")
        elif video == "zero":
            (cdir / "invite.mp4").write_bytes(b"")
        # video == "none" leaves it missing
        return cdir

    wrong_copy = good_html.replace("6:30 PM", "7:00 PM").replace("<p>Free entry</p>", "")

    # expectations: gate name -> True if that gate is expected to PASS
    positive = {g: True for g in expected_gates(manifest)}
    plan = [
        ("positive-control", dict(positive)),
        ("missing-preview", dict(positive, **{"preview-png": False,
                                              "preview-nonblank": False})),
        ("blank-preview", dict(positive, **{"preview-nonblank": False})),
        ("zero-byte-mp4", dict(positive, **{"video-exists": False, "video-duration": False,
                                            "video-resolution": False,
                                            **{f"frame-{p:03d}-nonblank": False
                                               for p in FRAME_PERCENTS}})),
        ("black-video", dict(positive, **{f"frame-{p:03d}-nonblank": False
                                          for p in FRAME_PERCENTS})),
        ("wrong-copy", dict(positive, **{"required-copy": False})),
    ]
    builders = {
        "positive-control": lambda: case("positive-control"),
        "missing-preview": lambda: case("missing-preview", preview="none"),
        "blank-preview": lambda: case("blank-preview", preview="blank"),
        "zero-byte-mp4": lambda: case("zero-byte-mp4", video="zero"),
        "black-video": lambda: case("black-video", video="black"),
        "wrong-copy": lambda: case("wrong-copy", html=wrong_copy),
    }

    cases, all_ok = [], True
    for name, expect in plan:
        cdir = builders[name]()
        rows = grade(cdir, manifest)
        by = {r["name"]: r for r in rows}
        for gate, want_pass in expect.items():
            got = by.get(gate)
            ok = got is not None and got["passed"] == want_pass
            all_ok = all_ok and ok
            cases.append({"case": name, "gate": gate,
                          "expected": "PASS" if want_pass else "FAIL",
                          "actual": ("PASS" if got["passed"] else "FAIL") if got else "MISSING",
                          "detail": (got or {}).get("detail", ""),
                          "as_expected": ok})
    report = {"suite": "design-negatives", "passed": all_ok,
              "rows_total": len(expected_gates(manifest)), "cases": cases}
    (out_dir / "NEGATIVES.json").write_text(json.dumps(report, indent=2))
    lines = ["# Design gate negative proofs", "",
             "Every row is one gate on one deliberately bad artefact.", "",
             "| artefact | gate | expected | actual | detail |", "|---|---|---|---|---|"]
    for c in cases:
        lines.append(f"| {c['case']} | {c['gate']} | {c['expected']} | {c['actual']} "
                     f"| {c['detail'][:90]} |")
    lines.append("")
    lines.append(f"RESULT: {'DONE' if all_ok else 'FAILED'} — "
                 f"{sum(1 for c in cases if c['as_expected'])}/{len(cases)} gate "
                 "verdicts as expected.")
    (out_dir / "NEGATIVES.md").write_text("\n".join(lines))
    return report


# ------------------------------------------------------------------------ CLI entry

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "grade":
        if len(argv) != 3:
            print("usage: bench_design.py grade <workdir> <DESIGN_GATES.json>",
                  file=sys.stderr)
            return 2
        try:
            ok, rows = grade_file(Path(argv[1]), Path(argv[2]))
        except (OSError, ValueError, GateError) as exc:
            print(f"design-gate: cannot grade: {exc}", file=sys.stderr)
            return 1
        for r in rows:
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']:<24} {r['detail']}")
        if ok:
            print("DESIGN_GATE_OK")
            return 0
        failed = ", ".join(r["name"] for r in rows if not r["passed"])
        print(f"DESIGN_GATE_FAIL: {failed}")
        return 1
    if argv[0] == "negatives":
        out_dir = Path(argv[1]) if len(argv) > 1 else Path("bench/design-negatives")
        report = run_negative_proofs(out_dir)
        for c in report.get("cases", []):
            mark = "ok  " if c["as_expected"] else "BAD "
            print(f"{mark}{c['case']:<20} {c['gate']:<24} expected {c['expected']:<4} "
                  f"got {c['actual']}")
        print(f"negatives: {'PASS' if report['passed'] else 'FAIL'} "
              f"({out_dir / 'NEGATIVES.md'})")
        if report.get("error"):
            print(f"error: {report['error']}", file=sys.stderr)
        return 0 if report["passed"] else 1
    print(f"unknown command: {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
