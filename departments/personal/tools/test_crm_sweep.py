"""Tests for crm_sweep.py. All fixtures are invented; nothing here reads the live CRM."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "crm_sweep.py"


def run(args, expect_rc=None):
    proc = subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True)
    if expect_rc is not None:
        assert proc.returncode == expect_rc, (
            f"rc={proc.returncode} wanted {expect_rc}\n{proc.stdout}\n{proc.stderr}")
    return proc


def people(records):
    fd = tempfile.TemporaryDirectory()
    path = Path(fd.name) / "people.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return str(path), fd


CLEAN = [
    {"id": "asha-verma", "name": "Asha Verma", "relationship": "mentor",
     "contact_info": {"email": "asha@example.test", "phone": "9999900001"},
     "birthday": "1975-11-05", "last_contact": "2026-10-01", "notes": "ask about sabbatical",
     "tags": []},
    {"id": "rohit-nanda", "name": "Rohit Nanda", "relationship": "friend",
     "contact_info": {"phone": "9999900002"}, "birthday": "1990-11-20",
     "last_contact": "2026-08-01", "tags": []},
    {"id": "kavita-sharma", "name": "Kavita Sharma", "relationship": "family",
     "birthday": "1900-11-08", "last_contact": "2026-10-20", "tags": ["priority"]},
    {"id": "no-dates", "name": "Irfan Qureshi", "relationship": "advisor", "tags": []},
]
TODAY = "2026-11-01"


class SweepTest(unittest.TestCase):
    def setUp(self):
        self.path, self.fd = people(CLEAN)
        self.addCleanup(self.fd.cleanup)

    def report(self, extra=()):
        proc = run(["--people", self.path, "--today", TODAY, "--json", *extra])
        return proc, json.loads(proc.stdout)

    def test_stale_uses_default_threshold(self):
        proc, rep = self.report()
        ids = [s["id"] for s in rep["stale"]]
        self.assertIn("asha-verma", ids)
        self.assertNotIn("rohit-nanda", ids)
        self.assertNotIn("no-dates", ids)
        self.assertEqual(rep["stale"][0]["threshold"], 14)

    def test_quiet_bucket_catches_very_old(self):
        proc, rep = self.report()
        self.assertEqual([q["id"] for q in rep["quiet"]], ["rohit-nanda"])
        self.assertGreaterEqual(rep["quiet"][0]["days_since"], 45)

    def test_priority_threshold_is_seven_days(self):
        proc, rep = self.report()
        self.assertIn("kavita-sharma", [s["id"] for s in rep["stale"]])
        self.assertEqual(rep["stale"][-1]["threshold"], 7)

    def test_missing_last_contact_is_unknown_not_zero(self):
        proc, rep = self.report()
        self.assertEqual([u["id"] for u in rep["unknown"]], ["no-dates"])
        self.assertIsNone(rep["unknown"][0]["days_since"])

    def test_birthday_window_and_unknown_year(self):
        proc, rep = self.report()
        occ = {o["id"]: o for o in rep["occasions"]}
        self.assertIn("kavita-sharma", occ)
        self.assertEqual(occ["kavita-sharma"]["on"], "11-08")
        self.assertFalse(occ["kavita-sharma"]["year_known"])
        self.assertTrue(occ["asha-verma"]["year_known"])

    def test_outside_window_is_not_reported(self):
        proc, rep = self.report(["--occasion-days", "3"])
        self.assertNotIn("asha-verma", [o["id"] for o in rep["occasions"]])

    def test_future_last_contact_is_a_defect(self):
        bad = [dict(CLEAN[0], last_contact="2027-01-01")]
        path, fd = people(bad)
        self.addCleanup(fd.cleanup)
        proc = run(["--people", path, "--today", TODAY, "--json"])
        rep = json.loads(proc.stdout)
        self.assertEqual(rep["defects"][0]["value_shape"], "in the future")
        self.assertEqual(rep["stale"], [])

    def test_malformed_date_is_a_defect(self):
        bad = [dict(CLEAN[1], last_contact="01-08-2026")]
        path, fd = people(bad)
        self.addCleanup(fd.cleanup)
        proc = run(["--people", path, "--today", TODAY, "--json"])
        rep = json.loads(proc.stdout)
        self.assertEqual(rep["defects"][0]["field"], "last_contact")

    def test_due_count_and_exit_three(self):
        proc, rep = self.report()
        self.assertEqual(rep["due"], len(rep["stale"]) + len(rep["occasions"]))
        self.assertEqual(proc.returncode, 3)

    def test_nothing_due_exits_zero(self):
        fresh = [dict(CLEAN[2], last_contact="2026-10-30", birthday="1970-05-05")]
        path, fd = people(fresh)
        self.addCleanup(fd.cleanup)
        proc = run(["--people", path, "--today", TODAY, "--json"])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["due"], 0)

    def test_missing_file_exits_two(self):
        run(["--people", "/nonexistent/people.json", "--today", TODAY], expect_rc=2)

    def test_bad_today_exits_two(self):
        run(["--people", self.path, "--today", "yesterday"], expect_rc=2)

    def test_wrapped_object_store_is_accepted(self):
        path, fd = people({"people": CLEAN})
        self.addCleanup(fd.cleanup)
        proc = run(["--people", path, "--today", TODAY, "--json"])
        self.assertGreater(json.loads(proc.stdout)["checked"], 0)

    def test_non_list_store_exits_two(self):
        fd = tempfile.TemporaryDirectory()
        p = Path(fd.name) / "people.json"
        p.write_text('{"notes": "just a string"}', encoding="utf-8")
        self.addCleanup(fd.cleanup)
        run(["--people", str(p), "--today", TODAY, "--json"], expect_rc=2)

    def test_contact_values_never_appear_in_output(self):
        proc, _ = self.report()
        blob = proc.stdout
        self.assertNotIn("asha@example.test", blob)
        self.assertNotIn("9999900001", blob)

    def test_text_report_also_scrubs(self):
        proc = run(["--people", self.path, "--today", TODAY])
        self.assertNotIn("asha@example.test", proc.stdout)
        self.assertIn("## Stale contacts", proc.stdout)

    def test_scrub_refuses_when_a_field_holds_an_email(self):
        leaked = [dict(CLEAN[0], name="asha@example.test")]
        path, fd = people(leaked)
        self.addCleanup(fd.cleanup)
        proc = run(["--people", path, "--today", TODAY, "--json"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("refusing to print", proc.stderr)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":
    unittest.main()
