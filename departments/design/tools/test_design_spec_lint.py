"""Tests for design_spec_lint.py. Specs are written to temp dirs."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design_spec_lint as dsl  # noqa: E402

GOOD_SPEC = """# DESIGN_SPEC - Aarambh 2026 dignitary invitation (Lane A)

DRAFT FOR CEO REVIEW. Lane A output; Lane B builds from this file and nothing else.

## Concept
A formal invitation from The SCRIET Family to a dignitary for Aarambh, the orientation programme.
Typography carries the ceremony; the official CCSU crest is the only emblem.
Night-blue field, one gold, generous air: engraved stationery, not a poster.

## Palette (exact hex)
- Field: #101f3d, full bleed, no gradient.
- Body and venue text: #f4e2aa on #101f3d.
- Display gold, large lines only: #e6c574 on #101f3d (large).
- Hairline rules: #bd9141 at 1 px; decorative, never used for text.

## Typography
- Dignitary line: Cormorant Garamond Bold, 72 px, letter-spacing 0.02em.
- "The SCRIET Family": Cormorant Garamond SemiBold, 40 px caps, tracking 0.18em.
- Date, time, venue: Source Sans 3 Regular, 34 px, line height 1.4.
- Smallest text on the 1080x1920 master is 30 px so it survives the 720p WhatsApp copy.

## Layering order (bottom to top)
1. Field #101f3d
2. Hairline frame inset 64 px
3. Official CCSU crest PNG, untouched, 280 px tall
4. Text column
5. Fade-to-black overlay used only in the last second

## Movement arc
- 0.0-1.0 s: field fades up from black.
- 1.0-2.5 s: crest fades in at full size, no scale change.
- 2.5-6.0 s: text lines fade up one block at a time, 0.4 s each, 8 px upward drift.
- 6.0-9.0 s: hold the complete card, still, for 3 s.
- 9.0-10.0 s: gentle fade to black. No blinking, no shimmer, no zoom at the end.

## Audio direction
Solo piano bed, unhurried. Fade in over 1.0 s, fade out over the final 1.0 s with the
picture. Peaks below -1 dBFS, mean near -20 dB so it sits under a phone speaker's limit.

## Do not reuse
- The AI-generated crest rejected on 20 Oct 2026.
- Ornate corner flourishes and side medallions from the alumni card.
- Any Code.SCRIET wordmark or logo.
- The shimmer sweep and sparkle particles from the earlier envelope video.
"""


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = dsl.main(args)
    return code, out.getvalue(), err.getvalue()


class Lint(unittest.TestCase):
    def test_good_spec_passes(self):
        self.assertEqual(dsl.lint(GOOD_SPEC), [])

    def test_missing_section(self):
        spec = GOOD_SPEC.replace("## Audio direction", "## Notes")
        self.assertIn("missing section: audio direction", dsl.lint(spec))

    def test_palette_needs_exact_hex(self):
        spec = GOOD_SPEC.replace("#bd9141", "#b94")
        self.assertTrue(any("shorthand" in p for p in dsl.lint(spec)))

    def test_too_many_colours(self):
        extra = "\n".join(f"- accent {i}: #{i:02d}{i:02d}{i:02d}" for i in range(10, 16))
        spec = GOOD_SPEC.replace("## Typography", extra + "\n\n## Typography")
        self.assertTrue(any("distinct colours" in p for p in dsl.lint(spec)))

    def test_failing_contrast_pair(self):
        spec = GOOD_SPEC.replace("#f4e2aa on #101f3d", "#3a4a6a on #101f3d")
        self.assertTrue(any("below the 4.5:1" in p for p in dsl.lint(spec)))

    def test_palette_without_text_pair(self):
        spec = GOOD_SPEC.replace(" on #101f3d", "")
        self.assertTrue(any("no text pair" in p for p in dsl.lint(spec)))

    def test_typography_needs_size(self):
        spec = GOOD_SPEC.replace(", 72 px", "").replace(", 40 px", "").replace(", 34 px", "")
        spec = spec.replace("is 30 px", "is small")
        self.assertIn("typography gives no size (px, pt or rem)", dsl.lint(spec))

    def test_layering_needs_order(self):
        start = GOOD_SPEC.index("1. Field")
        end = GOOD_SPEC.index("## Movement")
        spec = GOOD_SPEC[:start] + "Text over the field, nothing else to say here.\n\n" + \
            GOOD_SPEC[end:]
        self.assertTrue(any("layering order" in p for p in dsl.lint(spec)))

    def test_movement_needs_hold(self):
        spec = GOOD_SPEC.replace("hold the complete card, still, for 3 s.",
                                 "the complete card stays for 3 s.")
        self.assertTrue(any("closing frame is held" in p for p in dsl.lint(spec)))

    def test_static_piece_needs_no_timings(self):
        start = GOOD_SPEC.index("- 0.0-1.0 s")
        end = GOOD_SPEC.index("## Audio direction")
        spec = GOOD_SPEC[:start] + "Static card: no motion, a single still frame.\n\n" + \
            GOOD_SPEC[end:]
        self.assertEqual(dsl.lint(spec), [])

    def test_blinking_is_banned_but_negation_is_fine(self):
        spec = GOOD_SPEC.replace("8 px upward drift.", "8 px upward drift, venue line blinks twice.")
        self.assertTrue(any("blinking" in p for p in dsl.lint(spec)))
        self.assertEqual(dsl.lint(GOOD_SPEC), [])  # contains "No blinking"

    def test_generated_crest_is_rejected(self):
        spec = GOOD_SPEC.replace("3. Official CCSU crest PNG, untouched, 280 px tall",
                                 "3. Crest redrawn as a vector, 280 px tall")
        self.assertTrue(any("untouched official PNG" in p for p in dsl.lint(spec)))

    def test_crest_halo_is_rejected(self):
        spec = GOOD_SPEC.replace("1.0-2.5 s: crest fades in", "1.0-2.5 s: crest with a soft halo fades in")
        self.assertTrue(any("untouched official PNG" in p for p in dsl.lint(spec)))

    def test_code_scriet_branding_on_aarambh(self):
        spec = GOOD_SPEC.replace("5. Fade-to-black", "5. Code.SCRIET wordmark in the footer\n6. Fade-to-black")
        self.assertTrue(any("no Code.SCRIET branding" in p for p in dsl.lint(spec)))

    def test_leftover_template_text(self):
        spec = GOOD_SPEC.replace("Solo piano bed", "[fill: music choice]")
        self.assertTrue(any("leftover template text" in p for p in dsl.lint(spec)))

    def test_shipped_template_is_not_buildable_until_filled(self):
        template = HERE.parent / "templates" / "DESIGN_SPEC.md"
        if not template.exists():
            self.skipTest("template not present next to tools/")
        problems = dsl.lint(template.read_text())
        self.assertTrue(any("leftover template text" in p for p in problems))
        sections = dsl.split_sections(template.read_text())
        for key in dsl.REQUIRED:
            self.assertIn(key, sections, f"template lacks the {key} heading")


class CommandLine(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "DESIGN_SPEC.md"
            good.write_text(GOOD_SPEC)
            self.assertEqual(run([str(good)])[0], 0)
            bad = Path(tmp) / "DESIGN_SPEC-v2.md"
            bad.write_text("# spec\n\n## Concept\nA nice invite.\n")
            code, _, err = run([str(bad)])
            self.assertEqual(code, 1)
            self.assertEqual(len(err.strip().splitlines()), 1)
            self.assertEqual(run([str(Path(tmp) / "missing.md")])[0], 2)


if __name__ == "__main__":
    unittest.main()
