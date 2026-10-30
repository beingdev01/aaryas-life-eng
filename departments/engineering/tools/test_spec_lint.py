"""Tests for spec_lint.py. Temp files only; specs are written inline."""

import io
import json
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lint as sl  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "task-spec.yaml"
W = "/home/ubuntu/aaryas-life/departments/engineering/work/demo"

GOOD = textwrap.dedent(f"""\
    id: demo
    title: Lane health and hung-process monitor for the free model lanes
    depth: 3
    goal: >
      Build a monitoring tool that reports lane processes older than a threshold and
      classifies provider errors, without ever killing a process unless asked.
    authorized_paths:
      - {W}
    banned_paths:
      - /home/ubuntu/clubsite
    deliverables:
      - path: {W}/lanewatch.py
        min_bytes: 1500
        description: the monitor
      - path: {W}/README.md
        min_bytes: 600
        description: how to run it
    acceptance:
      - name: compiles
        cmd: python3 -m py_compile {W}/lanewatch.py
      - name: unit_tests_pass
        cmd: cd {W} && python3 -m unittest test_lanewatch -v
      - name: runs_and_emits_json
        cmd: cd {W} && python3 lanewatch.py --json | python3 -c "import json,sys; json.load(sys.stdin); print('VALID_JSON')"
        expect_stdout: VALID_JSON
      - name: no_credential_reads
        cmd: "! grep -rnE '\\\\.config/|\\\\.env|api_key *=' {W}/lanewatch.py"
    """)


class SpecLintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "demo-spec.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def run_lint(self, text, *extra):
        self.path.write_text(text)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = sl.main([str(self.path), "--json", *extra])
        data = json.loads(out.getvalue()) if out.getvalue().strip().startswith("{") else None
        return rc, data, err.getvalue()

    def messages(self, data, level="ERROR"):
        return "\n".join(f"{x['where']}: {x['message']}" for x in data["findings"]
                         if x["level"] == level)

    def test_good_spec_passes_clean(self):
        rc, data, err = self.run_lint(GOOD)
        self.assertEqual(rc, 0, data)
        self.assertEqual(data["errors"], 0)
        self.assertEqual(err, "")

    def test_shipped_template_passes_strict(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = sl.main([str(TEMPLATE), "--strict"])
        self.assertEqual(rc, 0, out.getvalue())

    def test_existence_only_checks_are_errors(self):
        for cmd in (f"test -f {W}/lanewatch.py", f"ls {W}/lanewatch.py",
                    f"[ -e {W}/lanewatch.py ]", f"test -s {W}/a.py && echo PASS",
                    f"cd {W} && ls -la", f"wc -c {W}/a.py", f"[[ -f {W}/a.py ]] || exit 1"):
            spec = GOOD.replace(f"cmd: python3 -m py_compile {W}/lanewatch.py", f"cmd: '{cmd}'")
            rc, data, _ = self.run_lint(spec)
            self.assertEqual(rc, 1, cmd)
            self.assertIn("only tests existence", self.messages(data), cmd)

    def test_unquoted_bracket_command_is_an_error(self):
        spec = GOOD.replace(f"cmd: python3 -m py_compile {W}/lanewatch.py", f"cmd: [ -e {W}/x.py ]")
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("not a string", self.messages(data))

    def test_never_failing_commands_are_errors(self):
        spec = GOOD.replace("python3 -m unittest test_lanewatch -v",
                            "python3 -m unittest test_lanewatch -v || true")
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("can never fail", self.messages(data))
        spec = GOOD.replace("python3 -m unittest test_lanewatch -v",
                            "python3 -m unittest test_lanewatch -v; echo done")
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("proves nothing", self.messages(data))

    def test_set_e_makes_trailing_echo_acceptable(self):
        spec = GOOD.replace("cd {W} && python3 -m unittest test_lanewatch -v".format(W=W),
                            f"set -e; cd {W}; python3 -m unittest test_lanewatch -v; echo done")
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 0, self.messages(data))

    def test_pipe_into_tee_warns(self):
        spec = GOOD.replace("python3 -m unittest test_lanewatch -v",
                            "python3 -m unittest test_lanewatch -v | tee /tmp/t.log")
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 0)
        self.assertIn("masks the real exit code", self.messages(data, "WARN"))
        rc, _, _ = self.run_lint(spec, "--strict")
        self.assertEqual(rc, 1)

    def test_no_acceptance_is_an_error(self):
        spec = GOOD.split("acceptance:")[0]
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("no acceptance commands", self.messages(data))

    def test_acceptance_without_cmd_is_an_error(self):
        spec = GOOD + "  - name: forgot_the_command\n    expect_exit: 0\n"
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("drops it silently", self.messages(data))

    def test_small_or_missing_min_bytes_on_code_is_an_error(self):
        rc, data, _ = self.run_lint(GOOD.replace("min_bytes: 1500", "min_bytes: 50"))
        self.assertEqual(rc, 1)
        self.assertIn("below 200", self.messages(data))
        rc, data, _ = self.run_lint(GOOD.replace("    min_bytes: 600\n", ""))
        self.assertEqual(rc, 1)
        self.assertIn("min_bytes missing", self.messages(data))

    def test_small_min_bytes_on_binary_is_only_a_warning(self):
        spec = GOOD.replace(f"{W}/README.md", f"{W}/preview.png").replace("min_bytes: 600", "min_bytes: 10")
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 0, self.messages(data))
        self.assertIn("small for a .png", self.messages(data, "WARN"))

    def test_deliverable_outside_authorized_or_inside_banned(self):
        spec = GOOD.replace(f"path: {W}/README.md", "path: /home/ubuntu/aaryas-life/README.md")
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("outside every authorized path", self.messages(data))
        spec = GOOD.replace(f"path: {W}/README.md", "path: /home/ubuntu/clubsite/README.md") \
                   .replace(f"  - {W}\n", f"  - {W}\n  - /home/ubuntu/clubsite\n", 1)
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("inside banned path", self.messages(data))

    def test_relative_deliverable_is_an_error(self):
        rc, data, _ = self.run_lint(GOOD.replace(f"path: {W}/README.md", "path: README.md"))
        self.assertEqual(rc, 1)
        self.assertIn("relative path", self.messages(data))

    def test_tripwire_authorized_path_is_an_error(self):
        spec = GOOD.replace(f"  - {W}\n", f"  - {W}\n  - /home/ubuntu/aaryas-life/agents/x\n", 1)
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("tripwire", self.messages(data))

    def test_banned_title_words(self):
        for word in ("max", "Heavy", "complex", "Architecture", "[max]", "complexity"):
            spec = GOOD.replace("Lane health and", f"Lane health {word} and")
            rc, data, _ = self.run_lint(spec)
            self.assertEqual(rc, 1, word)
            self.assertIn("paid tier", self.messages(data), word)
        rc, data, _ = self.run_lint(GOOD.replace("Lane health and", "Lane health maximum and"))
        self.assertEqual(rc, 0, "maximum is not the word max")

    def test_depth_out_of_range_or_wrong_type(self):
        for depth in ("0", "6", "high", "true"):
            rc, data, _ = self.run_lint(GOOD.replace("depth: 3", f"depth: {depth}"))
            self.assertEqual(rc, 1, depth)
            self.assertIn("depth", self.messages(data))
        rc, data, _ = self.run_lint(GOOD.replace("depth: 3\n", ""))
        self.assertEqual(rc, 0)
        self.assertIn("defaults to 3", self.messages(data, "WARN"))

    def test_thin_goal_is_an_error(self):
        spec = GOOD.split("goal: >")[0] + "goal: make a monitor\n" + \
            "authorized_paths:" + GOOD.split("authorized_paths:")[1]
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("at least 40", self.messages(data))

    def test_credential_context_source_is_an_error(self):
        spec = GOOD.replace("depth: 3", "depth: 3\ncontext_sources:\n  - /home/ubuntu/.config/kilo/kilo.jsonc")
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        self.assertIn("credentials", self.messages(data))

    def test_compile_only_acceptance_warns(self):
        spec = GOOD.split("  - name: unit_tests_pass")[0]
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 0)
        self.assertIn("only compiles", self.messages(data, "WARN"))

    def test_parts_need_exclusive_files_and_real_verify(self):
        spec = GOOD + textwrap.dedent(f"""\
            parts:
              - id: core
                owns_files: [{W}/lanewatch.py]
                verify_cmd: test -f {W}/lanewatch.py
              - id: docs
                owns_files: [{W}/lanewatch.py]
                verify_cmd: grep -q 'Usage' {W}/README.md
            """)
        rc, data, _ = self.run_lint(spec)
        self.assertEqual(rc, 1)
        msgs = self.messages(data)
        self.assertIn("also owned by part core", msgs)
        self.assertIn("part core verify_cmd", msgs)

    def test_unknown_key_typo_warns(self):
        rc, data, _ = self.run_lint(GOOD.replace("acceptance:", "acceptence:"))
        self.assertEqual(rc, 1)  # the typo also means there is no acceptance at all
        self.assertIn("did you mean acceptance", self.messages(data, "WARN"))

    def test_unparseable_and_missing_files_exit_two(self):
        rc, _, err = self.run_lint("title: [unclosed\n")
        self.assertEqual(rc, 2)
        self.assertIn("does not parse", err)
        err_buf = io.StringIO()
        with redirect_stderr(err_buf), redirect_stdout(io.StringIO()):
            rc = sl.main([str(self.path.parent / "nope.yaml")])
        self.assertEqual(rc, 2)

    def test_segments_and_command_names(self):
        segs = sl.segments("A=1 ! grep -q x f && cd d; python3 t.py 2>&1 | tee log")
        names = [sl.command_name(w) for _, w in segs]
        self.assertEqual(names, ["grep", "cd", "python3", "tee"])


if __name__ == "__main__":
    unittest.main()
