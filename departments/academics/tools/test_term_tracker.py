"""Tests for term_tracker.py. Run: python3 -m unittest discover -s tools -p 'test_*.py'"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "templates" / "sample-calendar.json"
sys.path.insert(0, str(HERE))
import term_tracker  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cal = self.dir / "calendar.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(HERE / "term_tracker.py"), *args],
                              capture_output=True, text=True, timeout=60)

    def add(self, *extra, **kw):
        base = {"course": "MLP", "programme": "IITM", "kind": "deadline",
                "date": "2099-11-08", "time": "23:59", "source": "example notice",
                "status": "confirmed"}
        base.update(kw)
        args = ["add", "--calendar", str(self.cal)]
        for k, v in base.items():
            if v is not None:
                args += [f"--{k}", v]
        return self.run_tool(*args, *extra)

    def write(self, entries):
        self.cal.write_text(json.dumps({"schema": term_tracker.SCHEMA, "entries": entries}))


class AddAndList(Base):
    def test_help(self):
        proc = self.run_tool("--help")
        self.assertEqual(proc.returncode, 0)
        for word in ("add", "upcoming", "clashes", "validate"):
            self.assertIn(word, proc.stdout)

    def test_add_creates_file_and_generates_id(self):
        proc = self.add(title="Week 6 GA")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(self.cal.read_text())
        self.assertEqual(data["schema"], term_tracker.SCHEMA)
        self.assertEqual(data["entries"][0]["id"], "iitm-mlp-deadline-2099-11-08")
        self.assertEqual(data["entries"][0]["timezone"], "IST")
        proc = self.add(title="Week 7 GA")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ids = [e["id"] for e in json.loads(self.cal.read_text())["entries"]]
        self.assertEqual(ids[1], "iitm-mlp-deadline-2099-11-08-2")

    def test_add_rejects_duplicate(self):
        self.assertEqual(self.add(title="Week 6 GA").returncode, 0)
        proc = self.add(title="week 6 ga")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("duplicate", proc.stderr)
        self.assertEqual(len(json.loads(self.cal.read_text())["entries"]), 1)

    def test_add_rejects_bad_values_without_writing(self):
        cases = [dict(date="2099-02-30"), dict(date="15-11-2099"), dict(time="25:00"),
                 dict(source="unknown"), dict(time=None), dict(timezone="Mars/Base")]
        for case in cases:
            proc = self.add(**case)
            self.assertEqual(proc.returncode, 1, (case, proc.stdout))
            self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
            self.assertFalse(self.cal.exists(), case)

    def test_tentative_entry_may_have_no_time(self):
        proc = self.add(time=None, status="tentative", kind="exam")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.run_tool("list", "--calendar", str(self.cal))
        self.assertIn("time ? IST", proc.stdout)

    def test_list_sorted_in_ist_and_filters(self):
        self.write([
            {"id": "b", "course": "Data Mining", "programme": "CCSU", "kind": "exam",
             "date": "2099-11-10", "time": "10:00", "timezone": "IST", "source": "notice",
             "status": "confirmed"},
            {"id": "a", "course": "MLP", "programme": "IITM", "kind": "deadline",
             "date": "2099-11-09", "time": "20:00", "timezone": "UTC", "source": "portal",
             "status": "confirmed"},
        ])
        proc = self.run_tool("list", "--calendar", str(self.cal))
        lines = proc.stdout.strip().splitlines()
        # 20:00 UTC on the 9th is 01:30 IST on the 10th, before the 10:00 exam.
        self.assertTrue(lines[0].startswith("2099-11-10 Tue 01:30 IST"), lines)
        proc = self.run_tool("list", "--calendar", str(self.cal), "--programme", "CCSU",
                             "--json")
        rows = json.loads(proc.stdout)
        self.assertEqual([r["id"] for r in rows], ["b"])


class Update(Base):
    def test_update_needs_source_and_keeps_history(self):
        self.assertEqual(self.add(kind="exam", status="tentative", time="10:00").returncode, 0)
        eid = json.loads(self.cal.read_text())["entries"][0]["id"]
        proc = self.run_tool("update", "--calendar", str(self.cal), "--id", eid,
                             "--date", "2099-11-09")
        self.assertEqual(proc.returncode, 2)  # argparse: --source is required
        proc = self.run_tool("update", "--calendar", str(self.cal), "--id", eid,
                             "--date", "2099-11-09", "--status", "confirmed",
                             "--source", "written date sheet, example")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        e = json.loads(self.cal.read_text())["entries"][0]
        self.assertEqual((e["date"], e["status"]), ("2099-11-09", "confirmed"))
        self.assertIn("was 2099-11-08 10:00 IST tentative (source: example notice)", e["notes"])

    def test_update_rejects_bad_change_and_unknown_id(self):
        self.assertEqual(self.add().returncode, 0)
        before = self.cal.read_text()
        eid = json.loads(before)["entries"][0]["id"]
        proc = self.run_tool("update", "--calendar", str(self.cal), "--id", eid,
                             "--no-time", "--source", "x notice")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("needs a time", proc.stderr)
        proc = self.run_tool("update", "--calendar", str(self.cal), "--id", "nope",
                             "--date", "2099-01-01", "--source", "x notice")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.cal.read_text(), before)


class Windows(Base):
    def setUp(self):
        super().setUp()
        shutil.copy(SAMPLE, self.cal)

    def test_sample_calendar_validates(self):
        proc = self.run_tool("validate", "--calendar", str(self.cal))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("8 entries", proc.stdout)

    def test_sample_dates_are_clearly_fake(self):
        data = json.loads(SAMPLE.read_text())
        for e in data["entries"]:
            self.assertTrue(e["date"].startswith("2099-"), e)
            self.assertIn("EXAMPLE", e["source"])

    def test_upcoming_window_sorted(self):
        proc = self.run_tool("upcoming", "--calendar", str(self.cal), "--from", "2099-11-08",
                             "--days", "8", "--json")
        rows = json.loads(proc.stdout)
        self.assertEqual([r["id"] for r in rows], [
            "iitm-mlp-deadline-2099-11-08", "ccsu-computer-networks-class-2099-11-10",
            "ccsu-computer-networks-exam-2099-11-15", "iitm-mlp-quiz-2099-11-15",
            "iitm-tds-deadline-2099-11-15"])
        self.assertEqual(rows[0]["days_left"], 0)
        proc = self.run_tool("upcoming", "--calendar", str(self.cal), "--from", "2099-12-01")
        self.assertIn("no entries", proc.stdout)

    def test_clashes_same_day_and_window(self):
        proc = self.run_tool("clashes", "--calendar", str(self.cal), "--json")
        pairs = {(c["iitm"]["id"], c["ccsu"]["id"]) for c in json.loads(proc.stdout)}
        self.assertEqual(pairs, {
            ("iitm-mlp-quiz-2099-11-15", "ccsu-computer-networks-exam-2099-11-15"),
            ("iitm-tds-deadline-2099-11-15", "ccsu-computer-networks-exam-2099-11-15")})
        proc = self.run_tool("clashes", "--calendar", str(self.cal), "--window", "3")
        self.assertIn("NEAR (3 day(s) apart)", proc.stdout)
        proc = self.run_tool("clashes", "--calendar", str(self.cal), "--strict")
        self.assertEqual(proc.returncode, 1)
        proc = self.run_tool("clashes", "--calendar", str(self.cal), "--kinds", "class")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("no clashes", proc.stdout)

    def test_remind_lead_times(self):
        proc = self.run_tool("remind", "--calendar", str(self.cal), "--from", "2099-11-01",
                             "--json")
        ids = [r["id"] for r in json.loads(proc.stdout)]
        # 7 days before the GA deadline; 14 days before the quiz and the CN exam. The
        # 2099-11-15 deadline is 14 days out, which is not a deadline lead time.
        self.assertEqual(ids, ["iitm-mlp-deadline-2099-11-08",
                               "ccsu-computer-networks-exam-2099-11-15",
                               "iitm-mlp-quiz-2099-11-15"])
        proc = self.run_tool("remind", "--calendar", str(self.cal), "--from", "2099-11-08",
                             "--json")
        ids = [r["id"] for r in json.loads(proc.stdout)]
        self.assertIn("iitm-tds-deadline-2099-11-15", ids)
        self.assertIn("iitm-mlp-deadline-2099-11-08", ids)


class Malformed(Base):
    def test_malformed_files_fail(self):
        good = json.loads(SAMPLE.read_text())["entries"][0]
        cases = {
            "not json": "{nope",
            "no entries": json.dumps({"schema": term_tracker.SCHEMA}),
            "bad programme": json.dumps({"entries": [dict(good, programme="IIT")]}),
            "bad kind": json.dumps({"entries": [dict(good, kind="assignment")]}),
            "bad status": json.dumps({"entries": [dict(good, status="maybe")]}),
            "unknown field": json.dumps({"entries": [dict(good, colour="red")]}),
            "duplicate id": json.dumps({"entries": [good, dict(good, title="x")]}),
            "confirmed no time": json.dumps({"entries": [dict(good, time=None)]}),
            "missing source": json.dumps({"entries": [{k: v for k, v in good.items()
                                                       if k != "source"}]}),
        }
        for name, body in cases.items():
            self.cal.write_text(body)
            for cmd in (["validate"], ["upcoming"], ["clashes"], ["list"]):
                proc = self.run_tool(*cmd, "--calendar", str(self.cal))
                self.assertEqual(proc.returncode, 1, (name, cmd, proc.stdout))
                self.assertEqual(len(proc.stderr.strip().splitlines()), 1, (name, cmd))
                self.assertTrue(proc.stderr.startswith("term_tracker:"), proc.stderr)

    def test_missing_file(self):
        proc = self.run_tool("upcoming", "--calendar", str(self.dir / "none.json"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no such calendar", proc.stderr)

    def test_validate_lists_every_problem(self):
        good = json.loads(SAMPLE.read_text())["entries"][0]
        self.write([dict(good, programme="X"), dict(good, id="other", date="2099-13-01")])
        proc = self.run_tool("validate", "--calendar", str(self.cal))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("programme 'X'", proc.stdout)
        self.assertIn("not a real date", proc.stdout)


if __name__ == "__main__":
    unittest.main()
