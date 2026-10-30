#!/usr/bin/env python3
"""Unit tests for the outreach pipeline lint. Temp dirs only."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline_lint  # noqa: E402

HEADER = ("| prospect | tier | contact | angle | status | last touch | next step | notes |\n"
          "|---|---|---|---|---|---|---|---|\n")

GOOD = ("# Pipeline\n" + HEADER +
        "| Fictional Sponsor Corp | startup | partnerships@example.test | data | sent | 2027-10-20 | poll | active |\n"
        "| Example Dev Tools | dev-tools | via form | testing | new | 2027-11-01 | CEO digest | not sent |\n")


def _run(text):
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        problems, nrows = pipeline_lint.lint(path, set(pipeline_lint.ALLOWED_STATUSES))
        rc = pipeline_lint.main([path])
    finally:
        os.remove(path)
    return problems, nrows, rc


class PipelineLintTest(unittest.TestCase):
    def test_good_table_passes(self):
        problems, nrows, rc = _run(GOOD)
        self.assertEqual(problems, [])
        self.assertEqual(nrows, 2)
        self.assertEqual(rc, 0)

    def test_bad_status_flagged(self):
        t = GOOD.replace("| sent |", "| contacted |", 1)
        problems, _, rc = _run(t)
        self.assertTrue(any("not in allowed set" in p for p in problems))
        self.assertEqual(rc, 1)

    def test_non_iso_date_flagged(self):
        t = GOOD.replace("2027-10-20", "20-10-2027", 1)
        problems, _, _ = _run(t)
        self.assertTrue(any("ISO" in p for p in problems))

    def test_blank_next_step_flagged(self):
        t = GOOD.replace("| sent | 2027-10-20 | poll |", "| sent | 2027-10-20 |  |", 1)
        problems, _, _ = _run(t)
        self.assertTrue(any("blank next step" in p for p in problems))

    def test_duplicate_company_flagged(self):
        t = GOOD + "| Fictional Sponsor Corp | local | a@example.test | x | new | 2027-11-02 | y | dup |\n"
        problems, _, _ = _run(t)
        self.assertTrue(any("duplicate prospect" in p for p in problems))

    def test_short_row_flagged(self):
        t = GOOD + "| Ragged | local\n"
        problems, _, _ = _run(t)
        self.assertTrue(any("row structure does not match" in p for p in problems))

    def test_missing_column_flagged(self):
        bad_hdr = ("| prospect | tier | contact | angle | status | last touch | notes |\n"
                   "|---|---|---|---|---|---|---|\n"
                   "| A | local | a@example.test | x | new | 2027-11-01 | n |\n")
        p2, _, rc2 = _run(bad_hdr)
        self.assertTrue(any("missing required column" in p for p in p2))
        self.assertEqual(rc2, 1)


if __name__ == "__main__":
    unittest.main()
