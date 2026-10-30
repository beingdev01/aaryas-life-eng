"""Tests for event_checklist.py. Output goes to temp dirs; --today pins the clock."""

import datetime as dt
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draft_lint  # noqa: E402
import event_checklist as ec  # noqa: E402


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ec.main(args)
    return code, out.getvalue(), err.getvalue()


class Dates(unittest.TestCase):
    def setUp(self):
        self.text, self.late = ec.build("Git and GitHub Workshop", dt.date(2026, 11, 14),
                                        "workshop", "SCRIET computer lab", dt.date(2026, 10, 20))

    def test_phase_dates_are_real(self):
        self.assertIn("## T-21 - Saturday, 24 October 2026", self.text)
        self.assertIn("## T-7 - Saturday, 7 November 2026", self.text)
        self.assertIn("## T-0 - Saturday, 14 November 2026 - Event day", self.text)
        self.assertIn("## T+2 - Monday, 16 November 2026", self.text)
        self.assertEqual(self.late, 0)

    def test_all_phases_in_order(self):
        labels = ["T-21", "T-14", "T-10", "T-7", "T-3", "T-1", "T-0", "T+1", "T+2"]
        positions = [self.text.index(f"## {lab} ") for lab in labels]
        self.assertEqual(positions, sorted(positions))

    def test_workshop_lines_and_roles(self):
        self.assertIn("Computer lab at SCRIET", self.text)
        self.assertIn("Owner: Management Head.", self.text)
        self.assertNotIn("Problem statements", self.text)

    def test_marker_and_draft_lint_clean(self):
        self.assertIn("DRAFT FOR CEO REVIEW", self.text)
        self.assertEqual(draft_lint.lint(self.text, max_words=5000), [])

    def test_sunday_office_work_moves_to_saturday(self):
        # Event on Sunday 15 Nov 2026: T-21 is Sunday 25 Oct.
        text, _ = ec.build("Talk", dt.date(2026, 11, 15), "talk", None, dt.date(2026, 10, 1))
        self.assertIn("falls on a Sunday; offices are closed, do it on Saturday, 24 October 2026",
                      text)

    def test_every_kind_adds_its_own_lines(self):
        marks = {"workshop": "Computer lab", "hackathon": "judging rubric",
                 "talk": "Speaker bio and photo", "orientation": "four-lane Design Team"}
        for kind, mark in marks.items():
            text, _ = ec.build("E", dt.date(2027, 8, 20), kind, None, dt.date(2027, 7, 1))
            self.assertIn(mark, text, kind)
            self.assertEqual(draft_lint.lint(text, max_words=5000), [], kind)

    def test_compressed_timeline(self):
        text, late = ec.build("E", dt.date(2026, 11, 14), "workshop", None, dt.date(2026, 11, 5))
        self.assertEqual(late, 3)  # T-21, T-14, T-10 already past
        self.assertIn("Compressed timeline: 3 phase(s)", text)
        self.assertIn("(late: this date has passed; do these now)", text)


class CommandLine(unittest.TestCase):
    def test_writes_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "event" / "checklist.md"
            code, stdout, _ = run(["--event", "Hack Night", "--date", "2026-12-05", "--kind",
                                   "hackathon", "--today", "2026-11-01", "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            self.assertIn("Prize budget approved", out.read_text())
            self.assertIn("items", stdout)

    def test_past_event_refused(self):
        code, _, err = run(["--event", "Old", "--date", "2026-01-01", "--today", "2026-10-30"])
        self.assertEqual(code, 1)
        self.assertIn("in the past", err)

    def test_bad_arguments(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(ec.main(["--event", "X", "--date", "14-11-2026"]), 2)
            self.assertEqual(ec.main(["--event", "X", "--date", "2026-11-14", "--kind", "party"]), 2)
        self.assertEqual(run(["--event", " ", "--date", "2026-11-14", "--today", "2026-10-01"])[0], 2)

    def test_help_exits_zero(self):
        self.assertEqual(run(["--help"])[0], 0)


if __name__ == "__main__":
    unittest.main()
