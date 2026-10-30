"""Tests for health_report.py. Temp dirs only; a fake /proc tree; no live services."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import health_report as hr  # noqa: E402

NOW = datetime(2026, 10, 30, 15, 10, 0, tzinfo=timezone.utc)
CLK = 100


def call(argv):
    """Run the tool quietly; return its exit code."""
    import io
    from contextlib import redirect_stderr, redirect_stdout
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return hr.main(argv, now=NOW, clk_tck=CLK)


def make_proc(root: Path, mem_avail_kb=5_000_000, uptime=200_000.0, procs=()):
    root.mkdir(parents=True, exist_ok=True)
    (root / "meminfo").write_text(
        "MemTotal:       12210692 kB\n"
        f"MemAvailable:   {mem_avail_kb} kB\n"
        "SwapTotal:       2097148 kB\nSwapFree:        1258288 kB\n")
    (root / "loadavg").write_text("0.84 2.21 2.76 1/615 2456978\n")
    (root / "uptime").write_text(f"{uptime} 300000.00\n")
    for pid, argv, age_sec, rss_kb in procs:
        d = root / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        comm = os.path.basename(argv[0])[:15]
        (d / "comm").write_text(comm + "\n")
        start = int((uptime - age_sec) * CLK)
        fields = ["S", "1"] + ["0"] * 17 + [str(start)] + ["0"] * 10
        (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n")
        (d / "status").write_text(f"Name:\t{comm}\nVmRSS:\t  {rss_kb} kB\n")
    return root


def write_sources(base: Path, monitor_status="ok", cert_days=67, backup="OK :: 2026-10-29 21:34:38 UTC",
                  monitor_at="2026-10-30T15:05:01+00:00", domain_text=None):
    base.mkdir(parents=True, exist_ok=True)
    (base / "health.json").write_text(json.dumps({
        "generated_at": monitor_at,
        "services": [
            {"service": "codescriet.dev", "status": "ok", "detail": "HTTP 200"},
            {"service": "club-api", "status": monitor_status, "detail": "systemd: inactive"},
        ]}))
    (base / "alerts.log").write_text(
        "2026-10-20T09:20:02+00:00 codescriet.dev: ok -> warn (unexpected HTTP 404)\n")
    (base / "status.json").write_text(json.dumps({
        "generated_at": "2026-10-30T09:30:01+00:00",
        "certs": [{"service": "codescriet.dev", "status": "ok", "expires_in_days": cert_days,
                   "not_after": "Jan  5 19:34:08 2027 GMT"}]}))
    (base / "domain-watch.md").write_text(domain_text if domain_text is not None else (
        "== domain-watch 2026-10-18T11:00:01Z ==\n"
        "== domain-watch 2026-10-25T11:00:01Z ==\n"
        "Registry Expiry Date: 2027-09-21T10:00:00Z\n"))
    (base / "last-status.txt").write_text(backup + "\n")


class HealthReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.src = self.base / "src"
        self.out = self.base / "out" / "health-report.md"

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, extra=(), proc_kwargs=None, **src_kwargs):
        write_sources(self.src, **src_kwargs)
        proc = make_proc(self.base / "proc", **(proc_kwargs or {}))
        argv = ["--out", str(self.out), "--monitor", str(self.src / "health.json"),
                "--alerts", str(self.src / "alerts.log"), "--certs", str(self.src / "status.json"),
                "--domain", str(self.src / "domain-watch.md"),
                "--backup-status", str(self.src / "last-status.txt"),
                "--proc", str(proc), "--disk-path", str(self.base), "--disk-max-pct", "100",
                *extra]
        rc = call(argv)
        return rc, self.out.read_text() if self.out.exists() else ""

    def test_all_healthy_exits_zero_and_has_ceo_section(self):
        rc, text = self.run_tool()
        self.assertEqual(rc, 0, text)
        self.assertIn("Verdict: **OK**", text)
        self.assertIn("## Commands for the CEO", text)
        self.assertIn("No commands needed", text)
        self.assertIn("| club-api | ok |", text)

    def test_service_down_is_a_breach_with_restart_command_for_ceo(self):
        rc, text = self.run_tool(monitor_status="down")
        self.assertEqual(rc, 1)
        self.assertIn("club-api is down", text)
        self.assertIn("sudo systemctl restart club-api", text)

    def test_low_memory_breaches(self):
        rc, text = self.run_tool(proc_kwargs={"mem_avail_kb": 512 * 1024})
        self.assertEqual(rc, 1)
        self.assertIn("MemAvailable 512 MiB is below 1024 MiB", text)

    def test_disk_threshold_breaches(self):
        write_sources(self.src)
        rc, text = self.run_tool(extra=["--disk-max-pct", "0"])
        self.assertEqual(rc, 1)
        self.assertRegex(text, r"disk .* is [\d.]+% used \(limit 0%\)")

    def test_certificate_expiring_soon_breaches(self):
        rc, text = self.run_tool(cert_days=9)
        self.assertEqual(rc, 1)
        self.assertIn("expires in 9 days (limit 14)", text)

    def test_cert_check_error_entry_is_a_breach(self):
        write_sources(self.src)
        (self.src / "status.json").write_text(json.dumps({
            "generated_at": "2026-10-30T09:30:01+00:00",
            "certs": [{"service": "codescriet.dev", "status": "critical",
                       "detail": "check error: timeout"}]}))
        proc = make_proc(self.base / "proc")
        rc = call(["--out", str(self.out), "--monitor", str(self.src / "health.json"),
                      "--alerts", str(self.src / "alerts.log"),
                      "--certs", str(self.src / "status.json"),
                      "--domain", str(self.src / "domain-watch.md"),
                      "--backup-status", str(self.src / "last-status.txt"),
                      "--proc", str(proc), "--disk-path", str(self.base),
                      "--disk-max-pct", "100"])
        self.assertEqual(rc, 1)
        self.assertIn("could not read the certificate", self.out.read_text())

    def test_hung_lane_process_breaches_and_young_one_does_not(self):
        procs = [
            (4101, ["/home/ubuntu/.opencode/bin/opencode", "run", "--format", "json",
                    "--model", "opencode/flint-40b-free"], 50_000, 444_332),
            (4102, ["node", "/home/ubuntu/.local/bin/kilo", "run", "--title", "build-x",
                    "-m", "kilo/poolside/laguna-s-2.1:free"], 300, 36_000),
            (4103, ["/usr/bin/python3", "server.py"], 90_000, 10_000),
        ]
        rc, text = self.run_tool(proc_kwargs={"procs": procs})
        self.assertEqual(rc, 1)
        self.assertIn("1 lane process(es) older than 1h", text)
        self.assertIn("2 lane processes alive", text)
        self.assertIn("pids 4101", text)
        self.assertIn("engctl reap --older-than 3600 --kill", text)
        self.assertNotIn("| 4103 |", text)

    def test_lane_threshold_is_configurable(self):
        procs = [(4101, ["/x/opencode", "run"], 50_000, 400_000)]
        rc, _ = self.run_tool(extra=["--lane-max-age-hours", "24"], proc_kwargs={"procs": procs})
        self.assertEqual(rc, 0)

    def test_stale_monitor_snapshot_breaches(self):
        rc, text = self.run_tool(monitor_at="2026-10-30T13:00:00+00:00")
        self.assertEqual(rc, 1)
        self.assertIn("monitor snapshot is stale", text)

    def test_missing_monitor_file_breaches(self):
        write_sources(self.src)
        (self.src / "health.json").unlink()
        proc = make_proc(self.base / "proc")
        rc = call(["--out", str(self.out), "--monitor", str(self.src / "health.json"),
                      "--certs", str(self.src / "status.json"),
                      "--alerts", str(self.src / "alerts.log"),
                      "--domain", str(self.src / "domain-watch.md"),
                      "--backup-status", str(self.src / "last-status.txt"),
                      "--proc", str(proc), "--disk-path", str(self.base),
                      "--disk-max-pct", "100"])
        self.assertEqual(rc, 1)
        self.assertIn("is missing", self.out.read_text())

    def test_backup_failure_breaches(self):
        rc, text = self.run_tool(backup="FAIL :: 2026-10-29 21:31:00 UTC :: pg_dump of live DB failed")
        self.assertEqual(rc, 1)
        self.assertIn("last nightly backup FAILED", text)
        self.assertIn("CEO decision only", text)

    def test_old_backup_breaches(self):
        rc, text = self.run_tool(backup="OK :: 2026-10-27 21:34:38 UTC")
        self.assertEqual(rc, 1)
        self.assertIn("last successful backup is", text)

    def test_empty_domain_watch_is_a_warning_not_a_breach(self):
        rc, text = self.run_tool(domain_text="== domain-watch 2026-10-25T11:00:01Z ==\n")
        self.assertEqual(rc, 0)
        self.assertIn("domain expiry is unknown", text)

    def test_domain_expiring_breaches(self):
        rc, text = self.run_tool(domain_text="== domain-watch 2026-10-25T11:00:01Z ==\n"
                                             "Registry Expiry Date: 2026-11-20T00:00:00Z\n")
        self.assertEqual(rc, 1)
        self.assertIn("registration expires in", text)

    def test_refuses_to_overwrite_an_input(self):
        write_sources(self.src)
        rc = call(["--out", str(self.src / "health.json"),
                      "--monitor", str(self.src / "health.json")])
        self.assertEqual(rc, 2)

    def test_json_summary(self):
        write_sources(self.src)
        proc = make_proc(self.base / "proc")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = hr.main(["--out", str(self.out), "--monitor", str(self.src / "health.json"),
                          "--alerts", str(self.src / "alerts.log"),
                          "--certs", str(self.src / "status.json"),
                          "--domain", str(self.src / "domain-watch.md"),
                          "--backup-status", str(self.src / "last-status.txt"),
                          "--proc", str(proc), "--disk-path", str(self.base),
                          "--disk-max-pct", "100", "--json"], now=NOW, clk_tck=CLK)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["verdict"], "OK")

    def test_proc_name_detection(self):
        self.assertEqual(hr._proc_name(["node", "/a/kilo", "run"], "node"), "kilo")
        self.assertEqual(hr._proc_name(["/a/.kilo", "run"], ".kilo"), "kilo")
        self.assertEqual(hr._proc_name(["/a/opencode", "run"], "opencode"), "opencode")
        self.assertIsNone(hr._proc_name(["node", "/srv/app.js"], "node"))
        self.assertIsNone(hr._proc_name(["vim", "kilo.md"], "vim"))


if __name__ == "__main__":
    unittest.main()
