"""Benchmarks for the Engineering department.

Three suites, each answering a different question:

  safety   do the engine's guarantees actually hold? Deterministic, no models.
  lanes    which free lanes answer right now, and what does a call cost? Live.
  quality  how much does the pipeline add over one free model asked once? Live.

The quality suite is the one that tests the Owner's instruction to make free lanes beat
a paid model. It scores two ways of solving the same problem with the same free models:

  baseline  one lane, one shot, the problem statement only.
  engine    the full pipeline: recon, plan, red team, sampling, review, gates, repair.

Both are graded by hidden tests that are written into the working directory only after
the build is finished, so neither can code to the tests. The score is the fraction of
hidden tests that pass, which measures the process rather than the prompt.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import bench_tasks, guard, lanes as lanes_mod, orchestrator, util
from . import spec as spec_mod
from .ledger import Ledger

PIPELINE_DIR = Path(__file__).resolve().parent.parent
BENCH_ROOT = Path(os.environ.get("ENG_BENCH_ROOT", str(PIPELINE_DIR / "bench")))


@dataclass
class Score:
    task: str
    mode: str
    lane: str = ""
    passed: int = 0
    total: int = 0
    elapsed_sec: float = 0.0
    cost: float = 0.0
    calls: int = 0
    error: str = ""
    details: list = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


# ------------------------------------------------------------------ test scoring

_TEST_LINE = re.compile(r"^(test_\S+)\s+\(([^)]+)\).*?\.\.\.\s+(ok|FAIL|ERROR|skipped)", re.M)

_MARKER = re.compile(r"^HIDDEN (\S+) (ok|FAIL|ERROR|skipped)$", re.M)
_RAN_MARKER = re.compile(r"^HIDDEN_RAN (\d+)$", re.M)

# Runs inside the scored directory. unittest writes its per-test lines and its
# warnings to the same stream, which is why the text could not be trusted; this
# keeps the machine-readable verdicts on a stream nothing else touches.
_SCORE_RUNNER = """import sys
import unittest


class Recorder(unittest.TextTestResult):
    def _say(self, test, verdict):
        print("HIDDEN %s %s" % (test.id().split(".")[-1], verdict), flush=True)

    def addSuccess(self, test):
        unittest.TextTestResult.addSuccess(self, test)
        self._say(test, "ok")

    def addFailure(self, test, err):
        unittest.TextTestResult.addFailure(self, test, err)
        self._say(test, "FAIL")

    def addError(self, test, err):
        unittest.TextTestResult.addError(self, test, err)
        self._say(test, "ERROR")

    def addSkip(self, test, reason):
        unittest.TextTestResult.addSkip(self, test, reason)
        self._say(test, "skipped")


suite = unittest.defaultTestLoader.loadTestsFromName("test_hidden")
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1,
                                 resultclass=Recorder).run(suite)
print("HIDDEN_RAN %d" % result.testsRun, flush=True)
"""


def run_hidden_tests(task: dict, workdir: Path) -> tuple[int, int, list]:
    """Copy the hidden tests in, run them, and read the verdicts the tests print.

    Verdicts come from `_hidden_runner.py`, which writes exactly one line per test to
    stdout and sends every traceback and warning to stderr. The previous version
    regex-parsed `unittest -v` output, where a warning raised inside a test lands
    between the test name and its verdict: on expr-eval the unclosed file in
    test_no_eval_shortcut did exactly that, so a passing test vanished from the count
    and every mode was scored one point low."""
    workdir = Path(workdir)
    if not (workdir / "solution.py").exists():
        total = len(re.findall(r"def test_", task["hidden_tests"]))
        return 0, total, [{"test": "*", "result": "ERROR", "why": "solution.py missing"}]

    test_file = workdir / "test_hidden.py"
    test_file.write_text(task["hidden_tests"])
    (workdir / "_hidden_runner.py").write_text(_SCORE_RUNNER)
    try:
        proc = subprocess.run(
            ["python3", "_hidden_runner.py"],
            cwd=str(workdir), capture_output=True, text=True, timeout=180)
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        total = len(re.findall(r"def test_", task["hidden_tests"]))
        return 0, total, [{"test": "*", "result": "ERROR", "why": "tests timed out"}]

    details = [{"test": m.group(1), "result": m.group(2)}
               for m in _MARKER.finditer(proc.stdout)]
    ran = [int(m.group(1)) for m in _RAN_MARKER.finditer(proc.stdout)]
    if not details:
        # The in-process runner stayed silent. Fall back to the old text parse rather
        # than reporting a clean zero, and record that the fallback was needed.
        details = [{"test": m.group(1), "result": m.group(3)}
                   for m in _TEST_LINE.finditer(out)]
        total_match = re.search(r"Ran (\d+) tests?", out)
        total = int(total_match.group(1)) if total_match else len(details)
        details.append({"test": "*", "result": "ERROR",
                        "why": "runner silent; scored from unittest text output"})
    else:
        total = ran[-1] if ran else len(details)
    passed = sum(1 for d in details if d["result"] == "ok")
    verdicts = sum(1 for d in details if d["test"] != "*")
    if total and verdicts != total:
        # A missing verdict counts against the solution, never for it: under-reporting
        # is the safe direction for a score that is used as evidence.
        details.append({"test": "*", "result": "ERROR",
                        "why": f"attribution gap: {verdicts} verdicts for {total} tests"})
    util.write_text(workdir / "hidden-results.txt", out[-8000:])
    return passed, total, details


# ----------------------------------------------------------------- baseline mode

BASELINE_PROMPT = """Write a complete Python module named solution.py in the current
directory that solves this problem.

{statement}

Requirements: implement it fully, no stubs and no placeholders. Use only the Python
standard library. Before you finish, check that your code imports cleanly."""


def run_baseline(task: dict, pool: list, health: dict, workdir: Path,
                 timeout_sec: int, attempts: int = 3) -> Score:
    """One shot per attempt, but a lane that produces nothing is not a model verdict.

    A free lane can answer a trivial probe and still hang on real work. Scoring that as
    a model failure would flatter the engine for the wrong reason, so the baseline is
    allowed to move to another lane until one actually returns a file. Each attempt is
    still a single unassisted call: no plan, no review, no repair, no second opinion.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    score = Score(task["id"], "baseline")
    started = time.monotonic()
    tried: list[str] = []
    picked: list[str] = []

    for attempt in range(1, attempts + 1):
        candidates = lanes_mod.pick(pool, health, "build", count=1,
                                    exclude_lanes=set(picked))
        if not candidates:
            break
        lane = candidates[0]
        picked.append(lane.id)
        tried.append(lane.id)
        res = lanes_mod.invoke(lane, BASELINE_PROMPT.format(statement=task["statement"]),
                               workdir, timeout_sec,
                               title=f"bench-{task['id']}-a{attempt}", mode="rw")
        score.calls += 1
        score.cost += res.cost
        if (workdir / "solution.py").exists():
            score.lane = lane.id
            score.error = "" if attempt == 1 else f"lane {attempt}: {','.join(tried)}"
            break
        score.error = f"no solution.py from {','.join(tried)} ({res.verdict})"
        score.lane = ",".join(tried)

    score.elapsed_sec = round(time.monotonic() - started, 1)
    score.passed, score.total, score.details = run_hidden_tests(task, workdir)
    return score


# ------------------------------------------------------------------- engine mode

def build_spec(task: dict, workdir: Path, depth: int) -> dict:
    """The spec a lane sees: the problem, the file, and public checks only.

    The hidden tests are deliberately absent. A public check proves the module imports
    and handles the worked examples, which is what a real ticket would state.
    """
    examples = re.findall(r"^\s{4}(\w+\(.*)$", task["statement"], re.M)
    public = "\n".join(
        f"assert {e}" for e in examples if "raises" not in e and "==" in e) or "pass"
    probe = workdir / "public_check.py"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("from solution import *\n" + public + "\nprint('PUBLIC_OK')\n")
    return {
        "id": f"bench-{task['id']}",
        "title": task["title"],
        "department": "engineering",
        "depth": depth,
        "goal": (task["statement"].strip()
                 + "\n\nThis is a correctness-critical utility. Handle the edge cases the "
                   "statement names, and any obvious ones it implies. It will be tested "
                   "against cases you have not seen."),
        "deliverables": [{"path": str(workdir / "solution.py"), "min_bytes": 200,
                          "description": "the complete module"}],
        "acceptance": [
            {"name": "imports", "cmd": f"cd {workdir} && python3 -c 'import solution'",
             "expect_exit": 0},
            {"name": "public_examples", "cmd": f"cd {workdir} && python3 public_check.py",
             "expect_exit": 0, "expect_stdout": "PUBLIC_OK"},
        ],
        "authorized_paths": [str(workdir)],
        "banned_paths": [str(PIPELINE_DIR / "engine"), "/home/ubuntu/.config",
                         "/home/ubuntu/.ssh"],
        "context_sources": [],
        "constraints": ["Use only the Python standard library.",
                        "Do not look for or read any test files; the grading tests are hidden."],
    }


def run_engine(task: dict, workdir: Path, depth: int, lanes_file: Path | None,
               health: dict | None = None) -> Score:
    workdir.mkdir(parents=True, exist_ok=True)
    score = Score(task["id"], "engine")
    run_dir = workdir.parent / f"{workdir.name}-run"
    started = time.monotonic()
    ledger = Ledger(run_dir)
    try:
        spec = spec_mod.from_dict(build_spec(task, workdir, depth))
        outcome = orchestrator.run(spec, run_dir, lanes_file=lanes_file, health=health)
        score.error = "" if outcome.status == "DONE" else outcome.status
    except Exception as exc:                                   # noqa: BLE001
        # One task failing must not abort the suite; it is itself a result.
        score.error = f"{type(exc).__name__}: {exc}"[:200]
    score.elapsed_sec = round(time.monotonic() - started, 1)
    summary = ledger.summary()
    score.cost = summary["total_cost"]
    score.calls = summary["lane_calls"]
    score.lane = ",".join(sorted({e.get("lane", "") for e in ledger.events("lane_call")}))[:60]
    score.passed, score.total, score.details = run_hidden_tests(task, workdir)
    return score


# ------------------------------------------------------------------ safety suite

def run_safety() -> dict:
    """Run the engine's own test suite and report pass/fail per class."""
    proc = subprocess.run(
        [sys.executable, "-W", "error::ResourceWarning", "-m", "unittest",
         "discover", "-s", str(PIPELINE_DIR / "tests"), "-v"],
        cwd=str(PIPELINE_DIR), capture_output=True, text=True, timeout=1800,
        env={**os.environ, "ENG_SLOTS_DIR": str(BENCH_ROOT / "slots"),
             "ENG_BRIDGE_STATE": str(BENCH_ROOT / "bridge-state"),
             "ENG_OFFER_STATE": str(BENCH_ROOT / "offers")})
    out = proc.stdout + proc.stderr
    ran = re.search(r"Ran (\d+) tests?", out)
    failures = re.findall(r"^(FAIL|ERROR): (\S+)", out, re.M)
    return {"suite": "safety", "passed": proc.returncode == 0,
            "tests": int(ran.group(1)) if ran else 0,
            "failures": [f"{kind} {name}" for kind, name in failures],
            "tail": out[-1500:]}


def run_lanes(lanes_file: Path | None, out_dir: Path) -> dict:
    pool, defaults = lanes_mod.load_lanes(lanes_file)
    audit = guard.audit_lanes(pool)
    health = lanes_mod.probe(pool, int(defaults.get("probe_timeout_sec", 90)),
                             int(defaults.get("max_parallel", 3)),
                             workdir=out_dir / "probe")
    families = sorted({ln.family for ln in pool if ln.id in set(health["live"])})
    return {"suite": "lanes", "enabled": sum(1 for ln in pool if ln.enabled),
            "provably_free": audit["enabled_free"], "violations": audit["violations"],
            "live": health["live"], "dead": health["dead"], "families": families,
            "total_cost": health["total_cost"],
            "median_latency": sorted(r["elapsed_sec"] for r in health["results"]
                                     if r["verdict"] == "ok"),
            "results": health["results"]}


# ----------------------------------------------------------------------- driver

def run_quality(tasks: list, modes: list, depth: int, lanes_file: Path | None,
                out_dir: Path, timeout_sec: int) -> dict:
    pool, defaults = lanes_mod.load_lanes(lanes_file)
    guard.enforce(pool)
    health = lanes_mod.probe([ln for ln in pool if ln.enabled and not ln.readonly],
                             int(defaults.get("probe_timeout_sec", 90)),
                             int(defaults.get("max_parallel", 3)),
                             workdir=out_dir / "probe")
    builders = lanes_mod.pick(pool, health, "build", count=1)
    scores: list[Score] = []
    if not builders:
        print("  warning: no live builder lane", flush=True)

    for task in tasks:
        for mode in modes:
            workdir = out_dir / task["id"] / mode
            if mode == "baseline":
                if not health["live"]:
                    scores.append(Score(task["id"], mode, error="no live builder lane"))
                    continue
                score = run_baseline(task, pool, health, workdir, timeout_sec)
            else:
                score = run_engine(task, workdir, depth, lanes_file, health)
            scores.append(score)
            util.write_json(out_dir / "scores.json", [s.__dict__ for s in scores])
            print(f"  {task['id']:<16} {mode:<9} {score.passed}/{score.total} "
                  f"({score.rate:.0%})  {score.elapsed_sec}s  cost={score.cost}  "
                  f"{score.error}", flush=True)

    by_mode = {}
    for mode in modes:
        rows = [s for s in scores if s.mode == mode]
        passed = sum(s.passed for s in rows)
        total = sum(s.total for s in rows)
        by_mode[mode] = {
            "tests_passed": passed, "tests_total": total,
            "rate": round(passed / total, 4) if total else 0.0,
            "tasks_fully_solved": sum(1 for s in rows if s.total and s.passed == s.total),
            "tasks": len(rows),
            "seconds": round(sum(s.elapsed_sec for s in rows), 1),
            "cost": round(sum(s.cost for s in rows), 6),
            "lane_calls": sum(s.calls for s in rows),
        }
    return {"suite": "quality", "depth": depth, "live_lanes": health["live"],
            "by_mode": by_mode, "scores": [s.__dict__ for s in scores]}


def write_report(result: dict, out_dir: Path) -> Path:
    lines = ["# Engineering benchmark report", "",
             f"- Run: {out_dir.name}", f"- Finished: {util.ist_now()} ({util.utc_now()})", ""]

    if result.get("suite") == "safety" or "safety" in result:
        s = result.get("safety", result)
        lines += ["## Safety suite", f"- Result: {'PASS' if s['passed'] else 'FAIL'}",
                  f"- Tests: {s['tests']}", ""]
        if s.get("failures"):
            lines += [f"  - {f}" for f in s["failures"]] + [""]

    if "lanes" in result:
        ln = result["lanes"]
        lines += ["## Lane suite",
                  f"- Enabled: {ln['enabled']}, provably free: {ln['provably_free']}, "
                  f"live now: {len(ln['live'])}",
                  f"- Model families live: {len(ln['families'])} "
                  f"({', '.join(ln['families'])})",
                  f"- Total provider-reported cost: {ln['total_cost']}", ""]
        if ln["dead"]:
            lines += [f"  - dead: {k} ({v})" for k, v in ln["dead"].items()] + [""]

    if "quality" in result:
        q = result["quality"]
        lines += ["## Quality suite",
                  f"Depth {q['depth']}. Hidden tests are written only after the build, "
                  f"so neither mode can code to them.", "",
                  "| mode | tests passed | rate | tasks fully solved | seconds | lane calls | cost |",
                  "|---|---|---|---|---|---|---|"]
        for mode, m in q["by_mode"].items():
            lines.append(f"| {mode} | {m['tests_passed']}/{m['tests_total']} "
                         f"| {m['rate']:.0%} | {m['tasks_fully_solved']}/{m['tasks']} "
                         f"| {m['seconds']} | {m['lane_calls']} | {m['cost']} |")
        lines.append("")
        if "baseline" in q["by_mode"] and "engine" in q["by_mode"]:
            b, e = q["by_mode"]["baseline"], q["by_mode"]["engine"]
            delta = e["rate"] - b["rate"]
            lines += [f"The pipeline moved the hidden-test pass rate from "
                      f"{b['rate']:.0%} to {e['rate']:.0%} ({delta:+.0%}), on the same "
                      f"free models, at a total reported cost of {e['cost']}.", ""]
        lines += ["### Per task", "", "| task | mode | passed | rate | seconds | note |",
                  "|---|---|---|---|---|---|"]
        for s in q["scores"]:
            total = s["total"] or 1
            lines.append(f"| {s['task']} | {s['mode']} | {s['passed']}/{s['total']} "
                         f"| {s['passed'] / total:.0%} | {s['elapsed_sec']} "
                         f"| {s.get('error', '')} |")
        lines.append("")

    path = out_dir / "BENCH_REPORT.md"
    util.write_text(path, "\n".join(lines))
    util.write_json(out_dir / "bench.json", result)
    return path
