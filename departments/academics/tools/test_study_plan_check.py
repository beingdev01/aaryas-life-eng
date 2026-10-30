"""Tests for study_plan_check.py. Run: python3 -m unittest discover -s tools -p 'test_*.py'"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
sys.path.insert(0, str(HERE))
import study_plan_check as spc  # noqa: E402
import term_tracker  # noqa: E402

CAL = {"schema": term_tracker.SCHEMA, "entries": [
    {"id": "iitm-mlp-quiz-2099-11-15", "course": "MLP", "programme": "IITM", "kind": "quiz",
     "date": "2099-11-15", "time": "14:00", "timezone": "IST", "source": "example",
     "status": "confirmed"},
    {"id": "ccsu-dbms-exam-2099-11-18", "course": "DBMS", "programme": "CCSU", "kind": "exam",
     "date": "2099-11-18", "time": "10:00", "timezone": "IST", "source": "example",
     "status": "tentative"},
    {"id": "iitm-mlp-deadline-2099-11-10", "course": "MLP", "programme": "IITM",
     "kind": "deadline", "date": "2099-11-10", "time": "23:59", "timezone": "IST",
     "source": "example", "status": "confirmed"},
]}

PLAN = """# Study plan
Period: 2099-11-01 to 2099-11-20

## Schedule
| Date | Time (IST) | Course | Session |
|---|---|---|---|
| 2099-11-02 | 18:00 | MLP | Revision: weeks 1-3 |
| 2099-11-09 | 18:00 | MLP | Practice: past quiz papers |
| 2099-11-11 | 18:00 | DBMS | Review: normalisation |
- 2099-11-16 18:00 IST DBMS recap of SQL joins
"""


def check(plan, cal=CAL, min_sessions=2, kinds=("exam", "quiz")):
    probs, stats = spc.plan_problems(plan, cal, min_sessions, list(kinds))
    return [m for _, m in probs], stats


class PlanLogic(unittest.TestCase):
    def test_good_plan_passes(self):
        probs, stats = check(PLAN)
        self.assertEqual(probs, [])
        self.assertEqual(stats["exams"], 2)
        self.assertEqual(stats["sessions"], 4)

    def test_no_schedule(self):
        probs, _ = check("# Plan\n\nRead notes every day.\n")
        self.assertTrue(any("no dated schedule" in p and "no section" in p for p in probs))
        probs, _ = check("# Plan\n## Schedule\nEvery evening.\n")
        self.assertTrue(any("no dated session lines" in p for p in probs))

    def test_invalid_date_in_schedule(self):
        probs, _ = check(PLAN + "- 2099-11-31 MLP revision\n")
        self.assertTrue(any("not a real date" in p for p in probs))

    def test_exam_without_enough_revision(self):
        plan = PLAN.replace("- 2099-11-16 18:00 IST DBMS recap of SQL joins\n", "")
        probs, _ = check(plan)
        self.assertTrue(any("ccsu-dbms-exam-2099-11-18" in p and "has 1 revision" in p
                            and "tentative" in p for p in probs), probs)

    def test_non_revision_sessions_do_not_count(self):
        plan = PLAN.replace("Practice: past quiz papers", "attend lecture")
        probs, _ = check(plan)
        self.assertTrue(any("iitm-mlp-quiz-2099-11-15" in p for p in probs), probs)

    def test_session_on_exam_day(self):
        probs, _ = check(PLAN + "- 2099-11-15 09:00 IST MLP recap formula sheet\n")
        self.assertTrue(any("on the day of its exam" in p for p in probs), probs)

    def test_linked_session_on_or_after_exam(self):
        probs, _ = check(PLAN + "- 2099-11-16 MLP revision (for iitm-mlp-quiz-2099-11-15)\n")
        self.assertTrue(any("on or after its exam iitm-mlp-quiz-2099-11-15" in p
                            for p in probs), probs)

    def test_revision_after_last_exam(self):
        probs, _ = check(PLAN + "- 2099-11-19 DBMS revision of everything\n")
        self.assertTrue(any("after DBMS's last exam" in p for p in probs), probs)

    def test_linked_id_counts_and_date_inside_id_is_ignored(self):
        plan = PLAN.replace("| 2099-11-09 | 18:00 | MLP | Practice: past quiz papers |",
                            "- 2099-11-09 practice for iitm-mlp-quiz-2099-11-15")
        probs, _ = check(plan)
        self.assertEqual(probs, [])

    def test_exams_outside_period_ignored(self):
        plan = PLAN.replace("Period: 2099-11-01 to 2099-11-20", "Period: 2099-11-01 to 2099-11-16")
        plan = plan.replace("- 2099-11-16 18:00 IST DBMS recap of SQL joins\n", "")
        probs, stats = check(plan)
        self.assertEqual(probs, [])
        self.assertEqual(stats["exams"], 1)

    def test_session_outside_period(self):
        probs, _ = check(PLAN + "- 2099-11-25 MLP reading\n")
        self.assertTrue(any("outside the plan period" in p for p in probs))


class Integrity(unittest.TestCase):
    def flagged(self, text):
        return spc.integrity_problems(text.splitlines())

    def test_forbidden_phrases_flagged(self):
        for line in ("Solve assignment 4 tonight", "solve the week 5 graded assignment",
                     "Get answers to quiz 2", "Share the quiz answers", "find the answer key",
                     "Submit GA 6 on the portal", "submitting the OPPE",
                     "draft the assignment for Lakshya", "solutions to the graded assignment",
                     "take the quiz for him", "log in on his behalf"):
            self.assertTrue(self.flagged(line), line)

    def test_planning_language_allowed(self):
        for line in ("Revision: weeks 1-4", "Practice: solve PYQs from 2023, self-marked",
                     "GA 6 due 2099-11-14 23:59 IST", "Lakshya submitted GA 5 on time",
                     "Submission window opens 2099-11-01", "solve practice assignment set 3",
                     "Mock quiz, timed, then review own mistakes"):
            self.assertFalse(self.flagged(line), line)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(HERE / "study_plan_check.py"), *args],
                              capture_output=True, text=True, timeout=60)

    def test_help(self):
        proc = self.run_tool("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--find-calendar", proc.stdout)

    def test_explicit_calendar_pass_and_fail(self):
        (self.dir / "cal.json").write_text(json.dumps(CAL))
        plan = self.dir / "study-plan.md"
        plan.write_text(PLAN)
        proc = self.run_tool(str(plan), "--calendar", str(self.dir / "cal.json"))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("study_plan_check: OK", proc.stdout)
        plan.write_text(PLAN + "- 2099-11-12 submit the MLP assignment\n")
        proc = self.run_tool(str(plan), "--calendar", str(self.dir / "cal.json"))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
        self.assertIn("coursework-solving", proc.stderr)

    def test_find_calendar_and_shipped_template(self):
        shutil.copy(TEMPLATES / "sample-calendar.json", self.dir / "calendar.json")
        shutil.copy(TEMPLATES / "term-plan.md", self.dir / "term-plan.md")
        proc = self.run_tool(str(self.dir / "term-plan.md"), "--find-calendar")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("3 exam(s) in period", proc.stdout)

    def test_find_calendar_missing(self):
        plan = self.dir / "a" / "b" / "c" / "plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(PLAN)
        proc = self.run_tool(str(plan), "--find-calendar")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no calendar.json", proc.stderr)

    def test_malformed_calendar_fails(self):
        (self.dir / "calendar.json").write_text('{"entries": [{"course": "MLP"}]}')
        plan = self.dir / "plan.md"
        plan.write_text(PLAN)
        proc = self.run_tool(str(plan), "--find-calendar")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing", proc.stderr)

    def test_integrity_only_on_templates(self):
        for name in ("term-plan.md", "weekly-review.md"):
            proc = self.run_tool(str(TEMPLATES / name), "--integrity-only")
            self.assertEqual(proc.returncode, 0, (name, proc.stdout, proc.stderr))
        bad = self.dir / "weekly-review.md"
        bad.write_text("# Week\nThe answers to quiz 1 are below.\n")
        proc = self.run_tool(str(bad), "--integrity-only")
        self.assertEqual(proc.returncode, 1)

    def test_missing_plan(self):
        proc = self.run_tool(str(self.dir / "none.md"), "--integrity-only")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
