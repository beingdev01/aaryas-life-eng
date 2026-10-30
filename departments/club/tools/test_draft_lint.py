"""Tests for draft_lint.py. Drafts are written to temp dirs."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import draft_lint as dl  # noqa: E402

CLEAN = """DRAFT FOR CEO REVIEW

Subject: Git and GitHub workshop, Saturday 14 November

Hi everyone,

Code.SCRIET is running a hands-on Git and GitHub workshop on Saturday, 14 November 2026,
from 10:30 AM to 1:00 PM in the SCRIET computer lab.

You will set up Git, make your first repository, and open a pull request against a
practice project. Bring your college ID. Lab machines are ready, so no laptop is needed.

Register at https://codescriet.dev/events before Thursday, 12 November. Seats are
limited to the 40 lab machines. Certificates will be sent by email within a week to
everyone who attends the full session.

Questions can go to the Code.SCRIET team at team@codescriet.dev.

- [x] Date approved by the Teacher In-charge
- [ ] Seat count checked

See the [event page](https://codescriet.dev/events) for the agenda.

Technical Head, Code.SCRIET
"""


def lint_text(text, **kw):
    return dl.lint(text, **kw)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = dl.main(args)
    return code, out.getvalue(), err.getvalue()


class Lint(unittest.TestCase):
    def test_clean_draft_passes(self):
        self.assertEqual(lint_text(CLEAN), [])

    def test_marker_required(self):
        probs = lint_text(CLEAN.replace("DRAFT FOR CEO REVIEW", "Draft"))
        self.assertTrue(any("marker missing" in p for p in probs))

    def test_emoji_and_decorative_symbols(self):
        for ch in ("\U0001F389", "\u2728", "\u2192", "\u2605", "\u2022", "\u2714", "\u2122"):
            probs = lint_text(CLEAN.replace("Hi everyone,", f"Hi everyone {ch}"))
            self.assertTrue(any("U+" in p for p in probs), ch)

    def test_hindi_and_dashes_are_fine(self):
        text = CLEAN.replace("Hi everyone,", "Hi everyone \u2014 \u0906\u0930\u092e\u094d\u092d 2026,")
        self.assertEqual(lint_text(text), [])

    def test_placeholders(self):
        for token in ("[NAME]", "{{venue}}", "{date}", "<speaker name>", "TODO", "TBD",
                      "lorem", "XX:XX", "[fill: venue]", "insert time here"):
            probs = lint_text(CLEAN.replace("SCRIET computer lab", f"SCRIET computer lab {token}"))
            self.assertTrue(probs, token)

    def test_checkboxes_and_links_are_not_placeholders(self):
        self.assertEqual(lint_text(CLEAN), [])  # contains [x], [ ] and [text](url)

    def test_unconfirmed_dates(self):
        for phrase in ("Venue to be confirmed.", "Tentatively on Friday.",
                       "The date will be announced soon."):
            probs = lint_text(CLEAN.replace("Bring your college ID.", phrase))
            self.assertTrue(any("unconfirmed" in p for p in probs), phrase)

    def test_bare_or_http_site_fails(self):
        for bad in ("codescriet.dev/events", "http://codescriet.dev/events",
                    "www.codescriet.dev/events"):
            probs = lint_text(CLEAN.replace("https://codescriet.dev/events before", bad + " before"))
            self.assertTrue(any("https://" in p for p in probs), bad)
        probs = lint_text(CLEAN.replace("https://codescriet.dev/events before",
                                        "codescriet.dev/events before"))
        self.assertTrue(any("not 'codescriet.dev'" in p for p in probs), probs)

    def test_email_at_site_domain_is_fine(self):
        self.assertFalse(any("https://" in p for p in lint_text(CLEAN)))

    def test_send_claims(self):
        for claim in ("I have emailed the list.", "We posted this on the group.",
                      "The notice has been sent.", "I've already sent it.", "Sent: 10 Nov"):
            probs = lint_text(CLEAN + "\n" + claim + "\n")
            self.assertTrue(any("send or post claim" in p for p in probs), claim)

    def test_future_tense_is_fine(self):
        self.assertEqual(lint_text(CLEAN), [])  # "Certificates will be sent by email"

    def test_send_instructions(self):
        for line in ("Send this to the 2nd-year group.", "- Post the announcement at 9 AM",
                     "Please forward this to all members.", "Then auto-send the reminder."):
            probs = lint_text(CLEAN + "\n" + line + "\n")
            self.assertTrue(any("instruction" in p for p in probs), line)

    def test_private_data(self):
        for data in ("Call 9876543210.", "Call +91 98765 43210.", "Write to a.student@gmail.com.",
                     "ID 1234 5678 9012."):
            probs = lint_text(CLEAN.replace("Bring your college ID.", data))
            self.assertTrue(any("private data" in p for p in probs), data)
        self.assertEqual(lint_text(CLEAN.replace("Bring your college ID.", "Call 9876543210."),
                                   allow_contact=True), [])

    def test_hype(self):
        for hype in ("We are excited to announce", "Don't miss out", "a game-changing session",
                     "Register now!!"):
            probs = lint_text(CLEAN.replace("Hi everyone,", hype))
            self.assertTrue(any("hype" in p for p in probs), hype)

    def test_word_limit(self):
        self.assertEqual(lint_text(CLEAN, max_words=400), [])
        probs = lint_text(CLEAN, max_words=50)
        self.assertTrue(any("word limit" in p for p in probs))
        self.assertEqual(dl.word_count("DRAFT FOR CEO REVIEW\none two three"), 3)

    def test_shipped_templates_fail_until_filled(self):
        for name in ("announcement.md", "event-report.md"):
            tpl = HERE.parent / "templates" / name
            if not tpl.exists():
                self.skipTest("templates not present next to tools/")
            probs = lint_text(tpl.read_text(), max_words=2000)
            self.assertTrue(any("placeholder" in p for p in probs), name)
            self.assertFalse(any("marker missing" in p for p in probs), name)


class CommandLine(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "announcement-draft.md"
            good.write_text(CLEAN)
            code, out, _ = run([str(good), "--max-words", "300"])
            self.assertEqual(code, 0, out)
            bad = Path(tmp) / "reminder-draft.md"
            bad.write_text("Hi [NAME], see codescriet.dev")
            code, _, err = run([str(bad)])
            self.assertEqual(code, 1)
            self.assertEqual(len(err.strip().splitlines()), 1)
            empty = Path(tmp) / "empty-draft.md"
            empty.write_text("  \n")
            self.assertEqual(run([str(empty)])[0], 2)
            self.assertEqual(run([str(Path(tmp) / "missing.md")])[0], 2)


if __name__ == "__main__":
    unittest.main()
