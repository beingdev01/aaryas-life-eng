"""Tests for caddy_block_lint.py. Pure text; temp files only; caddy is never run."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caddy_block_lint as cbl  # noqa: E402

GOOD = """# certificates portal (AAR-200)
http://certs.codescriet.dev {
	header {
		Strict-Transport-Security "max-age=15552000"
	}
	reverse_proxy 127.0.0.1:18790 {
		flush_interval -1
	}
}
"""

EXISTING_CADDYFILE = """{
	admin off
}
http://codescriet.dev {
	root * /home/ubuntu/clubsite/apps/web/dist
	file_server
}
http://api.codescriet.dev {
	reverse_proxy 127.0.0.1:5001
}
http://tds-ga1-dl.codescriet.dev {
	reverse_proxy 127.0.0.1:18766
}
"""


class CaddyBlockLintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_lint(self, text, *extra):
        path = self.dir / "block.txt"
        path.write_text(text)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cbl.main([str(path), *extra])
        return rc, out.getvalue(), err.getvalue()

    def test_good_block_passes_and_prints_ceo_commands(self):
        rc, out, err = self.run_lint(GOOD)
        self.assertEqual(rc, 0, out)
        self.assertIn("Commands for the CEO", out)
        self.assertIn("caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile", out)
        self.assertIn("sudo systemctl restart caddy", out)
        self.assertIn("https://certs.codescriet.dev/", out)
        self.assertNotIn("systemctl reload", out)
        self.assertEqual(err, "")

    def test_apex_is_rejected(self):
        rc, out, err = self.run_lint(GOOD.replace("certs.codescriet.dev", "codescriet.dev"))
        self.assertEqual(rc, 1)
        self.assertIn("main domain", out)
        self.assertNotIn("Commands for the CEO", out)
        self.assertTrue(err.startswith("caddy_block_lint:"))

    def test_www_is_rejected(self):
        rc, out, _ = self.run_lint(GOOD.replace("certs.", "www."))
        self.assertEqual(rc, 1)
        self.assertIn("www.codescriet.dev", out)

    def test_other_domain_and_multilevel_rejected(self):
        rc, out, _ = self.run_lint(GOOD.replace("certs.codescriet.dev", "certs.example.com"))
        self.assertEqual(rc, 1)
        self.assertIn("not a subdomain", out)
        rc, out, _ = self.run_lint(GOOD.replace("certs.", "a.certs."))
        self.assertEqual(rc, 1)
        self.assertIn("more than one level", out)

    def test_https_or_bare_address_rejected(self):
        rc, out, _ = self.run_lint(GOOD.replace("http://certs", "https://certs"))
        self.assertEqual(rc, 1)
        self.assertIn("must start with http://", out)
        rc, out, _ = self.run_lint(GOOD.replace("http://certs", "certs"))
        self.assertEqual(rc, 1)

    def test_upstream_must_be_loopback_with_port(self):
        for bad, needle in (("10.0.0.5:18790", "must be 127.0.0.1"),
                            ("127.0.0.1", "no explicit port"),
                            ("https://127.0.0.1:18790", "plain http"),
                            ("{env.UPSTREAM}", "placeholder")):
            rc, out, _ = self.run_lint(GOOD.replace("127.0.0.1:18790", bad))
            self.assertEqual(rc, 1, bad)
            self.assertIn(needle, out, bad)

    def test_localhost_upstream_accepted(self):
        rc, out, _ = self.run_lint(GOOD.replace("127.0.0.1:18790", "localhost:18790"))
        self.assertEqual(rc, 0, out)

    def test_admin_port_and_directive_rejected(self):
        rc, out, _ = self.run_lint(GOOD.replace("127.0.0.1:18790", "127.0.0.1:2019"))
        self.assertEqual(rc, 1)
        self.assertIn("2019", out)
        rc, out, _ = self.run_lint(GOOD.replace("\theader {", "\tadmin localhost:2019\n\theader {"))
        self.assertEqual(rc, 1)
        self.assertIn("admin directive", out)

    def test_missing_hsts_rejected(self):
        block = "http://certs.codescriet.dev {\n\treverse_proxy 127.0.0.1:18790\n}\n"
        rc, out, _ = self.run_lint(block)
        self.assertEqual(rc, 1)
        self.assertIn("Strict-Transport-Security", out)

    def test_low_hsts_is_warning_and_strict_fails(self):
        low = GOOD.replace("15552000", "300")
        rc, out, _ = self.run_lint(low)
        self.assertEqual(rc, 0)
        self.assertIn("WARN", out)
        rc, _, _ = self.run_lint(low, "--strict")
        self.assertEqual(rc, 1)

    def test_no_reverse_proxy_rejected_unless_static(self):
        static = ("http://slides.codescriet.dev {\n"
                  "\theader {\n\t\tStrict-Transport-Security \"max-age=15552000\"\n\t}\n"
                  "\troot * /var/www/slides\n\tfile_server\n}\n")
        rc, out, _ = self.run_lint(static)
        self.assertEqual(rc, 1)
        self.assertIn("no reverse_proxy", out)
        rc, out, _ = self.run_lint(static, "--static")
        self.assertEqual(rc, 0, out)
        self.assertIn("namei -l /var/www/slides", out)

    def test_file_server_on_sensitive_paths_rejected(self):
        for root in ("/", "/home/ubuntu", "/etc/caddy", "/home/ubuntu/.ssh",
                     "/home/ubuntu/aaryas-life", "/var/www/site/.git",
                     "/home/ubuntu/clubsite/apps/web/dist"):
            block = ("http://files.codescriet.dev {\n"
                     "\theader Strict-Transport-Security \"max-age=15552000\"\n"
                     f"\troot * {root}\n\tfile_server\n}}\n")
            rc, out, _ = self.run_lint(block, "--static")
            self.assertEqual(rc, 1, root)

    def test_file_server_without_root_rejected(self):
        block = ("http://files.codescriet.dev {\n"
                 "\theader Strict-Transport-Security \"max-age=15552000\"\n\tfile_server\n}\n")
        rc, out, _ = self.run_lint(block, "--static")
        self.assertEqual(rc, 1)
        self.assertIn("without a root", out)

    def test_protected_subdomain_rejected_then_allowed(self):
        rc, out, _ = self.run_lint(GOOD.replace("certs.", "vpn.").replace("18790", "18791"))
        self.assertEqual(rc, 1)
        self.assertIn("protected subdomain", out)
        rc, out, _ = self.run_lint(GOOD.replace("certs.", "vpn."), "--allow-protected")
        self.assertEqual(rc, 0, out)

    def test_two_blocks_and_global_options_rejected(self):
        rc, out, _ = self.run_lint(GOOD + GOOD.replace("certs.", "other."))
        self.assertEqual(rc, 1)
        self.assertIn("exactly one site block", out)
        rc, out, _ = self.run_lint("{\n\tadmin off\n}\n" + GOOD)
        self.assertEqual(rc, 1)
        self.assertIn("global options", out)

    def test_tls_directive_rejected(self):
        rc, out, _ = self.run_lint(GOOD.replace("\theader {", "\ttls internal\n\theader {"))
        self.assertEqual(rc, 1)
        self.assertIn("tls directive", out)

    def test_unbalanced_braces_rejected(self):
        rc, out, _ = self.run_lint(GOOD.rstrip().rstrip("}"))
        self.assertEqual(rc, 1)
        self.assertIn("never closed", out)

    def test_duplicate_of_existing_block_detected(self):
        cf = self.dir / "Caddyfile"
        cf.write_text(EXISTING_CADDYFILE)
        dup = GOOD.replace("certs.", "tds-ga1-dl.")
        rc, out, _ = self.run_lint(dup, "--caddyfile", str(cf))
        self.assertEqual(rc, 1)
        self.assertIn("already has a block", out)
        rc, out, _ = self.run_lint(GOOD, "--caddyfile", str(cf))
        self.assertEqual(rc, 0, out)

    def test_known_port_is_a_warning(self):
        rc, out, _ = self.run_lint(GOOD.replace("18790", "5001"))
        self.assertEqual(rc, 0)
        self.assertIn("club-api", out)

    def test_comments_are_ignored_and_hash_in_quotes_kept(self):
        block = GOOD.replace("reverse_proxy 127.0.0.1:18790 {",
                             "reverse_proxy 127.0.0.1:18790 { # the certs service")
        rc, out, _ = self.run_lint(block)
        self.assertEqual(rc, 0, out)

    def test_unreadable_file_exits_two(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = cbl.main([str(self.dir / "missing.txt")])
        self.assertEqual(rc, 2)
        self.assertIn("cannot read", err.getvalue())


if __name__ == "__main__":
    unittest.main()
