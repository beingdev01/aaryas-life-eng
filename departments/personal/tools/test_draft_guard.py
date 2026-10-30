"""Tests for draft_guard.py. Fixtures are written to temp dirs and use invented names."""

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import draft_guard as dg  # noqa: E402

GOOD = """DRAFT FOR CEO REVIEW

To (for you to send): Asha Verma
Occasion: 31 days since the last mail

Hi Asha,

Did the sabbatical planning ever settle? I have a free Sunday after the 8th if you want
to talk it through.

Ready to send when you are.
"""

GOOD_NUDGE = """DRAFT FOR CEO REVIEW

To (for you): yourself
Occasion: sleep nudge

A short walk before the 8pm session would help tonight. Nothing else needed.
"""

GOOD_REPORT = """# Sweep 2026-11-01

Checked: 4 records. Stale: 2. Occasions: 1.

| id | relationship | days since | draft |
|---|---|---|---|
| asha-verma | mentor | 31 | work/sweep-2026-11-01/draft-asha-verma-2026-11-01.md |
"""


def problems(text, **kw):
    return dg.check(text, **kw)


class MarkerTest(unittest.TestCase):
    def test_clean_draft_passes(self):
        self.assertEqual(problems(GOOD), [])

    def test_marker_must_be_line_one(self):
        moved = GOOD.replace("DRAFT FOR CEO REVIEW\n\n", "") + "\nDRAFT FOR CEO REVIEW\n"
        self.assertTrue(any("line 1" in p for p in problems(moved)))

    def test_lowercase_marker_fails(self):
        self.assertTrue(any("line 1" in p for p in problems(GOOD.lower())))


class SendClaimTest(unittest.TestCase):
    def test_completed_send_fails(self):
        bad = GOOD + "\nI have sent this to Asha already.\n"
        self.assertTrue(any("send-claim" in p for p in problems(bad)))

    def test_already_emailed_fails(self):
        bad = GOOD + "\nAlready emailed the advisor too.\n"
        self.assertTrue(any("send-claim" in p for p in problems(bad)))

    def test_delivery_promise_fails(self):
        bad = GOOD + "\nYou will receive it shortly.\n"
        self.assertTrue(any("promises delivery" in p for p in problems(bad)))

    def test_send_instruction_fails(self):
        bad = GOOD + "\nSend this to her tonight.\n"
        self.assertTrue(any("send instruction" in p for p in problems(bad)))

    def test_auto_send_fails(self):
        bad = GOOD + "\nAuto-send on Sunday.\n"
        self.assertTrue(any("automated send" in p for p in problems(bad)))

    def test_ready_to_send_is_allowed(self):
        self.assertEqual([p for p in problems(GOOD) if "send" in p], [])


class LeakTest(unittest.TestCase):
    def test_email_leak_fails(self):
        bad = GOOD + "\nHer address is asha.verma@example.test if you need it.\n"
        self.assertTrue(any("email address" in p for p in problems(bad)))

    def test_phone_leak_fails(self):
        bad = GOOD + "\nReach her on 9999900001.\n"
        self.assertTrue(any("phone number" in p for p in problems(bad)))

    def test_grouped_phone_leak_fails(self):
        bad = GOOD + "\nReach her on +91 99999-00001.\n"
        self.assertTrue(any("phone number" in p for p in problems(bad)))

    def test_allow_contact_permits_email(self):
        bad = GOOD + "\nHer address is asha.verma@example.test if you need it.\n"
        self.assertEqual([p for p in problems(bad, allow_contact=True)
                          if "email" in p], [])

    def test_pin_code_fails(self):
        bad = GOOD + "\nPin code 110001 for the office.\n"
        self.assertTrue(any("postal address" in p for p in problems(bad)))


class PlaceholderTest(unittest.TestCase):
    def test_bracket_placeholder(self):
        bad = GOOD.replace("Asha Verma", "[PERSON NAME]")
        self.assertTrue(any("placeholder" in p for p in problems(bad)))

    def test_curly_token(self):
        bad = GOOD.replace("the 8th", "{the_day}")
        self.assertTrue(any("template token" in p for p in problems(bad)))

    def test_tbd(self):
        bad = GOOD.replace("Sunday after the 8th", "Sunday, TBD")
        self.assertTrue(any("leftover" in p for p in problems(bad)))

    def test_unfilled_iso_date(self):
        bad = GOOD.replace("Occasion: 31 days", "Occasion: YYYY-MM-DD")
        self.assertTrue(any("unfilled date" in p for p in problems(bad)))


class StyleTest(unittest.TestCase):
    def test_emoji_fails(self):
        bad = GOOD.replace("Ready to send", "Ready to send \U0001f642")
        self.assertTrue(any("decorative" in p for p in problems(bad)))

    def test_bullet_dot_fails(self):
        bad = GOOD + "\n• follow up next month\n"
        self.assertTrue(any("decorative" in p for p in problems(bad)))

    def test_template_greeting_fails(self):
        bad = GOOD.replace("Hi Asha,", "Hi,\n\nI hope this message finds you well.")
        self.assertTrue(any("template filler greeting" in p for p in problems(bad)))

    def test_just_checking_in_fails(self):
        bad = GOOD.replace("Did the sabbatical", "Just checking in - did the sabbatical")
        self.assertTrue(any("template filler" in p for p in problems(bad)))

    def test_double_exclaim_fails(self):
        bad = GOOD.replace("when you are.", "when you are!!")
        self.assertTrue(any("exclamation" in p for p in problems(bad)))


class ToneTest(unittest.TestCase):
    def test_gentle_nudge_passes(self):
        self.assertEqual(problems(GOOD_NUDGE, tone="gentle", max_words=120), [])

    def test_guilt_language_fails_gentle(self):
        bad = GOOD_NUDGE + "\nYou skipped the walk again.\n"
        self.assertTrue(any("gentle tone" in p for p in problems(bad, tone="gentle")))

    def test_verdict_language_fails_gentle(self):
        bad = GOOD_NUDGE + "\nThis sleep is a failure.\n"
        self.assertTrue(any("gentle tone" in p for p in problems(bad, tone="gentle")))

    def test_guilt_is_allowed_in_a_draft(self):
        bad = GOOD + "\nYou skipped it again.\n"
        self.assertEqual([p for p in problems(bad) if "gentle" in p], [])


class ReportModeTest(unittest.TestCase):
    def test_report_head_passes(self):
        self.assertEqual(problems(GOOD_REPORT, max_words=1200, is_report=True), [])

    def test_report_needs_its_head(self):
        self.assertTrue(any("must open" in p
                            for p in problems("Stale: 2\n", is_report=True)))

    def test_report_mode_does_not_require_draft_marker(self):
        self.assertEqual([p for p in problems(GOOD_REPORT, is_report=True) if "line 1" in p], [])

    def test_draft_marker_still_required_without_report(self):
        self.assertTrue(any("line 1" in p for p in problems(GOOD_REPORT)))


class LimitsTest(unittest.TestCase):
    def test_over_word_limit_fails(self):
        long_text = GOOD + "\n" + ("one more line of text here. " * 60)
        self.assertTrue(any("words, limit" in p for p in problems(long_text, max_words=200)))

    def test_marker_line_is_not_counted(self):
        self.assertLess(dg.count_words(GOOD), 80)

    def test_empty_after_marker_fails(self):
        self.assertTrue(any("no content" in p for p in problems("DRAFT FOR CEO REVIEW\n")))


class CliTest(unittest.TestCase):
    def write(self, text, name="draft-x.md"):
        fd = tempfile.TemporaryDirectory()
        self.addCleanup(fd.cleanup)
        path = Path(fd.name) / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_cli_passes_clean_file(self):
        self.assertEqual(dg.main([self.write(GOOD)]), 0)

    def test_cli_fails_dirty_file(self):
        self.assertEqual(dg.main([self.write(GOOD + "\nI have sent it.\n")]), 1)

    def test_cli_missing_file_is_two(self):
        self.assertEqual(dg.main(["/nonexistent/draft.md"]), 2)

    def test_cli_empty_file_is_two(self):
        self.assertEqual(dg.main([self.write("   ")]), 2)

    def test_cli_checks_every_file_and_fails_once(self):
        bad_one = self.write(GOOD + "\nI have sent it.\n")
        good_one = self.write(GOOD)
        self.assertEqual(dg.main([bad_one, good_one]), 1)

    def test_cli_report_flag(self):
        self.assertEqual(dg.main([self.write(GOOD_REPORT, "sweep-report.md"), "--report"]), 0)


if __name__ == "__main__":
    unittest.main()
