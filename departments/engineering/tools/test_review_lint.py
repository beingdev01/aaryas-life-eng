"""Tests for review_lint.py. Temp files only."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_lint as rl  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "review-report.md"

LIST_REVIEW = """# Review: lanewatch

- Reviewer: quality-2
- Builder: bulk-3

**Verdict:** REVISE

## Findings

1. **high** `tools/lanewatch/lanewatch.py:142` - the age check uses `>` so a process exactly at
   the threshold is never reported. Fix: compare with `>=` and add a boundary test.
2. medium tools/lanewatch/lanewatch.py:77 - classification scans all of stdout, so a lane that
   merely quotes "Free usage limit reached" is marked quota-exhausted.
   Fix: classify from stderr and error events only, as engine/lanes.py does.

## Notes
Nothing else.
"""


class ReviewLintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_lint(self, text, name="part-review.md"):
        path = self.dir / name
        path.write_text(text)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = rl.main([str(path)])
        return rc, out.getvalue(), err.getvalue()

    def test_shipped_template_passes(self):
        rc, out, err = self.run_lint(TEMPLATE.read_text())
        self.assertEqual(rc, 0, out)
        self.assertIn("3 finding(s)", out)

    def test_list_style_review_passes(self):
        rc, out, _ = self.run_lint(LIST_REVIEW)
        self.assertEqual(rc, 0, out)
        self.assertIn("verdict REVISE, 2 finding(s)", out)

    def test_approve_with_no_findings_is_valid(self):
        rc, out, _ = self.run_lint("# Review\n\nVerdict: APPROVE\n\n## Findings\n\nNone.\n")
        self.assertEqual(rc, 0, out)
        rc, out, _ = self.run_lint("# Review\n\nVerdict: APPROVE\n\nAll checks re-run, clean.\n")
        self.assertEqual(rc, 0, out)

    def test_missing_verdict_fails(self):
        rc, out, err = self.run_lint(LIST_REVIEW.replace("**Verdict:** REVISE", ""))
        self.assertEqual(rc, 1)
        self.assertIn("no verdict", out)
        self.assertTrue(err.startswith("review_lint:"))

    def test_conflicting_verdicts_fail(self):
        rc, out, _ = self.run_lint(LIST_REVIEW + "\nFinal verdict: APPROVE\n")
        self.assertEqual(rc, 1)
        self.assertIn("conflicting verdicts", out)

    def test_vague_finding_without_location_fails(self):
        text = LIST_REVIEW.replace("`tools/lanewatch/lanewatch.py:142`", "the age check")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("finding 1: vague", out)

    def test_location_without_line_fails(self):
        text = LIST_REVIEW.replace("lanewatch.py:142", "lanewatch.py")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("vague", out)

    def test_finding_without_fix_or_severity_fails(self):
        text = LIST_REVIEW.replace("Fix: compare with `>=` and add a boundary test.", "")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("finding 1: no concrete fix", out)
        text = LIST_REVIEW.replace("medium tools", "tools")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("finding 2: no severity", out)

    def test_fix_ups_word_is_not_a_fix(self):
        text = ("# Review\n\nVerdict: REVISE\n\n## Findings\n\n"
                "- high a/b.py:3 - the retry loop needs fix-ups before merge because it never ends\n")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("no concrete fix", out)

    def test_approve_with_high_finding_fails(self):
        rc, out, _ = self.run_lint(LIST_REVIEW.replace("REVISE", "APPROVE"))
        self.assertEqual(rc, 1)
        self.assertIn("APPROVE with 1 critical/high", out)

    def test_revise_without_findings_fails(self):
        rc, out, _ = self.run_lint("# Review\n\nVerdict: REVISE\n\nNeeds more work overall.\n")
        self.assertEqual(rc, 1)
        self.assertIn("REVISE with no findings", out)

    def test_self_review_fails(self):
        rc, out, _ = self.run_lint(LIST_REVIEW.replace("Builder: bulk-3", "Builder: quality-2"))
        self.assertEqual(rc, 1)
        self.assertIn("never reviews its own build", out)

    def test_table_with_file_and_line_columns(self):
        text = ("# Review\n\nVerdict: REVISE\n\n## Findings\n\n"
                "| severity | file | line | problem | fix |\n|---|---|---|---|---|\n"
                "| high | engine/gate.py | 41 | second wait can raise and abort the gate | "
                "wrap proc.wait in try/except, record rc 124 |\n")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 0, out)

    def test_engine_json_review_shape(self):
        good = {"verdict": "REVISE", "findings": [
            {"severity": "high", "location": "engine/gate.py:41",
             "problem": "second TimeoutExpired propagates and aborts the gate",
             "fix": "wrap proc.wait(timeout=10) in try/except and set rc=124"}]}
        rc, out, _ = self.run_lint(json.dumps(good), "part-review.json")
        self.assertEqual(rc, 0, out)
        good["findings"][0]["location"] = "engine/gate.py"
        rc, out, _ = self.run_lint(json.dumps(good), "part-review.json")
        self.assertEqual(rc, 1)
        rc, out, _ = self.run_lint(json.dumps({"verdict": "APPROVE", "findings": []}), "r.json")
        self.assertEqual(rc, 0, out)

    def test_old_style_review_without_lines_fails(self):
        text = ("# quality-2 review\n\n**Verdict:** APPROVE with non-blocking findings\n\n"
                "## Findings\n- **M-1 (medium) gate.run_check timeout path:** after os.killpg, "
                "calls proc.wait with no outer guard. Fix: wrap in try/except and set rc=124.\n")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("vague", out)

    def test_unparseable_json_exits_two(self):
        rc, _, err = self.run_lint("{not json", "x-review.json")
        self.assertEqual(rc, 2)
        self.assertIn("does not parse", err)


if __name__ == "__main__":
    unittest.main()
