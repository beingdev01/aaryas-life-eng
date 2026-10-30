"""Tests for tmp_sandbox_report.py. Temp dirs and a fake /proc only; nothing is deleted."""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmp_sandbox_report as tsr  # noqa: E402

HOUR = 3600


class TmpSandboxReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "tmp"
        self.proc = base / "proc"
        self.root.mkdir()
        self.proc.mkdir()
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()

    def make_dir(self, name, age_hours, size=1000):
        d = self.root / name
        (d / "sub").mkdir(parents=True)
        f = d / "sub" / "out.log"
        f.write_bytes(b"x" * size)
        t = self.now - age_hours * HOUR
        for p in (f, d / "sub", d):
            os.utime(p, (t, t))
        return d

    def hold(self, pid, cwd=None, fd_target=None):
        p = self.proc / str(pid)
        (p / "fd").mkdir(parents=True)
        os.symlink(str(cwd or "/"), p / "cwd")
        if fd_target:
            os.symlink(str(fd_target), p / "fd" / "3")

    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = tsr.main(["--root", str(self.root), "--proc", str(self.proc), *argv], now=self.now)
        return rc, out.getvalue(), err.getvalue()

    def test_stale_and_fresh_are_classified(self):
        self.make_dir("paperclip-run-aar-109-08d7ba3b-4f3-aUWZTH", 72)
        self.make_dir("paperclip-run-aar-200-aaaa-bbb-Fresh1", 2)
        self.make_dir("eng-probe", 30)
        self.make_dir("unrelated-dir", 500)
        rc, out, _ = self.run_tool("--json")
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["dirs"], 3)
        self.assertEqual(data["stale_dirs"], 2)
        stale = {Path(r["path"]).name for r in data["rows"] if r["stale"]}
        self.assertEqual(stale, {"paperclip-run-aar-109-08d7ba3b-4f3-aUWZTH", "eng-probe"})
        self.assertIn("xargs -0 -r rm -rf --", data["cleanup_command"])

    def test_dir_held_as_cwd_is_never_stale(self):
        d = self.make_dir("paperclip-run-aar-186-9913b6c6-03b-0Wmdlk", 48)
        self.hold(2259117, cwd=d)
        rc, out, _ = self.run_tool("--json")
        row = json.loads(out)["rows"][0]
        self.assertTrue(row["held_open"])
        self.assertFalse(row["stale"])

    def test_dir_held_by_open_fd_is_never_stale(self):
        d = self.make_dir("eng-next", 48)
        self.hold(4242, cwd="/home/ubuntu", fd_target=d / "sub" / "out.log")
        rc, out, _ = self.run_tool("--json")
        self.assertFalse(json.loads(out)["rows"][0]["stale"])

    def test_print0_lists_only_stale_unheld(self):
        a = self.make_dir("eng-a", 48)
        b = self.make_dir("eng-b", 48)
        self.make_dir("eng-c", 1)
        self.hold(1, cwd=b)
        rc, out, _ = self.run_tool("--print0-stale")
        self.assertEqual(rc, 0)
        self.assertEqual([p for p in out.split("\0") if p], [str(a)])

    def test_symlinks_and_files_are_never_candidates(self):
        target = self.make_dir("keep-me", 100)
        os.symlink(str(target), self.root / "eng-link")
        (self.root / "eng-probe.json").write_text("{}")
        rc, out, _ = self.run_tool("--json")
        self.assertEqual(json.loads(out)["dirs"], 0)

    def test_nothing_is_deleted(self):
        d = self.make_dir("paperclip-run-old", 1000)
        self.run_tool()
        self.run_tool("--print0-stale")
        self.assertTrue((d / "sub" / "out.log").exists())

    def test_markdown_has_ceo_section_and_sizes(self):
        self.make_dir("paperclip-run-old", 100, size=8192)
        rc, out, _ = self.run_tool()
        self.assertEqual(rc, 0)
        self.assertIn("## Commands for the CEO", out)
        self.assertIn("platform-1 never deletes", out)
        self.assertIn("Stale (no change for 24h", out)

    def test_nothing_stale_says_so(self):
        self.make_dir("eng-new", 1)
        rc, out, _ = self.run_tool()
        self.assertIn("No commands needed", out)

    def test_threshold_and_pattern_options(self):
        self.make_dir("eng-x", 30)
        self.make_dir("scratch-1", 30)
        rc, out, _ = self.run_tool("--json", "--older-than-hours", "48")
        self.assertEqual(json.loads(out)["stale_dirs"], 0)
        rc, out, _ = self.run_tool("--json", "--pattern", "scratch-*")
        data = json.loads(out)
        self.assertEqual([Path(r["path"]).name for r in data["rows"]], ["scratch-1"])

    def test_refuses_tiny_threshold_and_missing_root(self):
        rc, _, err = self.run_tool("--older-than-hours", "0.1")
        self.assertEqual(rc, 2)
        self.assertIn("refused", err)
        err_buf = io.StringIO()
        with redirect_stderr(err_buf), redirect_stdout(io.StringIO()):
            rc = tsr.main(["--root", str(self.root / "nope")])
        self.assertEqual(rc, 2)
        self.assertIn("not a directory", err_buf.getvalue())

    def test_out_file_written(self):
        self.make_dir("eng-x", 30)
        out_path = self.root.parent / "reports" / "tmp-report.md"
        rc, _, _ = self.run_tool("--out", str(out_path))
        self.assertEqual(rc, 0)
        self.assertIn("Commands for the CEO", out_path.read_text())


if __name__ == "__main__":
    unittest.main()
