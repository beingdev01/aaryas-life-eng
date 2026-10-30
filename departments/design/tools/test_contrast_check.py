"""Tests for contrast_check.py. Temp dirs only; no network."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contrast_check as cc  # noqa: E402


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cc.main(args)
    return code, out.getvalue(), err.getvalue()


class RatioMaths(unittest.TestCase):
    def test_black_on_white_is_21(self):
        r = cc.contrast_ratio(cc.parse_colour("#000"), cc.parse_colour("#ffffff"))
        self.assertAlmostEqual(r, 21.0, places=2)

    def test_known_aa_boundary(self):
        # #767676 is the lightest grey that passes 4.5:1 on white; #777777 fails.
        self.assertGreaterEqual(cc.contrast_ratio(cc.parse_colour("#767676"),
                                                  cc.parse_colour("#ffffff")), 4.5)
        self.assertLess(cc.contrast_ratio(cc.parse_colour("#777777"),
                                          cc.parse_colour("#ffffff")), 4.5)

    def test_approved_certificate_pairs(self):
        navy, paper = cc.parse_colour("#0f2a4a"), cc.parse_colour("#f7f4ec")
        self.assertGreater(cc.contrast_ratio(navy, paper), 12)
        gold_text = cc.parse_colour("#7a6114")
        self.assertGreater(cc.contrast_ratio(gold_text, paper), 4.5)
        gold_rule = cc.parse_colour("#c9a227")
        self.assertLess(cc.contrast_ratio(gold_rule, paper), 3.0)

    def test_alpha_is_composited(self):
        faint = cc.parse_colour("rgba(15, 42, 74, 0.2)")
        self.assertLess(cc.contrast_ratio(faint, cc.parse_colour("#f7f4ec")), 2.0)

    def test_parse_formats(self):
        self.assertEqual(cc.parse_colour("#abc")[:3], (170.0, 187.0, 204.0))
        self.assertEqual(cc.parse_colour("rgb(255 0 0 / 50%)")[3], 0.5)
        self.assertEqual(cc.parse_colour("white")[:3], (255.0, 255.0, 255.0))
        self.assertEqual(cc.parse_colour("0f2a4a", allow_bare_hex=True)[:3],
                         (15.0, 42.0, 74.0))
        with self.assertRaises(cc.ContrastError):
            cc.parse_colour("hsl(10, 50%, 50%)")


class CommandLinePairs(unittest.TestCase):
    def test_passing_pair_exit_0(self):
        code, out, _ = run(["0f2a4a", "f7f4ec"])
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_failing_pair_exit_1_with_reason(self):
        code, _, err = run(["#c9a227", "#f7f4ec"])
        self.assertEqual(code, 1)
        self.assertIn("below AA", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_large_flag_lowers_threshold(self):
        # about 3.5:1: fails as body text, passes as large text
        self.assertEqual(run(["#8a8a8a", "#ffffff"])[0], 1)
        self.assertEqual(run(["--large", "#8a8a8a", "#ffffff"])[0], 0)

    def test_odd_colour_count_exit_2(self):
        self.assertEqual(run(["#000000"])[0], 2)


HTML = """<!doctype html><html><head><title>Invite</title>
<link rel="stylesheet" href="extra.css">
<link rel="stylesheet" href="https://fonts.example.com/remote.css">
<style>
:root { --navy: #101f3d; --gold: #e6c574; --paper: #f7f4ec; }
body { background: #8a8a8a; color: var(--gold); margin: 0; }
.card { background: var(--navy); font-size: 20px; }
.title { font-size: 3em; color: var(--gold); }
.venue { font-size: 18px; color: #f4e2aa; }
.ornament { color: #3a3a3a; /* contrast: ignore */ }
.script { font-size: 120px; background: linear-gradient(90deg, #e6c574, #f4e2aa);
          -webkit-background-clip: text; background-clip: text; color: transparent; }
.title:hover { color: #000000; }
.card > .badge { background: url(data:image/png;base64,AAAA;BBBB) no-repeat; color: #ffffff; }
@keyframes rise { 0% { color: #101f3d; } 100% { color: #e6c574; } }
@font-face { font-family: X; src: url(x.woff2); }
</style></head><body>
<main class="card">
  <p class="script">You are invited</p>
  <h1 class="title">The SCRIET Family</h1>
  <p class="venue">Netaji Subhash Chandra Bose Auditorium</p>
  <p class="time">10:00 AM onwards</p>
  <span class="badge">NAAC A++</span>
  <div class="ornament">ornament glyphs</div>
  <svg aria-hidden="true"><text fill="#202020">watermark</text></svg>
  <p style="color: #f4e2aa; font-size: 16px">27 October 2026</p>
  <p class="note">small print</p>
</main>
</body></html>"""


class FileExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, body):
        p = self.dir / name
        p.write_text(body)
        return p

    def labels(self, checks):
        return " | ".join(c["label"] for c in checks)

    def test_clean_invite_passes(self):
        self.write("extra.css", ".time { color: #f4e2aa; font-size: 40px; } "
                                ".note { color: #ddc894; }")
        html = self.write("index.html", HTML)
        code, out, err = run([str(html)])
        self.assertEqual(code, 0, out + err)
        self.assertIn("p.time", out)          # linked local stylesheet was read
        self.assertNotIn("ornament", out)     # ignore directive honoured
        self.assertNotIn("watermark", out)    # aria-hidden decoration skipped
        self.assertNotIn("Invite", out)       # <title> is not rendered text
        self.assertIn("p.script", out)        # gradient text checked stop by stop
        self.assertNotIn("#8a8a8a", out)      # text paired with the card, not the body

    def test_text_is_paired_with_nearest_painted_background(self):
        self.write("extra.css", "")
        checks = cc.checks_from_file(self.write("index.html", HTML))
        venue = [c for c in checks if c["label"].startswith("p.venue")]
        self.assertEqual(venue[0]["bg"], "#101f3d")
        title = [c for c in checks if c["label"].startswith("h1.title")][0]
        self.assertTrue(title["large"])       # 3em of a 20px parent = 60px
        badge = [c for c in checks if c["label"].startswith("span.badge")][0]
        self.assertEqual(badge["fg"], "#ffffff")  # child combinator matched

    def test_faint_small_text_fails(self):
        self.write("extra.css", ".note { color: rgba(230,197,116,.35); font-size: 14px; }")
        html = self.write("index.html", HTML)
        code, out, err = run([str(html)])
        self.assertEqual(code, 1)
        self.assertIn("p.note", err)

    def test_inherited_colour_from_body_on_grey_fails(self):
        html = self.write("plain.html", "<html><body style='background:#8a8a8a;color:#e6c574'>"
                                        "<p>The SCRIET Family</p></body></html>")
        self.assertEqual(run([str(html)])[0], 1)

    def test_bg_directive_inside_html(self):
        html = self.write("photo.html",
                          "<html><head><style>.over { color: #ffffff; "
                          "/* contrast: bg #101f3d */ }</style></head>"
                          "<body><p class='over'>On the photo</p></body></html>")
        self.assertEqual(run([str(html)])[0], 0)

    def test_large_text_detected_from_font_size(self):
        css = self.write("a.css", "body{background:#ffffff} .h{color:#8a8a8a;font-size:32px}"
                                  " .p{color:#8a8a8a;font-size:12px}")
        checks = cc.checks_from_file(css)
        by = {c["label"]: c for c in checks}
        self.assertTrue(by[".h"]["ok"])
        self.assertFalse(by[".p"]["ok"])

    def test_bg_directive_overrides_page(self):
        css = self.write("b.css", "body{background:#ffffff} "
                                  ".on-navy{color:#e6c574; /* contrast: bg #101f3d */}")
        self.assertTrue(all(c["ok"] for c in cc.checks_from_file(css)))

    def test_file_with_no_text_colours_exit_2(self):
        css = self.write("c.css", ".x { margin: 0; }")
        self.assertEqual(run([str(css)])[0], 2)

    def test_missing_file_exit_2(self):
        self.assertEqual(run([str(self.dir / "nope.html")])[0], 2)


if __name__ == "__main__":
    unittest.main()
