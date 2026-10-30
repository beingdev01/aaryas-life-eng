"""Tests for render_preview.py.

The logic is tested with a fake Chrome (a small Python script that writes a PNG of
the requested size), so these tests never need a real browser. One test renders a
tiny page with the real Chrome, and only runs if Chrome is installed under ~/.cache.
"""

import io
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import png_check  # noqa: E402
import render_preview as rp  # noqa: E402

FAKE_CHROME = textwrap.dedent('''\
    #!/usr/bin/env python3
    import struct, sys, zlib
    args = dict(a.split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    out = args.get("--screenshot")
    w, h = (int(v) for v in args["--window-size"].split(","))
    s = float(args.get("--force-device-scale-factor", "1"))
    w, h = round(w * s) + SKEW, round(h * s)
    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b))
    raw = b"".join(b"\\x00" + bytes((x * 31 + y * 17) % 256 for x in range(w * 3))
                   for y in range(h))
    data = (b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    if out and WRITE:
        open(out, "wb").write(data)
    ''')


def make_fake(path: Path, skew=0, write=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_CHROME.replace("SKEW", str(skew)).replace("WRITE", str(write)))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = rp.main(args)
    return code, out.getvalue(), err.getvalue()


class Discovery(unittest.TestCase):
    def test_finds_newest_puppeteer_chrome(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old = make_fake(home / ".cache/puppeteer/chrome/linux_arm-150.0/chrome-linux-arm64/chrome")
            new = make_fake(home / ".cache/puppeteer/chrome/linux_arm-155.0/chrome-linux-arm64/chrome")
            self.assertEqual(rp.find_chrome(home), new)
            self.assertNotEqual(rp.find_chrome(home), old)

    def test_falls_back_to_headless_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            shell = make_fake(home / ".cache/puppeteer/chrome-headless-shell/linux_arm-155.0/"
                                     "chrome-headless-shell-linux-arm64/chrome-headless-shell")
            self.assertEqual(rp.find_chrome(home), shell)
            flags = rp.chrome_flags(shell, "/tmp/p", 1000)
            self.assertIn("--headless", flags)

    def test_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(rp.find_chrome(Path(tmp)))


class CommandShape(unittest.TestCase):
    def test_screenshot_command_is_niced_and_sized(self):
        cmd = rp.build_screenshot_cmd(Path("/x/chrome"), Path("/w/index.html"),
                                      Path("/w/p.png"), 1123, 794, 2.0846, "/tmp/p", 1500)
        self.assertEqual(cmd[:3], ["nice", "-n", "19"])
        self.assertIn("--headless=new", cmd)
        self.assertIn("--window-size=1123,794", cmd)
        self.assertIn("--force-device-scale-factor=2.0846", cmd)
        self.assertIn("--screenshot=/w/p.png", cmd)
        self.assertEqual(cmd[-1], "file:///w/index.html")

    def test_print_commands(self):
        chrome_cmd, raster = rp.build_print_cmds(Path("/x/chrome"), Path("/w/c.html"),
                                                 Path("/w/c.pdf"), Path("/w/c"), 200,
                                                 "/tmp/p", 1500)
        self.assertIn("--print-to-pdf=/w/c.pdf", chrome_cmd)
        self.assertIn("--no-pdf-header-footer", chrome_cmd)
        self.assertEqual(raster[3:], ["pdftoppm", "-png", "-r", "200", "-singlefile",
                                      "/w/c.pdf", "/w/c"])

    def test_expected_size(self):
        self.assertEqual(rp.expected_size(1123, 794, 2.0846), (2341, 1655))
        self.assertEqual(rp.expected_size(720, 1280, 1), (720, 1280))


class EndToEndWithFakeChrome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.html = self.dir / "index.html"
        self.html.write_text("<html><body style='background:#101f3d'></body></html>")

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_path_verifies_png(self):
        fake = make_fake(self.dir / "bin/chrome")
        out = self.dir / "preview.png"
        code, stdout, err = run([str(self.html), str(out), "--width", "40", "--height", "70",
                                 "--chrome", str(fake)])
        self.assertEqual(code, 0, stdout + err)
        self.assertEqual(png_check.inspect(out)["width"], 40)
        self.assertIn("command: nice -n 19", stdout)

    def test_wrong_size_output_fails(self):
        fake = make_fake(self.dir / "bin/chrome", skew=3)
        code, _, err = run([str(self.html), str(self.dir / "p.png"), "--width", "40",
                            "--height", "70", "--chrome", str(fake)])
        self.assertEqual(code, 1)
        self.assertIn("width", err)

    def test_chrome_that_writes_nothing_fails(self):
        fake = make_fake(self.dir / "bin/chrome", write=False)
        code, _, err = run([str(self.html), str(self.dir / "p.png"), "--width", "40",
                            "--height", "70", "--chrome", str(fake)])
        self.assertEqual(code, 1)
        self.assertIn("wrote no file", err)

    def test_dry_run_prints_command(self):
        fake = make_fake(self.dir / "bin/chrome")
        code, out, _ = run([str(self.html), str(self.dir / "p.png"), "--width", "10",
                            "--height", "10", "--chrome", str(fake), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("--window-size=10,10", out)
        self.assertFalse((self.dir / "p.png").exists())

    def test_input_errors_exit_2(self):
        fake = make_fake(self.dir / "bin/chrome")
        self.assertEqual(run([str(self.dir / "none.html"), str(self.dir / "p.png"),
                              "--width", "1", "--height", "1", "--chrome", str(fake)])[0], 2)
        self.assertEqual(run([str(self.html), str(self.dir / "p.jpg"), "--width", "1",
                              "--height", "1", "--chrome", str(fake)])[0], 2)
        self.assertEqual(run([str(self.html), str(self.dir / "p.png"),
                              "--chrome", str(fake)])[0], 2)
        self.assertEqual(run([str(self.html), str(self.dir / "p.png"), "--width", "1",
                              "--height", "1", "--chrome", str(self.dir / "nochrome")])[0], 2)


REAL_CHROME = rp.find_chrome()


@unittest.skipUnless(REAL_CHROME and os.access(str(REAL_CHROME), os.X_OK),
                     "no Chrome under ~/.cache/puppeteer or ~/.cache/ms-playwright")
class RealChrome(unittest.TestCase):
    def test_tiny_real_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "t.html"
            html.write_text("<html><body style='margin:0;background:#f7f4ec;color:#0f2a4a'>"
                            "<p style='font:20px serif'>Preview</p></body></html>")
            out = Path(tmp) / "t.png"
            code, stdout, err = run([str(html), str(out), "--width", "160", "--height", "90",
                                     "--wait-ms", "300", "--timeout", "90"])
            self.assertEqual(code, 0, stdout + err)
            info = png_check.inspect(out)
            self.assertEqual((info["width"], info["height"]), (160, 90))


if __name__ == "__main__":
    unittest.main()
