"""Tests for report_lint.py. Temp files only."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_lint as rl  # noqa: E402

GOOD = """# Incident report: club-api down, 2026-10-31 14:05 IST

- Severity: SEV-2 (members cannot sign in on https://codescriet.dev)
- Detected by: monitor/alerts.log line `2026-10-31T08:35:01+00:00 club-api: ok -> down`
- Status: open, waiting on the CEO

## What happened
The platform monitor flipped club-api to down at 08:35 UTC. `systemctl status club-api`
shows the unit in failed state after an out-of-memory kill. Six hung opencode lane
processes held 2.6 GiB at the time.

## Commands for the CEO

```
journalctl -u club-api -n 100 --no-pager
sudo systemctl restart club-api
curl -sS -o /dev/null -w '%{http_code}\\n' https://api.codescriet.dev/health
```
"""


class ReportLintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "incident-report.md"

    def tearDown(self):
        self.tmp.cleanup()

    def run_lint(self, text, *extra):
        self.path.write_text(text)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = rl.main([str(self.path), *extra])
        return rc, out.getvalue(), err.getvalue()

    def test_good_report_passes(self):
        rc, out, err = self.run_lint(GOOD)
        self.assertEqual(rc, 0, out)
        self.assertEqual(err, "")

    def test_missing_ceo_section_fails(self):
        text = GOOD.split("## Commands for the CEO")[0] + "\nMore detail here to pass size.\n" * 5
        rc, out, err = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("no 'Commands for the CEO' section", out)
        self.assertTrue(err.startswith("report_lint:"))

    def test_empty_ceo_section_fails(self):
        text = GOOD.split("## Commands for the CEO")[0] + "## Commands for the CEO\n\n## Notes\nnone\n"
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("section is empty", out)

    def test_ceo_section_without_commands_fails(self):
        text = (GOOD.split("## Commands for the CEO")[0]
                + "## Commands for the CEO\n\nPlease look into it when you can.\n")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 1)
        self.assertIn("has no command", out)

    def test_explicit_no_action_passes(self):
        text = (GOOD.split("## Commands for the CEO")[0]
                + "## Commands for the CEO\n\nNo commands needed: every threshold is within limits.\n")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 0, out)

    def test_trivial_report_fails(self):
        rc, out, _ = self.run_lint("# Report\n\n## Commands for the CEO\n`df -h`\n")
        self.assertEqual(rc, 1)
        self.assertIn("bytes", out)
        self.assertIn("lines of content", out)

    def test_placeholders_fail(self):
        for marker in ("TODO: fill this", "TBD", "<fill in the cause>", "{{service}}"):
            rc, out, _ = self.run_lint(GOOD.replace("Status: open", f"Status: {marker}"))
            self.assertEqual(rc, 1, marker)
            self.assertIn("placeholder", out)

    def test_credentials_fail(self):
        leaks = ["Authorization: Bearer abcdefghijklmnop1234",
                 "postgres://admin:hunter22secret@db.example/x",
                 "lakshya $2a$14$Ohw.7c9Xu8ZQDUuajVV1NOSaNBa.hzcj7uVvzmC3Sa46mXDo9h4y2",
                 "password = s3cretvalue99"]
        for leak in leaks:
            rc, out, _ = self.run_lint(GOOD.replace("Status: open", leak))
            self.assertEqual(rc, 1, leak)
            self.assertIn("[REDACTED]", out)

    def test_redacted_values_pass(self):
        rc, out, _ = self.run_lint(GOOD.replace("Status: open", "Authorization: Bearer [REDACTED]"))
        self.assertEqual(rc, 0, out)

    def test_subsection_heading_inside_ceo_section_is_kept(self):
        text = (GOOD.split("## Commands for the CEO")[0] + "## Commands for the CEO\n\n"
                "### disk (breach)\n\n```\ndf -h /\n```\n")
        rc, out, _ = self.run_lint(text)
        self.assertEqual(rc, 0, out)

    def test_unfilled_shipped_templates_fail(self):
        templates = Path(__file__).resolve().parent.parent / "templates"
        for name in ("incident-report.md", "health-report.md", "subdomain-request.md"):
            rc, out, _ = self.run_lint((templates / name).read_text())
            self.assertEqual(rc, 1, name)
            self.assertIn("placeholder", out, name)

    def test_unreadable_exits_two(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = rl.main([str(self.path.parent / "missing.md")])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
