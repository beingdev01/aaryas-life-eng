"""Tests for memo_index.py. Run: python3 -m unittest discover -s tools -p 'test_*.py'"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

GOOD = """# Research Memo: Free static host for the Code.SCRIET event archive

## Question
Which free host should serve the event archive? Requested by the CEO.

## Why it matters
Engineering builds the migration once this is decided.

## Findings
- GitHub Pages includes custom domains with HTTPS [1].

## Options & trade-offs
- GitHub Pages: free for public repositories [1].

## Recommendation
Use GitHub Pages. The repository is public already.

## Open questions
- None that change the recommendation.

## Sources
[1] GitHub Pages docs - https://docs.github.com/en/pages
"""

LEGACY = """# Honeybee facts

## Fact 1
Bees can add and subtract.
"""


class MemoIndex(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(HERE / "memo_index.py"), *args],
                              capture_output=True, text=True, timeout=60)

    def make_memos(self, tmp):
        memos = Path(tmp) / "memos"
        memos.mkdir()
        (memos / "2026-10-13-static-host.md").write_text(GOOD)
        (memos / "2026-10-29-later-memo.md").write_text(GOOD.replace("event archive",
                                                                     "club handbook"))
        (memos / "honeybee-funfacts.md").write_text(LEGACY)
        (memos / "README.md").write_text("# not a memo\n")
        (memos / ".gitkeep").write_text("")
        return memos

    def snapshot(self, folder):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}

    def test_help(self):
        proc = self.run_tool("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--memos", proc.stdout)

    def test_markdown_index_and_inputs_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            memos = self.make_memos(tmp)
            before = self.snapshot(memos)
            out = Path(tmp) / "out" / "INDEX.md"
            proc = self.run_tool("--memos", str(memos), "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(self.snapshot(memos), before)
            body = out.read_text()
            self.assertIn("3 memo(s), 2 pass", body)
            self.assertLess(body.index("2026-10-29"), body.index("2026-10-13"))
            self.assertLess(body.index("2026-10-13"), body.index("undated"))
            self.assertNotIn("README", body)
            self.assertIn("Use GitHub Pages.", body)

    def test_json_and_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            memos = self.make_memos(tmp)
            out = Path(tmp) / "index.json"
            proc = self.run_tool("--memos", str(memos), "--out", str(out), "--format", "json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(out.read_text())
            by_file = {m["file"]: m for m in data["memos"]}
            self.assertTrue(by_file["2026-10-13-static-host.md"]["conforms"])
            self.assertFalse(by_file["honeybee-funfacts.md"]["conforms"])
            self.assertEqual(by_file["honeybee-funfacts.md"]["date"], "undated")

            proc = self.run_tool("--memos", str(memos), "--out", str(out), "--strict")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("honeybee-funfacts.md", proc.stderr)

    def test_out_inside_memos_is_skipped_on_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            memos = self.make_memos(tmp)
            out = memos / "memo-index.md"
            for _ in range(2):
                proc = self.run_tool("--memos", str(memos), "--out", str(out))
                self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("3 memo(s)", out.read_text())
            self.assertFalse([p for p in os.listdir(memos) if p.startswith(".memo_index.")])

    def test_missing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_tool("--memos", str(Path(tmp) / "none"), "--out",
                                 str(Path(tmp) / "i.md"))
            self.assertEqual(proc.returncode, 2)
            self.assertIn("not found", proc.stderr)
            self.assertFalse((Path(tmp) / "i.md").exists())


if __name__ == "__main__":
    unittest.main()
