#!/usr/bin/env python3
"""Unit tests for the outreach draft gate. Stdlib unittest, temp dirs only."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import email_gate  # noqa: E402

GOOD = """First-touch draft (draft-and-hold) for Fictional Sponsor Corp.

```
From: "Code.SCRIET" <outreach@codescriet.dev>
To: partnerships@example.test (published on example.test/contact)
Subject: A data-modelling workshop with Code.SCRIET

Hi team,

I'm Lakshya Pandey, Technical Head at Code.SCRIET (https://codescriet.dev), the coding club of SCRIET, CCSU Meerut.

Our members ship real projects and would like one co-branded session, your branding on the material and certificates and the session listed on https://codescriet.dev.

Would you be open to a 15-minute call?

Best,
Lakshya Pandey, Technical Head, Code.SCRIET
https://codescriet.dev
```
"""


def write(text):
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class EmailGateTest(unittest.TestCase):
    def _errs(self, text):
        p = write(text)
        try:
            return email_gate.run(p, 200)
        finally:
            os.remove(p)

    def test_good_draft_passes(self):
        self.assertEqual(self._errs(GOOD), [])

    def test_via_form_passes(self):
        t = GOOD.replace("To: partnerships@example.test (published on example.test/contact)",
                         "To: via form - https://example.test/contact")
        self.assertEqual(self._errs(t), [])

    def test_bare_url_fails(self):
        t = GOOD.replace("https://codescriet.dev", "codescriet.dev")
        self.assertTrue(any("bare or non-https" in e for e in self._errs(t)))

    def test_invented_free_mail_contact_fails(self):
        t = GOOD.replace("partnerships@example.test (published on example.test/contact)",
                         "some.persona@gmail.com")
        self.assertTrue(any("personal / free" in e for e in self._errs(t)))

    def test_missing_from_fails(self):
        t = GOOD.replace('<outreach@codescriet.dev>', '<x@example.test>')
        self.assertTrue(any("missing sender" in e for e in self._errs(t)))

    def test_send_claim_fails(self):
        t = GOOD.replace("Would you be open to a 15-minute call?",
                         "I have sent this to them already.")
        self.assertTrue(any("claims a send" in e for e in self._errs(t)))

    def test_emoji_fails(self):
        t = GOOD.replace("Hi team,", "Hi team \U0001F680,")
        self.assertTrue(any("emoji" in e for e in self._errs(t)))

    def test_hype_fails(self):
        t = GOOD.replace("one co-branded session", "one game-changer session")
        self.assertTrue(any("AI-hype" in e for e in self._errs(t)))

    def test_no_signature_fails(self):
        t = GOOD.replace("Best,\nLakshya Pandey, Technical Head, Code.SCRIET\nhttps://codescriet.dev",
                         "regards the club")
        self.assertTrue(any("signature" in e for e in self._errs(t)))

    def test_word_cap_fails(self):
        long_block = GOOD.replace("Would you be open to a 15-minute call?",
                                  " ".join(["please"] * 210))
        self.assertTrue(any("over the" in e for e in self._errs(long_block)))

    def test_no_draft_marker_fails(self):
        t = GOOD.replace("First-touch draft (draft-and-hold)", "First-touch note")
        self.assertTrue(any("DRAFT marker" in e for e in self._errs(t)))


if __name__ == "__main__":
    unittest.main()
