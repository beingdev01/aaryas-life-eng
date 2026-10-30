#!/usr/bin/env python3
"""Unit tests for the outreach dedupe / already-seen checker. Temp dirs only."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seen_check  # noqa: E402

PIPE = """# Outreach Pipeline

| prospect | tier | contact | angle | status | last touch | next step | notes |
|---|---|---|---|---|---|---|---|
| Fictional Sponsor Corp | startup | partnerships@example.test | data workshop | sent | 2027-10-20 | poll | active |
| Recent Decline Co | dev-tools | via form | testing | declined | 2027-10-25 | none | cooloff |
| Long Gone Ltd | local | info@example.test | old ask | declined | 2026-01-05 | none | expired |
"""

PROSPECTS = """# Sponsor Prospects — 2027-11-01

## 1. Fictional Sponsor Corp
- **Company:** Fictional Sponsor Corp (example.test)

## 2. Brand New Startup
- **Company:** Brand New Startup (newco.example.test)
"""


class SeenCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.pipe = os.path.join(d, "pipeline.md")
        with open(self.pipe, "w", encoding="utf-8") as fh:
            fh.write(PIPE)
        self.pdir = os.path.join(d, "prospects")
        os.makedirs(self.pdir)
        self.pfile = os.path.join(self.pdir, "2027-11-01.md")
        with open(self.pfile, "w", encoding="utf-8") as fh:
            fh.write(PROSPECTS)

    def tearDown(self):
        self.tmp.cleanup()

    def _dup(self, company, days=180, today="2027-11-01"):
        import datetime as dt
        t = dt.date(*map(int, today.split("-")))
        return seen_check.scan_seen(company, self.pipe, self.pdir, days, t,
                                    exclude_files={os.path.abspath(self.pfile)})

    def test_active_row_is_duplicate(self):
        dup, reason = self._dup("Fictional Sponsor Corp")
        self.assertTrue(dup)
        self.assertIn("already in pipeline", reason)

    def test_declined_within_cooloff_is_duplicate(self):
        dup, _ = self._dup("Recent Decline Co", days=180)
        self.assertTrue(dup)

    def test_declined_past_cooloff_is_clear(self):
        dup, _ = self._dup("Long Gone Ltd", days=180)
        self.assertFalse(dup)

    def test_new_company_is_clear(self):
        dup, _ = self._dup("Brand New Startup")
        self.assertFalse(dup)

    def test_appears_in_other_run_file_is_duplicate(self):
        # A company drafted by an earlier run (a different prospect file) is caught.
        other = os.path.join(self.pdir, "2027-10-31.md")
        with open(other, "w", encoding="utf-8") as fh:
            fh.write("## 1. Brand New Startup\n- **Company:** Brand New Startup (x)\n")
        import datetime as dt
        t = dt.date(2027, 11, 1)
        dup, reason = seen_check.scan_seen(
            "Brand New Startup", self.pipe, self.pdir, 180, t,
            exclude_files={os.path.abspath(self.pfile)})
        self.assertTrue(dup)
        self.assertIn("prospect file", reason)

    def test_name_match_case_insensitive(self):
        self.assertTrue(seen_check.match("GEEKSFORGEEKS", "GeeksforGeeks"))
        self.assertTrue(seen_check.match("Fictional Sponsor Corp", "fictional sponsor corp"))

    def test_main_exit_code_duplicate(self):
        rc = seen_check.main(["--company", "Fictional Sponsor Corp",
                              "--pipeline", self.pipe, "--today", "2027-11-01"])
        self.assertEqual(rc, 1)

    def test_main_exit_code_clear(self):
        rc = seen_check.main(["--company", "Brand New Startup",
                              "--pipeline", self.pipe, "--today", "2027-11-01"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
