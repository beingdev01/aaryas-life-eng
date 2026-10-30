"""Tests for png_check.py. PNGs are built in memory and written to temp dirs."""

import hashlib
import io
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import png_check as pc  # noqa: E402


def chunk(ctype: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + ctype + body +
            struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF))


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc_ = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc_:
        return a
    return b if pb <= pc_ else c


def encode_rows(rows, bpp, filters):
    out, prev = bytearray(), bytes(len(rows[0]))
    for y, row in enumerate(rows):
        f = filters[y % len(filters)]
        enc = bytearray()
        for i, x in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = prev[i]
            ul = prev[i - bpp] if i >= bpp else 0
            pred = {0: 0, 1: left, 2: up, 3: (left + up) >> 1, 4: paeth(left, up, ul)}[f]
            enc.append((x - pred) & 0xFF)
        out += bytes([f]) + enc
        prev = row
    return bytes(out)


def make_png(width, height, colour_type=6, pixel=None, filters=(0,), extra=b""):
    bpp = pc.CHANNELS[colour_type]
    pixel = pixel or (lambda x, y: tuple((x * 7 + y * 13 + c * 29) % 256 for c in range(bpp)))
    rows = [bytes(v for x in range(width) for v in pixel(x, y)) for y in range(height)]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    return (pc.SIGNATURE + chunk(b"IHDR", ihdr) + extra +
            chunk(b"IDAT", zlib.compress(encode_rows(rows, bpp, filters))) +
            chunk(b"IEND", b"")), rows


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = pc.main(args)
    return code, out.getvalue(), err.getvalue()


class PNGCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        p = self.dir / name
        p.write_bytes(data)
        return p

    def test_reads_dimensions_from_ihdr(self):
        data, _ = make_png(36, 64)
        p = self.write("a.png", data)
        code, out, _ = run([str(p), "--width", "36", "--height", "64", "--min-bytes", "1"])
        self.assertEqual(code, 0, out)
        self.assertIn("36x64", out)

    def test_wrong_dimensions_fail_with_one_line(self):
        data, _ = make_png(36, 64)
        p = self.write("a.png", data)
        code, _, err = run([str(p), "--width", "40", "--min-bytes", "1"])
        self.assertEqual(code, 1)
        self.assertIn("width 36", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_tolerance_allows_pdftoppm_rounding(self):
        data, _ = make_png(30, 21)
        p = self.write("a.png", data)
        self.assertEqual(run([str(p), "--width", "30", "--height", "20", "--tolerance", "1",
                              "--min-bytes", "1"])[0], 0)

    def test_preset_whatsapp(self):
        info = {"width": 720, "height": 1280}
        self.assertEqual(pc.PRESETS["whatsapp-720"][:2], (info["width"], info["height"]))
        data, _ = make_png(20, 20)
        p = self.write("a.png", data)
        self.assertEqual(run([str(p), "--preset", "whatsapp-720", "--min-bytes", "1"])[0], 1)

    def test_jpeg_renamed_to_png_exit_2(self):
        p = self.write("fake.png", b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        code, _, err = run([str(p)])
        self.assertEqual(code, 2)
        self.assertIn("JPEG", err)

    def test_html_error_page_exit_2(self):
        p = self.write("err.png", b"<html>500</html>")
        self.assertEqual(run([str(p)])[0], 2)

    def test_truncated_file_exit_2(self):
        data, _ = make_png(30, 30)
        p = self.write("cut.png", data[:-20])
        code, _, err = run([str(p)])
        self.assertEqual(code, 2)
        self.assertIn("truncated", err)

    def test_crc_corruption_exit_2(self):
        data, _ = make_png(10, 10)
        bad = bytearray(data)
        bad[20] ^= 0xFF  # inside IHDR body
        p = self.write("crc.png", bytes(bad))
        self.assertEqual(run([str(p)])[0], 2)

    def test_min_bytes_catches_blank_render(self):
        data, _ = make_png(4, 4)
        p = self.write("tiny.png", data)
        code, _, err = run([str(p)])
        self.assertEqual(code, 1)
        self.assertIn("bytes", err)

    def test_max_bytes(self):
        data, _ = make_png(40, 40)
        p = self.write("big.png", data)
        self.assertEqual(run([str(p), "--max-bytes", "50", "--min-bytes", "1"])[0], 1)

    def test_all_filter_types_decode_exactly(self):
        for ct in (0, 2, 4, 6):
            data, rows = make_png(9, 10, ct, filters=(0, 1, 2, 3, 4))
            p = self.write(f"f{ct}.png", data)
            self.assertEqual(pc.decode_rows(pc.inspect(p)), rows, f"colour type {ct}")

    def test_transparent_crest_passes_alpha_check(self):
        def crest(x, y):
            inside = 3 <= x <= 12 and 3 <= y <= 12
            return (122, 31, 31, 255) if inside else (0, 0, 0, 0)
        data, _ = make_png(16, 16, 6, crest, filters=(4,))
        p = self.write("crest.png", data)
        code, out, err = run([str(p), "--require-alpha", "--min-bytes", "1"])
        self.assertEqual(code, 0, out + err)

    def test_crest_with_background_box_fails(self):
        data, _ = make_png(16, 16, 6, lambda x, y: (255, 255, 255, 255))
        p = self.write("boxed.png", data)
        code, _, err = run([str(p), "--require-alpha", "--min-bytes", "1"])
        self.assertEqual(code, 1)
        self.assertIn("background box", err)

    def test_rgb_without_alpha_fails_alpha_check(self):
        data, _ = make_png(8, 8, 2)
        p = self.write("rgb.png", data)
        code, _, err = run([str(p), "--require-alpha", "--min-bytes", "1"])
        self.assertEqual(code, 1)
        self.assertIn("no alpha", err)

    def test_same_as_proves_byte_identity(self):
        data, _ = make_png(12, 12)
        a = self.write("official.png", data)
        b = self.write("copy.png", data)
        self.assertEqual(run([str(b), "--same-as", str(a), "--min-bytes", "1"])[0], 0)
        other, _ = make_png(12, 12, pixel=lambda x, y: (1, 2, 3, 255))
        c = self.write("redrawn.png", other)
        code, _, err = run([str(c), "--same-as", str(a), "--min-bytes", "1"])
        self.assertEqual(code, 1)
        self.assertIn("byte-identical", err)
        self.assertEqual(pc.inspect(a)["sha256"], hashlib.sha256(data).hexdigest())

    def test_missing_file_exit_2(self):
        self.assertEqual(run([str(self.dir / "none.png")])[0], 2)


if __name__ == "__main__":
    unittest.main()
