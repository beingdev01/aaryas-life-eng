"""Self-tests for the engine's safety and gate machinery.

These test the guarantees that matter: a paid lane cannot be dispatched, an
unverifiable task cannot enter the pipeline, and a missing or trivial artifact cannot
pass as done. Run with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import gate, guard, lanes as lanes_mod, spec as spec_mod, util  # noqa: E402
from engine.ledger import Ledger  # noqa: E402
from engine.stages import _parse_json_reply  # noqa: E402


class FreeLaneGuard(unittest.TestCase):
    def test_free_identifiers_accepted(self):
        for model in ("kilo/nvidia/nemotron-3-ultra-550b-a55b:free",
                      "opencode/flint-40b-free",
                      "kilo/poolside/laguna-s-2.1:free",
                      "kilo/openrouter/free"):
            ok, why = guard.is_free_model(model)
            self.assertTrue(ok, f"{model} should be free: {why}")

    def test_paid_and_unproven_identifiers_refused(self):
        for model in ("Qwen3.8-Max", "Qwen3.8-Flash", "gpt-5.4-nano",
                      "claude-sonnet-4", "gemini-2.5-pro", "opencode/ultimate",
                      "kilo/kilo-auto/auto", "", "some/model"):
            ok, _ = guard.is_free_model(model)
            self.assertFalse(ok, f"{model} must be refused")

    def test_max_variant_refused(self):
        self.assertFalse(guard.check_variant("max")[0])
        self.assertTrue(guard.check_variant("xhigh")[0])
        self.assertTrue(guard.check_variant(None)[0])

    def test_enforce_raises_when_paid_lane_enabled(self):
        pool = [lanes_mod.Lane("good", "kilo", "x/y:free", "fam", ["build"], True),
                lanes_mod.Lane("bad", "kilo", "Qwen3.8-Max", "fam2", ["build"], True)]
        with self.assertRaises(guard.PaidModelRefused):
            guard.enforce(pool)

    def test_enforce_ignores_disabled_paid_lane(self):
        pool = [lanes_mod.Lane("good", "kilo", "x/y:free", "fam", ["build"], True),
                lanes_mod.Lane("bad", "kilo", "Qwen3.8-Max", "fam2", ["build"], False)]
        self.assertEqual(guard.enforce(pool)["enabled_free"], 1)

    def test_enforce_raises_when_no_free_lane(self):
        pool = [lanes_mod.Lane("bad", "kilo", "Qwen3.8-Max", "f", ["build"], False)]
        with self.assertRaises(guard.PaidModelRefused):
            guard.enforce(pool)

    def test_invoke_refuses_paid_model_without_spawning(self):
        """The last line of defence: even a caller that skipped enforce() cannot spend."""
        lane = lanes_mod.Lane("bad", "kilo", "Qwen3.8-Max", "f", ["build"], True)
        with tempfile.TemporaryDirectory() as tmp:
            res = lanes_mod.invoke(lane, "hello", Path(tmp), timeout_sec=5)
        self.assertEqual(res.verdict, "refused_paid")
        self.assertEqual(res.exit_code, 125)
        self.assertEqual(res.elapsed_sec, 0.0)   # proves nothing was launched

    def test_titles_strip_tier_escalation_triggers(self):
        """qoder-runner.sh:61 escalates to paid Max on these words."""
        for bad in ("[max] build", "heavy refactor", "complex task",
                    "architecture review", "MAX effort"):
            out = guard.sanitize_title(bad).lower()
            for trigger in ("[max]", "heavy", "complex", "architecture"):
                self.assertNotIn(trigger, out, f"{bad!r} -> {out!r} still has {trigger}")
            self.assertNotRegex(out, r"\bmax\b")

    def test_lane_pool_on_disk_is_all_free(self):
        pool, _ = lanes_mod.load_lanes()
        audit = guard.audit_lanes(pool)
        self.assertEqual(audit["violations"], [], "shipped lanes.yaml has a paid lane")
        self.assertGreater(audit["enabled_free"], 1)


class IntakeGate(unittest.TestCase):
    def test_rejects_task_with_no_checkable_outcome(self):
        with self.assertRaises(spec_mod.SpecError) as ctx:
            spec_mod.from_dict({"title": "Do a thing",
                                "goal": "Make the system better in some general way."})
        self.assertIn("acceptance", str(ctx.exception))

    def test_rejects_thin_goal(self):
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.from_dict({"title": "x", "goal": "fix it",
                                "deliverables": [{"path": "/tmp/x"}]})

    def test_rejects_missing_title(self):
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.from_dict({"goal": "a" * 60, "deliverables": [{"path": "/tmp/x"}]})

    def test_rejects_bad_depth(self):
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.from_dict({"title": "t", "goal": "a" * 60, "depth": 9,
                                "deliverables": [{"path": "/tmp/x"}]})

    def test_accepts_minimal_valid_spec_and_sets_profile(self):
        s = spec_mod.from_dict({
            "title": "Write a report",
            "goal": "Produce a written report that answers the stated question with evidence.",
            "depth": 4,
            "deliverables": [{"path": "/tmp/report.md", "min_bytes": 100}]})
        self.assertEqual(s.depth, 4)
        self.assertEqual(s.profile["sample_k"], 2)
        self.assertEqual(s.profile["recon_slices"], 4)

    def test_default_constraints_are_always_injected(self):
        s = spec_mod.from_dict({"title": "t", "goal": "a" * 60,
                                "deliverables": [{"path": "/tmp/x"}]})
        joined = " ".join(s.constraints).lower()
        for must in ("credential", "never send", "never deploy"):
            self.assertIn(must, joined)

    def test_brief_includes_deliverables_and_constraints(self):
        s = spec_mod.from_dict({"title": "T", "goal": "a" * 60,
                                "deliverables": [{"path": "/tmp/out.md", "min_bytes": 10}],
                                "banned_paths": ["/etc"]})
        brief = spec_mod.to_brief(s)
        self.assertIn("/tmp/out.md", brief)
        self.assertIn("/etc", brief)
        self.assertIn("Hard constraints", brief)


class Gates(unittest.TestCase):
    def test_passing_and_failing_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = gate.run_check(spec_mod.Acceptance(cmd="true", name="g"), Path(tmp))
            bad = gate.run_check(spec_mod.Acceptance(cmd="false", name="b"), Path(tmp))
        self.assertTrue(good.passed)
        self.assertFalse(bad.passed)
        self.assertIn("exit 1", bad.reason)

    def test_stdout_expectations(self):
        with tempfile.TemporaryDirectory() as tmp:
            hit = gate.run_check(spec_mod.Acceptance(
                cmd="echo HELLO", expect_stdout="HELLO", name="h"), Path(tmp))
            miss = gate.run_check(spec_mod.Acceptance(
                cmd="echo HELLO", expect_stdout="GOODBYE", name="m"), Path(tmp))
            forbid = gate.run_check(spec_mod.Acceptance(
                cmd="echo OOPS", forbid_stdout="OOPS", name="f"), Path(tmp))
        self.assertTrue(hit.passed)
        self.assertFalse(miss.passed)
        self.assertFalse(forbid.passed)

    def test_timeout_is_bounded_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = gate.run_check(spec_mod.Acceptance(
                cmd="sleep 30", timeout_sec=2, name="t"), Path(tmp))
        self.assertFalse(res.passed)
        self.assertEqual(res.exit_code, 124)


class ReceiptEnforcement(unittest.TestCase):
    """The rule that makes a zero-output run fail instead of passing."""

    def test_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Ledger(Path(tmp) / "run")
            ok, receipts = led.check_receipts(
                [{"path": str(Path(tmp) / "nope.md"), "min_bytes": 1}])
        self.assertFalse(ok)
        self.assertFalse(receipts[0].exists)

    def test_trivial_file_fails_min_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "thin.md"
            target.write_text("x")
            led = Ledger(Path(tmp) / "run")
            ok, receipts = led.check_receipts([{"path": str(target), "min_bytes": 500}])
        self.assertFalse(ok)
        self.assertTrue(receipts[0].exists)
        self.assertEqual(receipts[0].bytes, 1)

    def test_real_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "real.md"
            target.write_text("y" * 600)
            led = Ledger(Path(tmp) / "run")
            ok, _ = led.check_receipts([{"path": str(target), "min_bytes": 500}])
        self.assertTrue(ok)

    def test_ledger_records_and_replays_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Ledger(Path(tmp) / "run")
            self.assertFalse(led.is_stage_done("plan"))
            led.stage_done("plan", parts=3)
            self.assertTrue(led.is_stage_done("plan"))
            self.assertEqual(led.stage_result("plan")["parts"], 3)
            self.assertIn("plan", led.summary()["stages_done"])


class DraftGuardrails(unittest.TestCase):
    """The front door must never produce a spec the engine would later refuse."""

    def setUp(self):
        from engine import draft as draft_mod
        self.d = draft_mod
        self.workdir = Path("/tmp/eng-test-work/task")

    def test_always_banned_paths_are_forced_in(self):
        out = self.d._normalise({"title": "t", "banned_paths": []}, self.workdir, "req")
        for path in self.d.ALWAYS_BANNED:
            self.assertIn(path, out["banned_paths"])

    def test_workdir_is_always_authorized(self):
        out = self.d._normalise({"title": "t"}, self.workdir, "req")
        self.assertEqual(out["authorized_paths"][0], str(self.workdir))

    def test_invented_context_sources_are_dropped(self):
        out = self.d._normalise({"title": "t", "context_sources": [
            "/definitely/not/a/real/path/xyz", str(Path(__file__))]}, self.workdir, "req")
        self.assertEqual(out["context_sources"], [str(Path(__file__))])

    def test_deliverables_outside_workdir_are_caught(self):
        draft = {"deliverables": [{"path": f"{self.workdir}/ok.md"},
                                  {"path": "/home/ubuntu/aaryas-life/agents/CHARTER.md"}]}
        self.assertEqual(self.d._outside_workdir(draft, self.workdir),
                         ["/home/ubuntu/aaryas-life/agents/CHARTER.md"])

    def test_title_and_id_are_normalised(self):
        out = self.d._normalise({"title": "  Build a Thing!  "}, self.workdir, "req")
        self.assertEqual(out["title"], "Build a Thing!")
        self.assertEqual(out["id"], "build-a-thing")

    def test_saved_spec_round_trips_through_the_intake_gate(self):
        spec = self.d._normalise({
            "title": "Write a report",
            "goal": "Produce a written report that answers the question with evidence.",
            "depth": 2,
            "deliverables": [{"path": f"{self.workdir}/report.md", "min_bytes": 400}],
            "acceptance": [{"name": "has_heading", "cmd": "true"}]},
            self.workdir, "write a report")
        with tempfile.TemporaryDirectory() as tmp:
            path = self.d.save_spec(spec, Path(tmp))
            loaded = spec_mod.load(path)
        self.assertEqual(loaded.title, "Write a report")
        self.assertEqual(loaded.depth, 2)


class StreamingInvocation(unittest.TestCase):
    """invoke() against fake CLIs that reproduce the real failure shapes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = dict(lanes_mod.CLI_PATHS)
        self.saved_slots = lanes_mod.SLOTS_DIR
        lanes_mod.SLOTS_DIR = self.root / "slots"
        lanes_mod.COST_BREAKER.reset()
        lanes_mod.reset_cooldowns()

    def tearDown(self):
        lanes_mod.CLI_PATHS.clear()
        lanes_mod.CLI_PATHS.update(self.saved)
        lanes_mod.SLOTS_DIR = self.saved_slots
        lanes_mod.COST_BREAKER.reset()
        lanes_mod.reset_cooldowns()
        self.tmp.cleanup()

    def _fake(self, body: str) -> lanes_mod.Lane:
        exe = self.root / "fakecli"
        exe.write_text("#!/usr/bin/env bash\n" + body + "\n")
        exe.chmod(0o755)
        lanes_mod.CLI_PATHS["kilo"] = str(exe)
        return lanes_mod.Lane("fake", "kilo", "fake/model:free", "fam", ["build"], True)

    def test_finished_lane_that_hangs_is_ended_by_the_stop_event(self):
        """Real behaviour seen live: the work is done, the CLI never exits."""
        lane = self._fake(
            "echo '{\"type\":\"text\",\"part\":{\"text\":\"all done\"}}'\n"
            "echo '{\"type\":\"step_finish\",\"part\":{\"reason\":\"stop\",\"cost\":0}}'\n"
            "sleep 300")
        start = time.monotonic()
        res = lanes_mod.invoke(lane, "go", self.root / "w1", timeout_sec=120, idle_sec=60)
        took = time.monotonic() - start
        self.assertEqual(res.verdict, "ok")
        self.assertEqual(res.ended_by, "stop_event")
        self.assertEqual(res.text, "all done")
        self.assertLess(took, 30, "should end within the stop grace, not the timeout")

    def test_silent_lane_is_ended_by_the_idle_cutoff(self):
        """Real behaviour seen live: quota exhausted, no events, process alive forever."""
        lane = self._fake("sleep 300")
        start = time.monotonic()
        res = lanes_mod.invoke(lane, "go", self.root / "w2", timeout_sec=120, idle_sec=3)
        self.assertEqual(res.ended_by, "idle")
        self.assertEqual(res.verdict, "hang")
        self.assertLess(time.monotonic() - start, 30)

    def test_intermediate_tool_steps_do_not_end_the_call(self):
        lane = self._fake(
            "echo '{\"type\":\"step_finish\",\"part\":{\"reason\":\"tool-calls\",\"cost\":0}}'\n"
            "sleep 12\n"
            "echo '{\"type\":\"text\",\"part\":{\"text\":\"second step\"}}'\n"
            "echo '{\"type\":\"step_finish\",\"part\":{\"reason\":\"stop\",\"cost\":0}}'")
        res = lanes_mod.invoke(lane, "go", self.root / "w3", timeout_sec=120, idle_sec=60)
        self.assertEqual(res.text, "second step")
        self.assertEqual(res.verdict, "ok")

    def test_quota_error_on_stderr_cools_the_lane_down(self):
        lane = self._fake("echo 'AI_APICallError: Free usage limit reached' >&2; exit 1")
        res = lanes_mod.invoke(lane, "go", self.root / "w4", timeout_sec=60, idle_sec=30)
        self.assertEqual(res.verdict, "quota")
        self.assertTrue(lanes_mod.is_cooling("fake"))

    def test_billed_call_is_flagged_and_trips_the_breaker(self):
        lane = self._fake(
            "echo '{\"type\":\"text\",\"part\":{\"text\":\"hi\"}}'\n"
            "echo '{\"type\":\"step_finish\",\"part\":{\"reason\":\"stop\",\"cost\":0.01}}'")
        res = lanes_mod.invoke(lane, "go", self.root / "w5", timeout_sec=60, idle_sec=30)
        self.assertEqual(res.verdict, "paid_cost_detected")
        self.assertTrue(lanes_mod.COST_BREAKER.tripped)

    def test_permission_files_are_written_per_mode(self):
        lane = self._fake("echo '{\"type\":\"text\",\"part\":{\"text\":\"x\"}}'")
        lanes_mod.invoke(lane, "go", self.root / "ro", timeout_sec=30, mode="ro")
        lanes_mod.invoke(lane, "go", self.root / "rw", timeout_sec=30, mode="rw", web=True)
        ro = json.loads((self.root / "ro" / "opencode.json").read_text())["permission"]
        rw = json.loads((self.root / "rw" / "kilo.json").read_text())["permission"]
        self.assertEqual((ro["edit"], ro["bash"], ro["webfetch"]), ("deny", "deny", "deny"))
        self.assertEqual(rw["edit"], "allow")
        self.assertEqual(rw["webfetch"], "allow")
        for must_deny in ("sudo *", "systemctl *", "git push*", "paperclipai *", "crontab *"):
            self.assertEqual(rw["bash"].get(must_deny), "deny")

    def test_platform_credentials_never_reach_a_lane(self):
        lane = self._fake('echo "{\\"type\\":\\"text\\",\\"part\\":{\\"text\\":\\"key=[${PAPERCLIP_API_KEY:-none}]\\"}}"')
        os.environ["PAPERCLIP_API_KEY"] = "pcp_supersecretvalue123"
        try:
            res = lanes_mod.invoke(lane, "go", self.root / "w6", timeout_sec=30)
        finally:
            del os.environ["PAPERCLIP_API_KEY"]
        self.assertIn("key=[none]", res.text)


class GlobalSlots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = lanes_mod.SLOTS_DIR
        lanes_mod.SLOTS_DIR = Path(self.tmp.name)

    def tearDown(self):
        lanes_mod.SLOTS_DIR = self.saved
        self.tmp.cleanup()

    def test_semaphore_caps_concurrent_lanes_and_releases(self):
        a = lanes_mod.LaneSlot(2, wait_sec=2).__enter__()
        b = lanes_mod.LaneSlot(2, wait_sec=2).__enter__()
        self.assertEqual(lanes_mod.slots_in_use(2), 2)
        with self.assertRaises(TimeoutError):
            lanes_mod.LaneSlot(2, wait_sec=3).__enter__()
        a.__exit__(None, None, None)
        c = lanes_mod.LaneSlot(2, wait_sec=2).__enter__()
        self.assertIsNotNone(c.index)
        b.__exit__(None, None, None)
        c.__exit__(None, None, None)
        self.assertEqual(lanes_mod.slots_in_use(2), 0)


class LoadSpreading(unittest.TestCase):
    def setUp(self):
        lanes_mod.reset_cooldowns()
        self.pool = [lanes_mod.Lane(f"l{i}", "kilo", f"m/{i}:free", f"f{i}", ["build"], True)
                     for i in range(3)]
        self.health = {"live": ["l0", "l1", "l2"]}

    def tearDown(self):
        lanes_mod.reset_cooldowns()

    def test_successive_picks_rotate_across_lanes(self):
        seen = {lanes_mod.pick(self.pool, self.health, "build-spread", 1)[0].id
                for _ in range(3)}
        self.assertEqual(seen, {"l0", "l1", "l2"})

    def test_cooling_lane_is_avoided_while_alternatives_exist(self):
        lanes_mod.cool_down("l0", 60)
        lanes_mod.cool_down("l1", 60)
        for _ in range(4):
            self.assertEqual(lanes_mod.pick(self.pool, self.health, "build-cool", 1)[0].id, "l2")

    def test_cooling_lanes_are_still_used_when_nothing_else_is_live(self):
        for lane in ("l0", "l1", "l2"):
            lanes_mod.cool_down(lane, 60)
        self.assertEqual(len(lanes_mod.pick(self.pool, self.health, "build-all", 1)), 1)


def _write_kit(root: Path, name: str = "research") -> Path:
    d = root / name
    (d / "skills").mkdir(parents=True)
    (d / "runbooks").mkdir()
    (d / "tools").mkdir()
    (d / "CHARTER.md").write_text("# Charter\n" + "Mission text. " * 120)
    (d / f"runbooks/{name}.md").write_text("# Runbook\n" + "Step text. " * 140)
    (d / "skills/a.md").write_text("# Skill A\n" + "Do this precisely. " * 40)
    (d / "skills/b.md").write_text("# Skill B\n" + "Then do that. " * 40)
    (d / "tools/check.py").write_text(
        "import sys\nsys.exit(0 if open(sys.argv[1]).read().strip() else 1)\n")
    (d / "tools/test_check.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n"
        "        self.assertTrue(True)\n")
    (d / "profile.yaml").write_text(f"""
department: {name}
name: Research
mission: Produce cited memos that answer sharp questions for the Owner.
agents:
  - name: research-1
    depth: 2
  - name: research-2
    depth: 4
output_kind: memo
work_root: {root}/work
may: [research and recommend]
never: [execute the plans it recommends]
constraints: [Every claim is cited or marked INFERENCE.]
skills: [skills/a.md, skills/b.md]
tools:
  - path: tools/check.py
    usage: python3 {{dept}}/tools/check.py <file>
    purpose: fails on an empty file
acceptance_templates:
  - name: nonempty
    applies_to: "*.md"
    cmd: python3 {{dept}}/tools/check.py {{deliverable}}
lane_policy:
  web: true
""")
    return d


class DepartmentKits(unittest.TestCase):
    def setUp(self):
        from engine import departments as dept_mod
        self.dm = dept_mod
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = dept_mod.DEPARTMENTS_ROOT
        dept_mod.DEPARTMENTS_ROOT = self.root
        self.kit = _write_kit(self.root)

    def tearDown(self):
        self.dm.DEPARTMENTS_ROOT = self.saved
        self.tmp.cleanup()

    def test_valid_kit_passes_validation_including_tool_tests(self):
        self.assertEqual(self.dm.validate(self.kit), [])

    def test_validation_catches_missing_pieces(self):
        (self.kit / "skills/b.md").unlink()
        (self.kit / "tools/test_check.py").unlink()
        problems = " ".join(self.dm.validate(self.kit))
        self.assertIn("skill missing: skills/b.md", problems)
        self.assertIn("no test file", problems)

    def test_tool_that_reads_credentials_is_rejected(self):
        (self.kit / "tools/check.py").write_text("open('/home/ubuntu/.config/x.env')\n")
        self.assertTrue(any("forbidden" in p for p in self.dm.validate(self.kit)))

    def test_agent_resolution_and_depth(self):
        prof = self.dm.for_agent("research-2")
        self.assertEqual(prof.department, "research")
        self.assertEqual(prof.agent_depth("research-2"), 4)
        self.assertIsNone(self.dm.for_agent("nobody"))

    def test_spec_with_department_gets_gates_constraints_web_and_brief(self):
        s = spec_mod.from_dict({
            "title": "Memo on free hosting", "department": "research",
            "goal": "Answer which free static hosting fits the club, with cited evidence.",
            "deliverables": [{"path": "/tmp/x/memo.md", "min_bytes": 300}]})
        names = [a.name for a in s.acceptance]
        self.assertIn("dept:nonempty:memo.md", names)
        self.assertIn("Every claim is cited or marked INFERENCE.", s.constraints)
        self.assertTrue(s.web)
        brief = spec_mod.to_brief(s)
        self.assertIn("## Department: Research", brief)
        self.assertIn("Do this precisely.", brief)
        self.assertIn(str(self.kit / "tools/check.py"), brief)

    def test_unknown_department_is_an_intake_error(self):
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.from_dict({"title": "t", "department": "nope", "goal": "a" * 60,
                                "deliverables": [{"path": "/tmp/x"}]})


class BridgeLoopGuard(unittest.TestCase):
    def setUp(self):
        from engine import bridge
        self.b = bridge
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = bridge.STATE_DIR
        bridge.STATE_DIR = Path(self.tmp.name)

    def tearDown(self):
        self.b.STATE_DIR = self.saved
        self.tmp.cleanup()

    def test_finished_issue_is_skipped_until_someone_touches_it(self):
        issue = {"id": "i1", "updatedAt": "2026-10-30T10:00:00Z"}
        self.assertFalse(self.b.already_handled(issue))
        self.b.remember("i1", "DONE", "2026-10-30T10:00:00Z", "/tmp/run")
        self.assertTrue(self.b.already_handled(issue))
        touched = {"id": "i1", "updatedAt": "2026-10-30T11:30:00Z"}
        self.assertFalse(self.b.already_handled(touched))

    def test_inbox_pick_prefers_priority_then_age_and_skips_handled(self):
        class FakePC:
            def inbox(self):
                return [{"id": "low", "status": "todo", "priority": "low",
                         "updatedAt": "2026-10-01"},
                        {"id": "high-new", "status": "todo", "priority": "high",
                         "updatedAt": "2026-10-29"},
                        {"id": "high-old", "status": "in_progress", "priority": "high",
                         "updatedAt": "2026-10-02"},
                        {"id": "done", "status": "done", "priority": "critical",
                         "updatedAt": "2026-10-01"}]

            def issue(self, iid):
                return {"id": iid, "updatedAt": "u-" + iid}

        os.environ.pop("PAPERCLIP_TASK_ID", None)
        self.assertEqual(self.b.pick_issue(FakePC(), None)["id"], "high-old")
        self.b.remember("high-old", "DONE", "u-high-old", "/tmp/r")
        self.assertEqual(self.b.pick_issue(FakePC(), None)["id"], "high-new")


class QoderLane(unittest.TestCase):
    """qodercli is free only by offer, so it is held to a narrower rule."""

    def setUp(self):
        from engine import offers
        self.offers = offers
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = offers.STATE
        offers.STATE = Path(self.tmp.name)
        self.lane = lanes_mod.Lane("qwen", "qodercli", "Qwen3.8-Flash", "qwen",
                                   ["review"], True, readonly=True)

    def tearDown(self):
        self.offers.STATE = self.saved
        self.tmp.cleanup()

    def _page(self, text):
        return lambda url: text

    def test_offer_open_when_every_phrase_present(self):
        page = "Qwen3.8-Flash remains free ... 0.0 ... We will announce the end date"
        ok, why = self.offers.is_open("qodercli:Qwen3.8-Flash",
                                      fetcher=self._page(page))
        self.assertTrue(ok, why)

    def test_offer_closed_when_a_phrase_disappears(self):
        ok, why = self.offers.is_open("qodercli:Qwen3.8-Flash",
                                      fetcher=self._page("Qwen3.8-Flash 0.0 no longer free"))
        self.assertFalse(ok)
        self.assertIn("remains free", why)

    def test_fetch_failure_fails_closed(self):
        def boom(url):
            raise OSError("network down")
        ok, why = self.offers.is_open("qodercli:Qwen3.8-Flash", fetcher=boom)
        self.assertFalse(ok)
        self.assertIn("network down", why)

    def test_stale_check_is_refused_without_refresh(self):
        self.offers.check("qodercli:Qwen3.8-Flash",
                          fetcher=self._page("Qwen3.8-Flash remains free 0.0 "
                                             "We will announce the end date"))
        p = self.offers.STATE / "qodercli_Qwen3.8-Flash.json"
        state = json.loads(p.read_text())
        state["checked_at"] = time.time() - 48 * 3600
        p.write_text(json.dumps(state))
        ok, why = self.offers.is_open("qodercli:Qwen3.8-Flash", refresh=False)
        self.assertFalse(ok)
        self.assertIn("stale", why)

    def test_paid_qoder_models_are_refused(self):
        for model in ("Auto", "Ultimate", "Qwen3.8-Max", "Efficient", "Kimi-K3.1-Pro"):
            lane = lanes_mod.Lane("x", "qodercli", model, "f", ["review"], True)
            ok, why = guard.is_free_lane(lane, refresh=False)
            self.assertFalse(ok, model)
            self.assertIn("no verified free offer", why)

    def test_readonly_lane_cannot_take_a_builder_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = lanes_mod.invoke(self.lane, "build something", Path(tmp), 30, mode="rw")
        self.assertEqual(res.verdict, "refused_mode")
        self.assertEqual(res.elapsed_sec, 0.0)

    def test_readonly_lane_excluded_from_builder_picks(self):
        pool = [self.lane,
                lanes_mod.Lane("b", "kilo", "m/b:free", "fam", ["build", "review"], True)]
        health = {"live": ["qwen", "b"]}
        picked = lanes_mod.pick(pool, health, "build", count=2)
        self.assertEqual([p.id for p in picked], ["b"])

    def test_command_uses_print_and_denies_credential_reads(self):
        cmd = lanes_mod.build_command(self.lane, "/usr/bin/qodercli", "hi",
                                      Path("/tmp/w"), "ro", "t", 19)
        self.assertIn("-p", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("dont_ask", cmd)
        joined = " ".join(cmd)
        self.assertIn("/.config/**", joined)
        self.assertIn("/.ssh/**", joined)
        self.assertNotIn("--dangerously-skip-permissions", cmd)


class QoderStreamParsing(unittest.TestCase):
    def _stream(self, credits=0, models=("qfmodel",), denied=False):
        lines = [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "c1", "name": "Read",
                 "input": {"file_path": "/home/ubuntu/.ssh/id_rsa"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "c1", "is_error": True,
                 "content": "needs approval"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "the answer"}]}},
            {"type": "result", "total_credits": credits, "total_cost_usd": 0,
             "modelUsage": {m: {"credits": 0, "costUSD": 0} for m in models},
             "is_error": False, "result": "the answer"},
        ]
        if denied:
            lines.insert(3, {"type": "system", "subtype": "permission_denied"})
        return "\n".join(json.dumps(x) for x in lines)

    def test_text_tools_and_zero_cost(self):
        ev = lanes_mod.parse_qoder_events(self._stream())
        self.assertEqual(ev["text"], "the answer")
        self.assertEqual(ev["tools"], {"Read": 1})
        self.assertEqual(ev["cost"], 0.0)
        self.assertEqual(ev["model_keys"], ["qfmodel"])

    def test_credential_read_attempt_is_recorded_with_its_outcome(self):
        ev = lanes_mod.parse_qoder_events(self._stream())
        self.assertEqual(len(ev["sensitive"]), 1)
        self.assertEqual(ev["sensitive"][0]["status"], "denied")
        self.assertEqual(ev["sensitive"][0]["tool"], "Read")

    def test_completed_credential_read_is_marked_completed(self):
        stream = self._stream().replace('"is_error": true', '"is_error": false')
        ev = lanes_mod.parse_qoder_events(stream)
        self.assertEqual(ev["sensitive"][0]["status"], "completed")

    def test_credits_are_counted_as_cost(self):
        self.assertGreater(lanes_mod.parse_qoder_events(self._stream(credits=3))["cost"], 0)

    def test_unexpected_model_key_is_visible(self):
        ev = lanes_mod.parse_qoder_events(self._stream(models=("qmodel_38max",)))
        self.assertEqual(ev["model_keys"], ["qmodel_38max"])


class BenchScoring(unittest.TestCase):
    def setUp(self):
        from engine import bench, bench_tasks
        self.bench = bench
        self.task = bench_tasks.by_id("interval-merge")

    def test_hidden_tests_are_not_in_the_spec_a_lane_sees(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = self.bench.build_spec(self.task, Path(tmp), 3)
        blob = json.dumps(spec)
        self.assertNotIn("test_no_mutation", blob)
        self.assertNotIn("hidden_tests", blob)
        self.assertIn("merge_intervals", blob)

    def test_missing_solution_scores_zero_not_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            passed, total, details = self.bench.run_hidden_tests(self.task, Path(tmp))
        self.assertEqual(passed, 0)
        self.assertGreater(total, 5)
        self.assertIn("missing", details[0]["why"])

    def test_correct_solution_scores_full(self):
        solution = (
            "def merge_intervals(intervals):\n"
            "    if not intervals:\n"
            "        return []\n"
            "    ordered = sorted(intervals)\n"
            "    out = [tuple(ordered[0])]\n"
            "    for start, end in ordered[1:]:\n"
            "        last_start, last_end = out[-1]\n"
            "        if start <= last_end:\n"
            "            out[-1] = (last_start, max(last_end, end))\n"
            "        else:\n"
            "            out.append((start, end))\n"
            "    return out\n")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "solution.py").write_text(solution)
            passed, total, details = self.bench.run_hidden_tests(self.task, Path(tmp))
        self.assertEqual(passed, total)
        self.assertGreaterEqual(total, 9)

    def test_wrong_solution_scores_partial(self):
        """A plausible but incorrect answer must not pass: touching intervals unmerged."""
        solution = (
            "def merge_intervals(intervals):\n"
            "    out = []\n"
            "    for start, end in sorted(intervals):\n"
            "        if out and start < out[-1][1]:\n"
            "            out[-1] = (out[-1][0], max(out[-1][1], end))\n"
            "        else:\n"
            "            out.append((start, end))\n"
            "    return out\n")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "solution.py").write_text(solution)
            passed, total, _ = self.bench.run_hidden_tests(self.task, Path(tmp))
        self.assertLess(passed, total)
        self.assertGreater(passed, 0)

    def test_every_benchmark_task_has_real_hidden_tests(self):
        from engine import bench_tasks
        for task in bench_tasks.TASKS:
            self.assertGreaterEqual(len(re.findall(r"def test_", task["hidden_tests"])), 6,
                                    task["id"])
            self.assertIn("solution.py", task["statement"])


class HiddenTestAttribution(unittest.TestCase):
    """Regression: the scorer used to regex-parse `unittest -v` text. A test that writes
    anything to stderr between its own name and its verdict breaks that line, and the
    verdict is silently lost. On expr-eval the unclosed file in test_no_eval_shortcut
    did exactly this, so a real 10/10 was reported as 9/10 and a real 1/10 as 0/10."""

    def setUp(self):
        from engine import bench
        self.bench = bench

    NOISY = (
        "import sys, unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_alpha(self):\n"
        "        sys.stderr.write('ResourceWarning: unclosed file\\n')\n"
        "        sys.stderr.flush()\n"
        "        self.assertEqual(1, 1)\n"
        "    def test_beta(self):\n"
        "        self.assertEqual(2, 2)\n")

    TASK = {"id": "attr", "statement": "def solve(x): ...", "hidden_tests": NOISY}

    def test_noise_inside_a_test_does_not_erase_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "solution.py").write_text("def solve(x):\n    return x\n")
            passed, total, details = self.bench.run_hidden_tests(self.TASK, Path(tmp))
        self.assertEqual(total, 2, "both tests must be counted")
        self.assertEqual(passed, 2, "a test that prints during its run still passes")
        self.assertEqual(sorted(d["test"] for d in details), ["test_alpha", "test_beta"])

    def test_the_old_text_parse_would_have_lost_that_pass(self):
        """Proves the regression is real: the same output fed to _TEST_LINE drops it."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "test_hidden.py").write_text(self.NOISY)
            proc = subprocess.run([sys.executable, "-m", "unittest", "test_hidden", "-v"],
                                  cwd=tmp, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        found = {m.group(1) for m in self.bench._TEST_LINE.finditer(out)}
        self.assertNotIn("test_alpha", found,
                         "the legacy parse must demonstrably lose the noisy test")

    def test_a_failing_test_is_attributed_by_name(self):
        task = dict(self.TASK, hidden_tests=(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_alpha(self):\n        self.assertEqual(1, 1)\n"
            "    def test_beta(self):\n        self.assertEqual(1, 2)\n"))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "solution.py").write_text("x = 1\n")
            passed, total, details = self.bench.run_hidden_tests(task, Path(tmp))
        self.assertEqual((passed, total), (1, 2))
        self.assertEqual([d["test"] for d in details if d["result"] == "FAIL"],
                         ["test_beta"])

    def test_unimportable_test_module_scores_zero_not_silent(self):
        task = dict(self.TASK, hidden_tests=(
            "from solution import nothing_here\n"
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_alpha(self):\n        self.assertTrue(True)\n"))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "solution.py").write_text("x = 1\n")
            passed, total, details = self.bench.run_hidden_tests(task, Path(tmp))
        self.assertEqual(passed, 0)
        self.assertGreaterEqual(total, 1)
        self.assertTrue(all(d["result"] != "ok" for d in details))


class HealthCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = lanes_mod.HEALTH_CACHE
        lanes_mod.HEALTH_CACHE = Path(self.tmp.name)
        lanes_mod.reset_cooldowns()
        self.pool = [lanes_mod.Lane("a", "kilo", "m/a:free", "f", ["build"], True)]

    def tearDown(self):
        lanes_mod.HEALTH_CACHE = self.saved
        lanes_mod.reset_cooldowns()
        self.tmp.cleanup()

    def test_second_probe_uses_the_cache(self):
        calls = []

        def fake_invoke(lane, prompt, workdir, timeout_sec, **kw):
            calls.append(lane.id)
            return lanes_mod.LaneResult(lane.id, lane.model, "ok", 0, 1.0, text="OK")

        saved = lanes_mod.invoke
        lanes_mod.invoke = fake_invoke
        try:
            first = lanes_mod.probe(self.pool, workdir=Path(self.tmp.name) / "p")
            second = lanes_mod.probe(self.pool, workdir=Path(self.tmp.name) / "p")
        finally:
            lanes_mod.invoke = saved
        self.assertFalse(first["from_cache"])
        self.assertTrue(second["from_cache"])
        self.assertEqual(len(calls), 1, "the second probe should not call any model")
        self.assertEqual(second["live"], ["a"])

    def test_expired_cache_is_reprobed(self):
        def fake_invoke(lane, prompt, workdir, timeout_sec, **kw):
            return lanes_mod.LaneResult(lane.id, lane.model, "ok", 0, 1.0, text="OK")

        saved = lanes_mod.invoke
        lanes_mod.invoke = fake_invoke
        try:
            lanes_mod.probe(self.pool, workdir=Path(self.tmp.name) / "p")
            again = lanes_mod.probe(self.pool, workdir=Path(self.tmp.name) / "p",
                                    cache_sec=0)
        finally:
            lanes_mod.invoke = saved
        self.assertFalse(again["from_cache"])

    def test_all_dead_result_is_not_cached(self):
        def dead(lane, prompt, workdir, timeout_sec, **kw):
            return lanes_mod.LaneResult(lane.id, lane.model, "quota", 1, 1.0)

        saved = lanes_mod.invoke
        lanes_mod.invoke = dead
        try:
            first = lanes_mod.probe(self.pool, workdir=Path(self.tmp.name) / "p")
            second = lanes_mod.probe(self.pool, workdir=Path(self.tmp.name) / "p")
        finally:
            lanes_mod.invoke = saved
        self.assertEqual(first["live"], [])
        self.assertFalse(second["from_cache"], "a dead pool must be retried, not cached")

    def test_cooled_lane_is_dropped_from_a_cached_result(self):
        def fake_invoke(lane, prompt, workdir, timeout_sec, **kw):
            return lanes_mod.LaneResult(lane.id, lane.model, "ok", 0, 1.0, text="OK")

        saved = lanes_mod.invoke
        lanes_mod.invoke = fake_invoke
        try:
            lanes_mod.probe(self.pool, workdir=Path(self.tmp.name) / "p")
            lanes_mod.cool_down("a", 60)
            second = lanes_mod.probe(self.pool, workdir=Path(self.tmp.name) / "p")
        finally:
            lanes_mod.invoke = saved
        self.assertNotIn("a", second["live"])


class VerifyCommandValidation(unittest.TestCase):
    """Regression: a planner wrote a Python one-liner with semicolon-separated `for`
    and `try` blocks. It was a SyntaxError, so a fully correct solution was scored as
    a failure and the repair loop chased a phantom."""

    def setUp(self):
        from engine import execute
        self.ex = execute

    def test_semicolon_compound_statement_is_rejected(self):
        bad = ("cd /tmp && python3 -c 'import solution; ok = True; "
               "for c in [\"\", \"(\"]: try: solution.evaluate(c); ok = False; "
               "except ValueError: pass; print(ok)'")
        ok, why = self.ex.validate_verify_cmd(bad)
        self.assertFalse(ok)
        self.assertIn("does not compile", why)

    def test_simple_python_one_liner_is_accepted(self):
        ok, why = self.ex.validate_verify_cmd(
            'cd /tmp && python3 -c "import json; print(json.dumps({}))"')
        self.assertTrue(ok, why)

    def test_unittest_invocation_is_accepted(self):
        ok, why = self.ex.validate_verify_cmd("cd /tmp && python3 -m unittest test_x -v")
        self.assertTrue(ok, why)

    def test_shell_syntax_error_is_rejected(self):
        ok, why = self.ex.validate_verify_cmd("if [ -f x ]; then")
        self.assertFalse(ok)
        self.assertIn("shell syntax", why)

    def test_empty_command_is_rejected(self):
        self.assertFalse(self.ex.validate_verify_cmd("")[0])
        self.assertFalse(self.ex.validate_verify_cmd("   ")[0])

    def test_broken_check_does_not_condemn_a_good_part(self):
        """The part must still pass on its deliverables when its check cannot run."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "solution.py"
            good.write_text("def f(x):\n    return x + 1\n" * 20)
            led = Ledger(root / "run")
            part = {"id": "p", "deliverables": [{"path": str(good), "min_bytes": 100}],
                    "verify_cmd": "python3 -c 'for i in x: pass'"}
            ok, receipts, checks = self.ex._verify_part(part, led, root, "build.p")
        self.assertTrue(ok, "a malformed check must not fail otherwise-good work")
        self.assertTrue(receipts[0].ok)
        self.assertEqual(checks, [])
        warnings = [e for e in led.events("warning") if "verify_cmd discarded" in e.get("message", "")]
        self.assertEqual(len(warnings), 1, "the discarded check must be recorded")

    def test_working_check_still_gates_the_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "solution.py"
            f.write_text("def f(x):\n    return x + 1\n" * 20)
            led = Ledger(root / "run")
            part = {"id": "p", "deliverables": [{"path": str(f), "min_bytes": 100}],
                    "verify_cmd": f"cd {root} && python3 -c \"import solution; assert solution.f(1)==2\""}
            ok, _, checks = self.ex._verify_part(part, led, root, "build.p")
            self.assertTrue(ok)
            self.assertEqual(len(checks), 1)
            part["verify_cmd"] = f"cd {root} && python3 -c \"import solution; assert solution.f(1)==99\""
            ok2, _, _ = self.ex._verify_part(part, led, root, "build.p2")
            self.assertFalse(ok2, "a valid failing check must still fail the part")


class ReviewerSeesGates(unittest.TestCase):
    """Regression: the reviewer returned APPROVE with no findings while the engine's
    own check on the same part had failed. It was never shown the gate output."""

    def test_gate_results_include_failures_and_transcripts(self):
        from engine import execute
        with tempfile.TemporaryDirectory() as tmp:
            led = Ledger(Path(tmp))
            led.event("gate", stage="build.widget", check="verify:widget",
                      passed=False, reason="exit 1, expected 0")
            util.write_text(led.dir / "gates" / "build.widget.verify-widget.txt",
                            "$ python3 check.py\nAssertionError: wrong answer\n")
            led.event("warning", stage="build.widget", part="widget",
                      message="planner verify_cmd discarded: it cannot run",
                      reason="python payload does not compile")
            text = execute._gate_results(led, "widget")
        self.assertIn("FAIL verify:widget", text)
        self.assertIn("AssertionError: wrong answer", text)
        self.assertIn("verify_cmd discarded", text)

    def test_no_gates_says_so_rather_than_looking_clean(self):
        from engine import execute
        with tempfile.TemporaryDirectory() as tmp:
            text = execute._gate_results(Ledger(Path(tmp)), "absent")
        self.assertIn("no checks", text)

    def test_review_prompt_asks_reviewer_to_respect_a_failing_check(self):
        from engine import execute
        self.assertIn("{gate_results}", execute.REVIEW_PROMPT)
        self.assertIn("outranks your own impression", execute.REVIEW_PROMPT)


class Redaction(unittest.TestCase):
    def test_secrets_are_stripped_from_stored_artifacts(self):
        samples = [
            ("API_KEY=abcdef123456", "abcdef123456"),
            ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
            ("nvapi-ABCDEFGH12345678", "ABCDEFGH12345678"),
            ("postgres://user:hunter2secret@host/db", "hunter2secret"),
            ("token: zyxwvu987654", "zyxwvu987654"),
        ]
        for raw, secret in samples:
            self.assertNotIn(secret, util.redact(raw), f"leaked from {raw!r}")

    def test_write_text_redacts_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.md"
            util.write_text(path, "password=supersecretvalue")
            self.assertNotIn("supersecretvalue", path.read_text())


class JsonRecovery(unittest.TestCase):
    """Models wrap JSON in prose and fences; the parser must still recover it."""

    def test_plain(self):
        self.assertEqual(_parse_json_reply('{"a": 1}')["a"], 1)

    def test_fenced(self):
        self.assertEqual(_parse_json_reply('```json\n{"a": 2}\n```')["a"], 2)

    def test_prose_wrapped(self):
        text = 'Sure, here is the plan:\n{"parts": [{"id": "x"}]}\nHope that helps.'
        self.assertEqual(_parse_json_reply(text)["parts"][0]["id"], "x")

    def test_nested_braces(self):
        text = 'out: {"a": {"b": {"c": 3}}} done'
        self.assertEqual(_parse_json_reply(text)["a"]["b"]["c"], 3)

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_json_reply("no json at all"))
        self.assertIsNone(_parse_json_reply(""))


class LanePicking(unittest.TestCase):
    def setUp(self):
        self.pool = [
            lanes_mod.Lane("a", "kilo", "m/a:free", "famA", ["build", "review"], True),
            lanes_mod.Lane("b", "kilo", "m/b:free", "famA", ["build"], True),
            lanes_mod.Lane("c", "kilo", "m/c:free", "famB", ["review"], True),
            lanes_mod.Lane("d", "kilo", "m/d:free", "famC", ["build"], True),
        ]
        self.health = {"live": ["a", "b", "c", "d"]}

    def test_prefers_family_diversity(self):
        picked = lanes_mod.pick(self.pool, self.health, "build", count=2)
        self.assertEqual(len({p.family for p in picked}), 2)

    def test_excludes_family_for_independent_review(self):
        picked = lanes_mod.pick(self.pool, self.health, "review", count=1,
                                exclude_families={"famA"})
        self.assertEqual(picked[0].id, "c")

    def test_only_live_lanes_are_eligible(self):
        picked = lanes_mod.pick(self.pool, {"live": ["c"]}, "build", count=2)
        self.assertEqual([p.id for p in picked], ["c"])   # role falls back, liveness does not

    def test_no_live_lane_yields_nothing(self):
        self.assertEqual(lanes_mod.pick(self.pool, {"live": []}, "build", 1), [])


class LaneResultClassification(unittest.TestCase):
    def test_quota_exhaustion_is_detected_from_stderr(self):
        self.assertEqual(
            lanes_mod.classify(124, "", [], "AI_APICallError: Free usage limit reached"),
            "quota")

    def test_paid_funds_error_is_detected(self):
        self.assertEqual(
            lanes_mod.classify(1, "", [], "Upstream request failed: Insufficient account funds"),
            "no_funds")

    def test_hang_is_detected(self):
        self.assertEqual(lanes_mod.classify(124, "", [], ""), "hang")

    def test_clean_run_is_ok(self):
        self.assertEqual(lanes_mod.classify(0, "hi", [], ""), "ok")

    def test_clean_exit_without_text_is_empty_not_ok(self):
        self.assertEqual(lanes_mod.classify(0, "", [], ""), "empty")

    def test_quota_text_inside_tool_output_is_not_misclassified(self):
        """Regression: the first live run marked 3 working recon lanes as 'quota'
        because they had read a receipt that quotes the quota error string."""
        stream = "\n".join([
            json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": "read",
                        "state": {"status": "completed",
                                  "output": "AI_APICallError: Free usage limit reached"}}}),
            json.dumps({"type": "text", "part": {"type": "text",
                        "text": "### FACTS\n- the receipt quotes a quota error"}}),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish",
                        "reason": "stop", "cost": 0}}),
        ])
        ev = lanes_mod.parse_events(stream)
        self.assertEqual(lanes_mod.classify(0, ev["text"], ev["errors"], ""), "ok")

    def test_reply_contains_model_text_only_not_tool_output(self):
        """Regression: tool output (file contents) inflated a 2.6 KB digest to 52 KB."""
        stream = "\n".join([
            json.dumps({"type": "tool_use", "part": {"tool": "read", "state": {
                "status": "completed", "output": "X" * 50000}}}),
            json.dumps({"type": "text", "part": {"text": "The file has 2 lines."}}),
        ])
        ev = lanes_mod.parse_events(stream)
        self.assertEqual(ev["text"], "The file has 2 lines.")
        self.assertNotIn("XXXX", ev["text"])

    def test_events_parse_tools_errors_cost_and_steps(self):
        stream = "\n".join([
            json.dumps({"type": "step_start", "part": {}}),
            json.dumps({"type": "tool_use", "part": {"tool": "write",
                        "state": {"status": "completed"}}}),
            json.dumps({"type": "tool_use", "part": {"tool": "read",
                        "state": {"status": "error"}}}),
            json.dumps({"type": "step_finish", "part": {"cost": 0}}),
            json.dumps({"type": "text", "part": {"text": "first"}}),
            json.dumps({"type": "text", "part": {"text": "first"}}),
            json.dumps({"type": "text", "part": {"text": "second"}}),
            json.dumps({"type": "step_finish", "part": {"cost": 0}}),
            "not json at all",
        ])
        ev = lanes_mod.parse_events(stream)
        self.assertEqual(ev["text"], "first\n\nsecond")
        self.assertEqual(ev["tools"], {"write": 1, "read": 1})
        self.assertEqual(ev["tool_errors"], 1)
        self.assertEqual(ev["steps"], 2)
        self.assertEqual(ev["cost"], 0.0)

    def test_error_events_are_read_as_error_signals(self):
        stream = json.dumps({"type": "error", "error": {
            "message": "Free usage limit reached"}})
        ev = lanes_mod.parse_events(stream)
        self.assertEqual(lanes_mod.classify(1, ev["text"], ev["errors"], ""), "quota")


class PaidCostBreaker(unittest.TestCase):
    """Runtime proof of free usage: any billed call stops the whole run."""

    def setUp(self):
        lanes_mod.COST_BREAKER.reset()

    def tearDown(self):
        lanes_mod.COST_BREAKER.reset()

    def test_cost_is_summed_from_step_finish(self):
        stream = "\n".join([
            json.dumps({"type": "step_finish", "part": {"cost": 0.002}}),
            json.dumps({"type": "step_finish", "cost": 0.001, "part": {}}),
        ])
        self.assertAlmostEqual(lanes_mod.parse_events(stream)["cost"], 0.003)

    def test_zero_cost_does_not_trip(self):
        lanes_mod.COST_BREAKER.record("a", "m:free", 0.0)
        self.assertFalse(lanes_mod.COST_BREAKER.tripped)

    def test_nonzero_cost_trips_and_blocks_every_later_call(self):
        lanes_mod.COST_BREAKER.record("a", "m:free", 0.0004)
        self.assertTrue(lanes_mod.COST_BREAKER.tripped)
        lane = lanes_mod.Lane("ok", "kilo", "x/y:free", "f", ["build"], True)
        with tempfile.TemporaryDirectory() as tmp:
            res = lanes_mod.invoke(lane, "hi", Path(tmp), timeout_sec=5)
        self.assertEqual(res.verdict, "refused_paid")
        self.assertEqual(res.elapsed_sec, 0.0)
        self.assertIn("cost breaker", res.stderr_tail)


class ChildReaping(unittest.TestCase):
    def test_reap_kills_tracked_process_group(self):
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        lanes_mod._track(proc.pid)
        self.assertEqual(lanes_mod.reap_all_children(), 1)
        proc.wait(timeout=10)
        self.assertIsNotNone(proc.returncode)

    def test_reap_is_idempotent(self):
        self.assertEqual(lanes_mod.reap_all_children(), 0)


class Tripwire(unittest.TestCase):
    def test_detects_created_modified_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.txt").write_text("a")
            (root / "change.txt").write_text("a")
            (root / "remove.txt").write_text("a")
            before = gate.snapshot([root])
            (root / "change.txt").write_text("changed content")
            (root / "remove.txt").unlink()
            (root / "new.txt").write_text("n")
            diff = gate.diff_snapshots(before, gate.snapshot([root]))
        self.assertEqual([Path(p).name for p in diff["created"]], ["new.txt"])
        self.assertEqual([Path(p).name for p in diff["modified"]], ["change.txt"])
        self.assertEqual([Path(p).name for p in diff["deleted"]], ["remove.txt"])

    def test_prunes_heavy_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / "index.js").write_text("x")
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("ref")
            (root / "real.py").write_text("x")
            snap = gate.snapshot([root])
        names = {Path(p).name for p in snap}
        self.assertEqual(names, {"real.py"})

    def test_no_change_means_empty_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a").write_text("a")
            s = gate.snapshot([Path(tmp)])
            diff = gate.diff_snapshots(s, gate.snapshot([Path(tmp)]))
        self.assertEqual(diff["created"] + diff["modified"] + diff["deleted"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
