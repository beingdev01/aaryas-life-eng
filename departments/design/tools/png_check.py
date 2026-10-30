#!/usr/bin/env python3
"""png_check.py - verify a PNG is real, complete, and the size it claims to be.

Pure Python (struct + zlib). It walks every chunk, checks every CRC, requires IHDR
first and IEND last, and reads width and height from IHDR. A truncated render, a
JPEG renamed to .png, or an HTML error page saved as .png all fail.

  png_check.py preview.png
  png_check.py preview.png --width 2339 --height 1654 --tolerance 1
  png_check.py frame.png --preset whatsapp-720
  png_check.py crest.png --require-alpha --same-as /path/to/official-crest.png

--require-alpha decodes the image (8-bit, non-interlaced) and requires all four
corner pixels to be transparent: the brand rule "official transparent crest, no
background box". --same-as requires the file to be byte-identical (SHA-256) to a
reference, which proves an asset was copied, not redrawn or re-encoded.

Exit codes: 0 pass, 1 a check failed, 2 the file is missing or not a valid PNG.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
PRESETS = {
    "a4-landscape-200": (2339, 1654, 1),
    "a4-portrait-200": (1654, 2339, 1),
    "whatsapp-720": (720, 1280, 0),
    "master-1080": (1080, 1920, 0),
    "square-1080": (1080, 1080, 0),
    "portrait-1080x1350": (1080, 1350, 0),
}
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
DECODE_PIXEL_CAP = 30_000_000


class PNGError(ValueError):
    """The file is not a structurally valid PNG."""


def inspect(path: Path) -> dict:
    """Walk the chunk list and return IHDR facts. Raises PNGError on any defect."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise PNGError(f"cannot read {path}: {exc.strerror}") from exc
    if not data.startswith(SIGNATURE):
        kind = "JPEG" if data[:3] == b"\xff\xd8\xff" else (
            "HTML/text" if data[:1] in (b"<", b"{") else "unknown")
        raise PNGError(f"{path} is not a PNG (signature mismatch; looks like {kind})")
    pos, chunks, idat, plte, trns, ihdr = 8, [], [], None, None, None
    while pos < len(data):
        if pos + 8 > len(data):
            raise PNGError(f"{path} is truncated inside a chunk header at byte {pos}")
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        end = pos + 8 + length + 4
        if end > len(data):
            raise PNGError(f"{path} is truncated: chunk {ctype.decode('latin-1')} "
                           f"needs {length} bytes")
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:end])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise PNGError(f"{path}: CRC mismatch in chunk {ctype.decode('latin-1')}")
        name = ctype.decode("latin-1")
        if not chunks and name != "IHDR":
            raise PNGError(f"{path}: first chunk is {name}, expected IHDR")
        chunks.append(name)
        if name == "IHDR":
            if length != 13:
                raise PNGError(f"{path}: IHDR has length {length}, expected 13")
            ihdr = struct.unpack(">IIBBBBB", body)
        elif name == "IDAT":
            idat.append(body)
        elif name == "PLTE":
            plte = body
        elif name == "tRNS":
            trns = body
        pos = end
        if name == "IEND":
            break
    if not chunks or chunks[-1] != "IEND":
        raise PNGError(f"{path} is truncated: no IEND chunk")
    if not idat:
        raise PNGError(f"{path} has no image data (no IDAT chunk)")
    width, height, bit_depth, colour_type, _comp, _filt, interlace = ihdr
    if width == 0 or height == 0:
        raise PNGError(f"{path}: zero width or height in IHDR")
    return {
        "path": str(path), "width": width, "height": height, "bit_depth": bit_depth,
        "colour_type": colour_type, "interlaced": bool(interlace),
        "has_alpha_channel": colour_type in (4, 6) or trns is not None,
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "chunks": len(chunks), "_idat": b"".join(idat), "_plte": plte, "_trns": trns,
    }


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_rows(info: dict) -> list[bytes]:
    """Return unfiltered scanlines for 8-bit, non-interlaced images."""
    if info["bit_depth"] != 8 or info["interlaced"]:
        raise PNGError("decoding needs an 8-bit, non-interlaced PNG; re-export it that way")
    if info["width"] * info["height"] > DECODE_PIXEL_CAP:
        raise PNGError("image too large to decode for the alpha check")
    bpp = CHANNELS[info["colour_type"]]
    stride = info["width"] * bpp
    raw = zlib.decompress(info["_idat"])
    if len(raw) < (stride + 1) * info["height"]:
        raise PNGError("image data is shorter than IHDR promises")
    rows, prev = [], bytearray(stride)
    for y in range(info["height"]):
        off = y * (stride + 1)
        ftype = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            line = bytearray((x + p) & 0xFF for x, p in zip(line, prev))
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up_left = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 0xFF
        elif ftype != 0:
            raise PNGError(f"unknown filter type {ftype} on row {y}")
        rows.append(bytes(line))
        prev = line
    return rows


def corner_alphas(info: dict) -> list[int]:
    """Alpha (0-255) of the four corner pixels."""
    ct = info["colour_type"]
    rows = decode_rows(info)
    bpp, w = CHANNELS[ct], info["width"]
    out = []
    for row in (rows[0], rows[-1]):
        for x in (0, w - 1):
            px = row[x * bpp:(x + 1) * bpp]
            if ct in (4, 6):
                out.append(px[-1])
            elif ct == 3:
                trns = info["_trns"] or b""
                out.append(trns[px[0]] if px[0] < len(trns) else 255)
            elif info["_trns"] is not None:
                key = info["_trns"]
                sample = bytes(v for i, v in enumerate(key) if i % 2 == 1)
                out.append(0 if bytes(px) == sample else 255)
            else:
                out.append(255)
    return out


def check(path: Path, width=None, height=None, tolerance=0, min_bytes=1024,
          max_bytes=None, require_alpha=False, same_as=None) -> tuple[dict, list[str]]:
    info = inspect(path)
    problems = []
    if width is not None and abs(info["width"] - width) > tolerance:
        problems.append(f"width {info['width']} px, expected {width}"
                        + (f" +/-{tolerance}" if tolerance else ""))
    if height is not None and abs(info["height"] - height) > tolerance:
        problems.append(f"height {info['height']} px, expected {height}"
                        + (f" +/-{tolerance}" if tolerance else ""))
    if info["bytes"] < min_bytes:
        problems.append(f"only {info['bytes']} bytes (minimum {min_bytes}); "
                        "likely a blank or failed render")
    if max_bytes is not None and info["bytes"] > max_bytes:
        problems.append(f"{info['bytes']} bytes exceeds the {max_bytes}-byte limit")
    if require_alpha:
        if not info["has_alpha_channel"]:
            problems.append("no alpha channel: an asset that must be transparent has a "
                            "solid background")
        else:
            try:
                alphas = corner_alphas(info)
                info["corner_alpha"] = alphas
                if max(alphas) > 16:
                    problems.append(f"corner pixels are not transparent (alpha {alphas}); "
                                    "the asset carries a background box")
            except PNGError as exc:
                problems.append(f"alpha check impossible: {exc}")
    if same_as is not None:
        try:
            ref = hashlib.sha256(Path(same_as).read_bytes()).hexdigest()
        except OSError as exc:
            problems.append(f"cannot read reference {same_as}: {exc.strerror}")
        else:
            info["reference_sha256"] = ref
            if ref != info["sha256"]:
                problems.append(f"not byte-identical to {same_as}: the asset was altered, "
                                "re-encoded or redrawn")
    return info, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="png_check.py",
        description="Verify a PNG is structurally valid and has the expected size.",
        epilog="Presets: " + ", ".join(f"{k}={w}x{h}" for k, (w, h, _t) in PRESETS.items()))
    ap.add_argument("file")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--tolerance", type=int, default=None,
                    help="allowed +/- pixels on width/height (default 0; presets set it)")
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--min-bytes", type=int, default=1024,
                    help="smallest believable file size (default 1024)")
    ap.add_argument("--max-bytes", type=int, default=None)
    ap.add_argument("--require-alpha", action="store_true",
                    help="require transparency and transparent corner pixels")
    ap.add_argument("--same-as", default=None,
                    help="require byte-identity with this reference file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    width, height, tol = args.width, args.height, 0
    if args.preset:
        pw, ph, tol = PRESETS[args.preset]
        width = width if width is not None else pw
        height = height if height is not None else ph
    if args.tolerance is not None:
        tol = args.tolerance

    try:
        info, problems = check(Path(args.file), width, height, tol, args.min_bytes,
                               args.max_bytes, args.require_alpha, args.same_as)
    except PNGError as exc:
        print(f"png_check: {exc}", file=sys.stderr)
        return 2
    public = {k: v for k, v in info.items() if not k.startswith("_")}
    public["problems"] = problems
    if args.json:
        print(json.dumps(public, indent=2))
    else:
        print(f"{info['path']}: PNG {info['width']}x{info['height']}, "
              f"{info['bytes']} bytes, bit depth {info['bit_depth']}, colour type "
              f"{info['colour_type']}, alpha {'yes' if info['has_alpha_channel'] else 'no'}, "
              f"sha256 {info['sha256'][:16]}")
        for p in problems:
            print(f"FAIL  {p}")
        if not problems:
            print("PASS")
    if problems:
        print(f"png_check: {args.file}: {problems[0]}"
              + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
