"""Tests for triage.py. Reports are written to temp dirs or passed in memory."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage  # noqa: E402


def run(args, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        if stdin is not None:
            with mock.patch.object(sys, "stdin", io.StringIO(stdin)):
                code = triage.main(args)
        else:
            code = triage.main(args)
    return code, out.getvalue(), err.getvalue()


class Classify(unittest.TestCase):
    def cls(self, text):
        return triage.classify(text)["class"]

    def test_site_bug(self):
        self.assertEqual(self.cls("The submit button on the playground page throws an error "
                                  "when I run my C++ code."), "site-bug")
        self.assertEqual(self.cls("Leaderboard page shows 404 since this morning."), "site-bug")
        self.assertEqual(self.cls("The judge has a memory leak and times out on test case 3."),
                         "site-bug")

    def test_account(self):
        self.assertEqual(self.cls("I can't log in, the OTP never arrives on my email."), "account")
        self.assertEqual(self.cls("Please change my username, I made a spelling mistake in "
                                  "my profile."), "account")

    def test_content(self):
        self.assertEqual(self.cls("There is a typo on the events page: 'Worskhop'."), "content")
        self.assertEqual(self.cls("The site shows the wrong date for the Git workshop, it "
                                  "should be 14 November."), "content")
        self.assertEqual(self.cls("Can you add the hackathon photos to the gallery?"), "content")

    def test_incident(self):
        for text in ("The website is down for everyone in the lab right now.",
                     "codescriet.dev was hacked, the home page shows someone else's text.",
                     "Our emails leaked: the members page shows every phone number.",
                     "Nobody can submit, the judge is returning 502.",
                     "The judge crashed during the contest, round 2 cannot continue.",
                     "Someone else logged into my account and changed my name.",
                     "Got a phishing mail with a fake login page for Code.SCRIET."):
            self.assertEqual(self.cls(text), "incident", text)

    def test_blank_after_run_is_a_bug(self):
        res = triage.classify("The playground is blank after I press Run, on my phone.")
        self.assertEqual(res["class"], "site-bug")
        self.assertGreaterEqual(res["scores"]["site-bug"], 3)

    def test_summary_is_clipped_on_a_word(self):
        long = "The submit button on the playground page " * 5
        res = triage.classify(long)
        self.assertLessEqual(len(res["summary"]), 84)
        self.assertTrue(res["summary"].endswith(" ..."))
        self.assertFalse(res["summary"][:-4].endswith(("subm", "playgr")))

    def test_other(self):
        self.assertEqual(self.cls("When is the next club meeting?"), "other")

    def test_routing_text(self):
        self.assertIn("engineering", triage.classify("Button broken")["route"])
        self.assertIn("CEO", triage.classify("site is down")["route"])
        self.assertIn("Never ask for a password",
                      triage.classify("password reset link expired")["club_action"])

    def test_redaction(self):
        res = triage.classify("Login fails for a.student@gmail.com, call 9876543210")
        self.assertNotIn("gmail", res["summary"])
        self.assertNotIn("9876543210", res["summary"])
        self.assertIn("(email removed)", res["summary"])


class CommandLine(unittest.TestCase):
    def test_bug_report_exit_0_with_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "report.txt"
            p.write_text("Playground page is blank on mobile Chrome after I press Run.\n")
            code, out, err = run([str(p)])
            self.assertEqual(code, 0, err)
            self.assertIn("class     : site-bug", out)
            self.assertIn("Title: Handoff from club-1: site bug", out)

    def test_incident_exit_3_loud(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "report.txt"
            p.write_text("The site is down, every student in the contest sees a 503.")
            code, out, err = run([str(p)])
            self.assertEqual(code, 3)
            self.assertIn("INCIDENT", err)
            self.assertIn("do not queue", err)
            self.assertEqual(len(err.strip().splitlines()), 1)

    def test_stdin_and_json(self):
        code, out, _ = run(["-", "--json"], stdin="Typo in the about page bio.")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["class"], "content")

    def test_empty_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "empty.txt"
            p.write_text("   \n")
            self.assertEqual(run([str(p)])[0], 2)
            self.assertEqual(run([str(Path(tmp) / "none.txt")])[0], 2)


if __name__ == "__main__":
    unittest.main()
