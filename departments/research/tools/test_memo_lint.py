"""Tests for memo_lint.py. Run: python3 -m unittest discover -s tools -p 'test_*.py'"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import memo_lint  # noqa: E402

QUICK = """# Research Memo: Hosting the Code.SCRIET event archive

## Question
Can the event archive move to a free static host without losing the custom domain?

## Why it matters / decision it feeds
The CEO decides this week whether Engineering builds the migration.

## Findings
- GitHub Pages serves custom domains with automatic HTTPS [1].

## Options & trade-offs
- GitHub Pages: free for public repositories [1].
- Stay on the VM: no change, but one more service to watch.

## Recommendation
Move the archive to GitHub Pages because the repository is already public.

## Open questions
- Does any archive page need server-side code?

## Sources
[1] GitHub Pages docs - https://docs.github.com/en/pages
"""

DECISION = QUICK.replace("## Open questions", """## Pre-mortem
Assume it failed in three months: the most likely cause is a DNS change made without a
rollback note.

## Open questions""")


def msgs(text, kind="auto", filename=None):
    return [m for _, m in memo_lint.lint_text(text, kind, filename)]


class MemoLintLogic(unittest.TestCase):
    def test_quick_memo_passes(self):
        self.assertEqual(msgs(QUICK), [])

    def test_decision_memo_passes_and_auto_detects(self):
        self.assertEqual(msgs(DECISION), [])
        self.assertEqual(msgs(DECISION, "decision"), [])

    def test_decision_kind_requires_premortem(self):
        self.assertTrue(any("pre-mortem" in m for m in msgs(QUICK, "decision")))

    def test_missing_section(self):
        text = QUICK.replace("## Open questions\n- Does any archive page need server-side code?\n",
                             "")
        self.assertIn("missing section 'open questions'", msgs(text))

    def test_out_of_order(self):
        rec = "## Recommendation\nMove the archive to GitHub Pages because the repository is already public.\n\n"
        text = QUICK.replace(rec, "")
        text = text.replace("## Findings", rec + "## Findings")
        self.assertTrue(any("out of order" in m for m in msgs(text)), msgs(text))

    def test_empty_recommendation(self):
        text = QUICK.replace("Move the archive to GitHub Pages because the repository is "
                             "already public.", "Pages.")
        self.assertTrue(any("Recommendation is empty" in m for m in msgs(text)))

    def test_empty_other_section(self):
        text = QUICK.replace("- Does any archive page need server-side code?", "")
        self.assertTrue(any("'open questions' is empty" in m for m in msgs(text)))

    def test_placeholders(self):
        for ph in ("TODO check this", "TBD", "Lorem ipsum", "[insert source]", "XXX",
                   "FIXME"):
            text = QUICK.replace("no change, but", f"no change, {ph}, but")
            self.assertTrue(any("placeholder" in m for m in msgs(text)), ph)

    def test_placeholder_in_code_is_ignored(self):
        text = QUICK.replace("no change, but", "no change (grep for `TODO`), but")
        self.assertEqual(msgs(text), [])

    def test_inline_decision_line_satisfies_why(self):
        text = QUICK.replace("\n## Why it matters / decision it feeds\n",
                             "\nDecision this feeds: ")
        self.assertEqual(msgs(text), [])

    def test_missing_title(self):
        text = QUICK.replace("# Research Memo: Hosting the Code.SCRIET event archive\n", "")
        self.assertTrue(any("no title" in m for m in msgs(text)))

    def test_duplicate_section(self):
        text = QUICK + "\n## Findings\n- again [1]\n"
        self.assertTrue(any("appears 2 times" in m for m in msgs(text)))

    def test_filed_name(self):
        self.assertEqual(msgs(QUICK, filename="2026-10-30-event-archive-hosting.md"), [])
        self.assertTrue(msgs(QUICK, filename="event-archive.md"))
        self.assertTrue(msgs(QUICK, filename="2026-13-40-event-archive.md"))
        self.assertTrue(msgs(QUICK, filename="2026-10-30-Event_Archive.md"))

    def test_templates_are_unfinished_until_filled(self):
        tdir = HERE.parent / "templates"
        for name in ("memo-quick.md", "memo-decision.md"):
            found = msgs((tdir / name).read_text())
            self.assertTrue(any("placeholder" in m for m in found), name)
            self.assertFalse(any("missing section" in m or "out of order" in m
                                 for m in found), (name, found))


class MemoLintCli(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(HERE / "memo_lint.py"), *args],
                              capture_output=True, text=True, timeout=60)

    def test_help(self):
        proc = self.run_tool("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Recommendation", proc.stdout)

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = Path(tmp) / "2026-10-30-archive.md"
            ok.write_text(DECISION)
            proc = self.run_tool(str(ok), "--filed")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

            bad = Path(tmp) / "bad.md"
            bad.write_text(QUICK.replace("## Recommendation", "## Notes"))
            proc = self.run_tool(str(bad))
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(len(proc.stderr.strip().splitlines()), 1)

            proc = self.run_tool(str(Path(tmp) / "nope.md"))
            self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
