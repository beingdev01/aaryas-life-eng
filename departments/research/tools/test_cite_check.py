"""Tests for cite_check.py. Run: python3 -m unittest discover -s tools -p 'test_*.py'"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cite_check  # noqa: E402

GOOD = """# Research Memo: Free lanes for overnight batch summaries

## Question
Which free model lane should run the nightly digest job?
Requested by: CEO
Decision this feeds: which lane the digest spec names.

## Findings

### Kilo gateway
**Facts:**
- Anonymous use is limited to 200 requests per hour per IP [1].
- The runner caps one invocation at 800 seconds, see `bin/kilo-runner.sh:61` and
  departments/research/runbook.md:52.
- Groq documents per-model limits on its rate-limit page https://console.groq.com/docs/rate-limits

**Inferences:**
- Three busy instances on one VM share one budget, so they exhaust it together.

INFERENCE: a nightly job at 03:00 IST will not compete with daytime lanes.

| Lane | Limit | Source |
|---|---|---|
| Kilo anonymous | 200 req/h/IP | [1] |
| Groq free | 1,000 req/day per model | [2] |

## Options & trade-offs
- Kilo: no key needed; shared budget [1].
- Groq: fast; needs a key the Owner holds [2].

## Recommendation
Use the Kilo lane for the digest, because it needs no new credential.

## Open questions
- Does the digest ever exceed 200 calls in an hour?

## Sources
[1] Kilo free tier limits - https://github.com/mvalentsev/awesome-free-ai-coding/blob/HEAD/providers/kilo-code.md
[2] Groq rate limits - https://console.groq.com/docs/rate-limits

RESULT: DONE
"""


def problems_of(text):
    return [msg for _, msg in cite_check.check_text(text)["problems"]]


class CiteCheckLogic(unittest.TestCase):
    def test_good_memo_passes(self):
        res = cite_check.check_text(GOOD)
        self.assertEqual(res["problems"], [])
        self.assertGreaterEqual(res["cited"], 5)
        self.assertGreaterEqual(res["inference"], 2)
        self.assertEqual(res["sources"], 2)

    def test_missing_sources_section_fails(self):
        text = GOOD.split("## Sources")[0]
        probs = problems_of(text)
        self.assertTrue(any("no Sources section" in p for p in probs))
        self.assertTrue(any("[1] is cited but not listed" in p for p in probs))

    def test_uncited_bullet_fails(self):
        text = GOOD.replace("**Inferences:**\n", "")
        probs = problems_of(text)
        self.assertTrue(any("no citation" in p and "Three busy" in p for p in probs), probs)

    def test_uncited_paragraph_fails(self):
        text = GOOD.replace("INFERENCE: a nightly job", "A nightly job")
        probs = problems_of(text)
        self.assertTrue(any("A nightly job" in p for p in probs), probs)

    def test_inline_inference_marker_accepted(self):
        text = GOOD.replace("INFERENCE: a nightly job", "A nightly job (inference) at")
        self.assertEqual(problems_of(text), [])

    def test_unresolved_reference_fails(self):
        text = GOOD.replace("200 requests per hour per IP [1]", "200 requests per hour [7]")
        probs = problems_of(text)
        self.assertTrue(any("[7] is cited but not listed" in p for p in probs), probs)

    def test_reference_ranges_resolve(self):
        text = GOOD.replace("shared budget [1]", "shared budget [1-2]")
        self.assertEqual(problems_of(text), [])
        text = GOOD.replace("shared budget [1]", "shared budget [1, 3]")
        self.assertTrue(any("[3]" in p for p in problems_of(text)))

    def test_malformed_urls_fail(self):
        for bad in ("http//example.com/x", "https:/example.com", "https://localhostx/",
                    "https://exa mple.com/page", "https://"):
            text = GOOD.replace("https://console.groq.com/docs/rate-limits\n",
                                bad + "\n", 1)
            probs = problems_of(text)
            self.assertTrue(any("malformed URL" in p for p in probs), (bad, probs))

    def test_empty_link_target_fails(self):
        text = GOOD.replace("- Groq: fast;", "- [Groq]() fast;")
        self.assertTrue(any("empty target" in p for p in problems_of(text)))

    def test_source_without_locator_fails(self):
        text = GOOD.replace("[2] Groq rate limits - https://console.groq.com/docs/rate-limits",
                            "[2] Groq rate limits page")
        self.assertTrue(any("source [2] has no URL" in p for p in problems_of(text)))

    def test_duplicate_source_id_fails(self):
        text = GOOD.replace("RESULT: DONE", "[2] again - https://example.org/a\n\nRESULT: DONE")
        self.assertTrue(any("defined twice" in p for p in problems_of(text)))

    def test_code_blocks_and_inline_code_ignored(self):
        text = GOOD.replace("## Options & trade-offs",
                            "```\nhttp//not-a-url arr[9]\n```\n\n## Options & trade-offs")
        text = text.replace("Use the Kilo lane", "Use the Kilo lane (`items[4]`)")
        self.assertEqual(problems_of(text), [])

    def test_http_protocol_version_is_not_a_url(self):
        text = GOOD.replace("- Kilo: no key needed;", "- Kilo: speaks HTTP/2 and HTTP/1.1;")
        self.assertEqual(problems_of(text), [])

    def test_numbered_sources_list_accepted(self):
        text = GOOD.replace("[1] Kilo free tier", "1. Kilo free tier").replace(
            "[2] Groq rate limits -", "2. Groq rate limits -")
        self.assertEqual(problems_of(text), [])

    def test_path_line_citation_accepted(self):
        text = GOOD.replace("- Groq documents per-model limits on its rate-limit page "
                            "https://console.groq.com/docs/rate-limits",
                            "- The engine refuses unproven free models (engine/guard.py:40).")
        self.assertEqual(problems_of(text), [])


class CiteCheckCli(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(HERE / "cite_check.py"), *args],
                              capture_output=True, text=True, timeout=60)

    def test_help(self):
        proc = self.run_tool("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("INFERENCE", proc.stdout)

    def test_exit_codes_and_one_line_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "2026-10-30-good.md"
            good.write_text(GOOD)
            proc = self.run_tool(str(good))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("cite_check: OK", proc.stdout)

            bad = Path(tmp) / "bad.md"
            bad.write_text(GOOD.split("## Sources")[0])
            proc = self.run_tool(str(bad))
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
            self.assertIn("FAIL", proc.stderr)

            proc = self.run_tool(str(Path(tmp) / "missing.md"))
            self.assertEqual(proc.returncode, 2)
            self.assertIn("cannot read", proc.stderr)

    def test_templates_have_sources_sections(self):
        tdir = HERE.parent / "templates"
        for name in ("memo-quick.md", "memo-decision.md"):
            text = (tdir / name).read_text()
            self.assertIn("## Sources", text, name)


if __name__ == "__main__":
    unittest.main()
