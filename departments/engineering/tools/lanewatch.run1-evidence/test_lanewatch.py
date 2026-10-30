#!/usr/bin/env python3
"""Unit tests for lanewatch.py.

Covers error classification for every provider failure mode (quota,
no_funds, rate_limited, auth, hang, unknown) and the age-threshold logic
that decides which processes are reported. Tests use only the Python
standard library and import functions directly from lanewatch.py.
"""

import unittest

from lanewatch import (
    classify_error,
    parse_ps_line,
    is_lane_process,
    filter_by_age,
    build_report,
    scan,
    _ERROR_SIGNATURES,
    _LANE_NAMES,
)


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class TestClassifyQuota(unittest.TestCase):
    """quota exhaustion: free usage limit reached, quota exceeded."""

    def test_free_usage_limit_reached(self):
        text = ("AI_APICallError: Free usage limit reached. Free models work "
                "in OpenCode; subscribe to OpenCode Go to keep going")
        self.assertEqual(classify_error(text), "quota")

    def test_quota_exceeded(self):
        self.assertEqual(classify_error("ERROR: quota exceeded for model"), "quota")

    def test_usage_limit_reached(self):
        self.assertEqual(classify_error("usage limit reached for tier"), "quota")

    def test_case_insensitive(self):
        self.assertEqual(classify_error("FREE USAGE LIMIT REACHED"), "quota")

    def test_embedded_in_long_text(self):
        blob = "some preamble\nrate=0\nFree usage limit reached\ntrailing"
        self.assertEqual(classify_error(blob), "quota")


class TestClassifyNoFunds(unittest.TestCase):
    """insufficient funds / payment required."""

    def test_insufficient_account_funds(self):
        text = ("AI_APICallError: Upstream request failed: "
                "Insufficient account funds")
        self.assertEqual(classify_error(text), "no_funds")

    def test_insufficient_funds(self):
        self.assertEqual(classify_error("Insufficient funds"), "no_funds")

    def test_payment_required(self):
        self.assertEqual(classify_error("Payment required"), "no_funds")


class TestClassifyRateLimited(unittest.TestCase):
    """rate limiting / 429."""

    def test_rate_limit(self):
        self.assertEqual(classify_error("Rate limit reached"), "rate_limited")

    def test_ratelimit(self):
        self.assertEqual(classify_error("you are ratelimited"), "rate_limited")

    def test_too_many_requests(self):
        self.assertEqual(classify_error("too many requests"), "rate_limited")

    def test_status_code_429(self):
        self.assertEqual(classify_error("status code 429"), "rate_limited")


class TestClassifyAuth(unittest.TestCase):
    """authentication failure."""

    def test_not_logged_in(self):
        self.assertEqual(classify_error("Not logged in"), "auth")

    def test_unauthorized(self):
        self.assertEqual(classify_error("Unauthorized"), "auth")

    def test_forbidden(self):
        self.assertEqual(classify_error("403 Forbidden"), "auth")


class TestClassifyHang(unittest.TestCase):
    """hang: timeout exit code 124 or timeout wording."""

    def test_exit_code_124(self):
        self.assertEqual(classify_error("exited with code 124: timed out"), "hang")

    def test_timed_out(self):
        self.assertEqual(classify_error("timed out after 90 seconds"), "hang")

    def test_timeout_wording(self):
        self.assertEqual(classify_error("TIMEOUT waiting for provider"), "hang")

    def test_timeout_with_124(self):
        self.assertEqual(classify_error("124 timeout killed"), "hang")


class TestClassifyUnknown(unittest.TestCase):
    """unknown: no matching signature."""

    def test_empty_string(self):
        self.assertEqual(classify_error(""), "unknown")

    def test_none_input(self):
        self.assertEqual(classify_error(None), "unknown")

    def test_unrelated_text(self):
        self.assertEqual(classify_error("OK"), "unknown")

    def test_random_error(self):
        self.assertEqual(classify_error("some random error message"), "unknown")


class TestClassificationPrecedence(unittest.TestCase):
    """Signatures take priority over hang (mirrors engine classify)."""

    def test_quota_beats_hang(self):
        text = ("Free usage limit reached\ntimed out after 90s")
        self.assertEqual(classify_error(text), "quota")

    def test_no_funds_beats_hang(self):
        text = ("Insufficient account funds\nexited with code 124")
        self.assertEqual(classify_error(text), "no_funds")


class TestAllCategoriesCovered(unittest.TestCase):
    """Every error category must be reachable."""

    CATEGORIES = {"quota", "no_funds", "rate_limited", "auth", "hang", "unknown"}

    def test_signatures_cover_expected(self):
        sig_cats = {v for v, _ in _ERROR_SIGNATURES}
        expected_sig_cats = {"quota", "no_funds", "rate_limited", "auth"}
        self.assertEqual(sig_cats, expected_sig_cats)

    def test_all_six_returned(self):
        samples = [
            ("free usage limit reached", "quota"),
            ("insufficient account funds", "no_funds"),
            ("rate limit", "rate_limited"),
            ("not logged in", "auth"),
            ("timed out", "hang"),
            ("nothing here", "unknown"),
        ]
        for text, expected in samples:
            self.assertEqual(classify_error(text), expected,
                             f"expected {expected} for {text!r}")


# ---------------------------------------------------------------------------
# ps line parsing
# ---------------------------------------------------------------------------

class TestParsePsLine(unittest.TestCase):
    def test_valid_line(self):
        line = "1234  3600 480000 /usr/bin/kilo run --format json"
        result = parse_ps_line(line)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 1234)
        self.assertEqual(result[1], 3600)
        self.assertEqual(result[2], 480000)
        self.assertEqual(result[3], "/usr/bin/kilo run --format json")

    def test_header_skipped(self):
        self.assertIsNone(parse_ps_line("  PID ELAPSED   RSS COMMAND"))

    def test_too_few_parts(self):
        self.assertIsNone(parse_ps_line("1234 3600"))
        self.assertIsNone(parse_ps_line(""))
        self.assertIsNone(parse_ps_line("short"))

    def test_non_numeric_pid(self):
        self.assertIsNone(parse_ps_line("abc def ghi cmd"))

    def test_multispace_separated(self):
        line = "  999   7200 960000 /usr/bin/opencode run"
        result = parse_ps_line(line)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 999)
        self.assertEqual(result[1], 7200)
        self.assertEqual(result[2], 960000)


# ---------------------------------------------------------------------------
# Lane process detection
# ---------------------------------------------------------------------------

class TestIsLaneProcess(unittest.TestCase):
    def test_kilo(self):
        self.assertTrue(is_lane_process("/usr/bin/kilo run --format json"))
        self.assertTrue(is_lane_process("kilo run"))

    def test_opencode(self):
        self.assertTrue(is_lane_process("/home/u/.opencode/bin/opencode run"))
        self.assertTrue(is_lane_process("opencode run --format json"))

    def test_qodercli(self):
        self.assertTrue(is_lane_process("qodercli -m Qwen3.8-Flash"))

    def test_not_lane(self):
        self.assertFalse(is_lane_process("/usr/bin/vim file.txt"))
        self.assertFalse(is_lane_process("python3 script.py"))
        self.assertFalse(is_lane_process("bash -l"))
        self.assertFalse(is_lane_process(""))


# ---------------------------------------------------------------------------
# Age threshold logic
# ---------------------------------------------------------------------------

class TestFilterByAge(unittest.TestCase):
    def _proc(self, pid, age, rss_kb=480000):
        return {
            "pid": pid,
            "age_seconds": age,
            "rss_mb": round(rss_kb / 1024.0, 1),
            "cmdline": "kilo run",
            "state": "S",
            "error_category": "unknown",
        }

    def test_all_old_enough(self):
        procs = [self._proc(1, 3601), self._proc(2, 7200)]
        self.assertEqual(len(filter_by_age(procs, 3600)), 2)

    def test_all_too_young(self):
        procs = [self._proc(1, 100), self._proc(2, 3599)]
        self.assertEqual(len(filter_by_age(procs, 3600)), 0)

    def test_boundary_inclusive(self):
        procs = [self._proc(1, 3600)]
        self.assertEqual(len(filter_by_age(procs, 3600)), 1)

    def test_mixed_ages(self):
        procs = [
            self._proc(1, 100), self._proc(2, 3601),
            self._proc(3, 5000), self._proc(4, 1),
        ]
        filtered = filter_by_age(procs, 3600)
        self.assertEqual(len(filtered), 2)
        self.assertEqual([p["pid"] for p in filtered], [2, 3])

    def test_empty_list(self):
        self.assertEqual(filter_by_age([], 3600), [])

    def test_custom_threshold(self):
        procs = [self._proc(1, 300), self._proc(2, 601)]
        filtered = filter_by_age(procs, 600)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["pid"], 601)


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

class TestBuildReport(unittest.TestCase):
    def test_empty_processes(self):
        report = build_report([], 3600)
        self.assertEqual(report["process_count"], 0)
        self.assertEqual(report["total_memory_mb"], 0.0)
        self.assertEqual(report["processes"], [])
        self.assertEqual(report["older_than_seconds"], 3600)

    def test_with_processes(self):
        procs = [
            {"pid": 100, "age_seconds": 7200, "rss_mb": 470.0,
             "cmdline": "kilo run", "state": "S", "error_category": "hang"},
            {"pid": 200, "age_seconds": 3601, "rss_mb": 465.0,
             "cmdline": "opencode run", "state": "S", "error_category": "quota"},
        ]
        report = build_report(procs, 3600)
        self.assertEqual(report["process_count"], 2)
        self.assertAlmostEqual(report["total_memory_mb"], 935.0, places=1)
        self.assertEqual(report["by_category"], {"hang": 1, "quota": 1})
        self.assertEqual(len(report["processes"]), 2)

    def test_scanned_at_format(self):
        report = build_report([], 3600)
        ts = report["scanned_at"]
        self.assertTrue(ts.endswith("Z"))
        self.assertEqual(len(ts), 20)  # YYYY-MM-DDTHH:MM:SSZ


# ---------------------------------------------------------------------------
# Integration: scan runs without crashing (may return empty on test VM)
# ---------------------------------------------------------------------------

class TestScanNoCrash(unittest.TestCase):
    def test_scan_returns_list(self):
        result = scan(older_than=3600)
        self.assertIsInstance(result, list)
        for proc in result:
            self.assertIn("pid", proc)
            self.assertIn("age_seconds", proc)
            self.assertIn("rss_mb", proc)
            self.assertIn("cmdline", proc)
            self.assertIn("error_category", proc)

    def test_scan_with_zero_threshold(self):
        result = scan(older_than=0)
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# Real error strings from receipts/R03 (verified 2026-10-30)
# ---------------------------------------------------------------------------

class TestRealProviderErrors(unittest.TestCase):
    def test_quota_error_from_receipt(self):
        text = ("AI_APICallError: Free usage limit reached. Free models work "
                "in OpenCode (https://opencode.ai); subscribe to OpenCode Go "
                "to keep going: https://opencode.ai/go")
        self.assertEqual(classify_error(text), "quota")

    def test_no_funds_error_from_receipt(self):
        text = ("AI_APICallError: Upstream request failed: "
                "Insufficient account funds")
        self.assertEqual(classify_error(text), "no_funds")


if __name__ == "__main__":
    unittest.main()
