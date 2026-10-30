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
from dataclasses import asdict, dataclass, field
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
    skipped: int = 0             # hidden checks not run (no network, wrong task kind)
    gates: list = field(default_factory=list)   # engine-run gate verdicts for this run

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def as_dict(self) -> dict:
        return asdict(self)


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


# ----------------------------------------------------------------- design suite
# The design suite mirrors run_quality with deterministic visual gates instead of
# hidden unit tests: artefacts are graded by bench_design (source bytes, copy strings,
# PNG dimensions and decoded pixel variance, video duration and per-frame variance).

def _grade_score(task: dict, mode: str, workdir: Path, started: float,
                 lane_ids: str, calls: int, cost: float, error: str) -> Score:
    from . import bench_design
    score = Score(task["id"], mode, lane=lane_ids, calls=calls, cost=cost, error=error)
    try:
        rows = bench_design.grade(workdir, bench_design.manifest_for(task))
    except Exception as exc:                                   # noqa: BLE001
        rows = [{"name": "*", "passed": False, "why": f"grader crashed: {exc}"}]
    score.details = [{"test": r["name"], "result": "ok" if r["passed"] else "FAIL",
                      "why": r.get("detail") or r.get("why", "")} for r in rows]
    score.total = len(rows)
    score.passed = sum(1 for r in rows if r["passed"])
    score.elapsed_sec = round(time.monotonic() - started, 1)
    return score


def run_design_baseline(task: dict, pool: list, health: dict, workdir: Path,
                        timeout_sec: int, attempts: int = 3) -> Score:
    """One unassisted call per attempt, same rules as the quality baseline.

    A lane that produces no source file at all is not a model verdict, so the baseline
    may move to another free lane until one writes the file. Each attempt is still one
    single call: no plan, no skills, no review, no gates feeding a repair loop."""
    from . import bench_design
    workdir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    tried, picked, calls = [], [], 0
    cost = 0.0
    paid = ""
    prompt = bench_design.BASELINE_PROMPT.format(brief=task["brief"])
    for attempt in range(1, attempts + 1):
        candidates = lanes_mod.pick(pool, health, "build", count=1,
                                    exclude_lanes=set(picked))
        if not candidates:
            break
        lane = candidates[0]
        picked.append(lane.id)
        tried.append(lane.id)
        res = lanes_mod.invoke(lane, prompt, workdir, timeout_sec,
                               title=f"design-{task['id']}-a{attempt}", mode="rw")
        calls += 1
        cost += res.cost
        if res.cost > 0:
            paid = (f"PAID COST DETECTED: lane {lane.id} ({lane.model}) reported cost "
                    f"{res.cost}; free-only rule, the suite must stop")
            break
        if (workdir / task["source"]["path"]).exists():
            break
    error = paid or ("" if (workdir / task["source"]["path"]).exists()
                     else f"no source file from {','.join(tried) or 'no live lane'}")
    lane_ids = ",".join(tried)[:60]
    return _grade_score(task, "baseline", workdir, started, lane_ids, calls, cost, error)


def run_design_engine(task: dict, workdir: Path, depth: int, lanes_file: Path | None,
                      health: dict | None = None) -> Score:
    """The full pipeline against the design kit: skills injected, kit templates plus
    deterministic design gates run by the engine, repair driven by real gate output."""
    from . import bench_design
    workdir.mkdir(parents=True, exist_ok=True)
    score = Score(task["id"], "engine")
    run_dir = workdir.parent / f"{workdir.name}-run"
    started = time.monotonic()
    ledger = Ledger(run_dir)
    try:
        spec = spec_mod.from_dict(bench_design.build_spec(task, workdir, depth))
        outcome = orchestrator.run(spec, run_dir, lanes_file=lanes_file, health=health)
        score.error = "" if outcome.status == "DONE" else outcome.status
    except Exception as exc:                                   # noqa: BLE001
        score.error = f"{type(exc).__name__}: {exc}"[:200]
    score.elapsed_sec = round(time.monotonic() - started, 1)
    summary = ledger.summary()
    score.cost = summary["total_cost"]
    score.calls = summary["lane_calls"]
    score.lane = ",".join(sorted({e.get("lane", "") for e in ledger.events("lane_call")}))[:60]
    if summary["total_cost"] > 0:
        score.error = ("PAID COST DETECTED: this run reported "
                       f"{summary['total_cost']}; free-only rule, the suite must stop")
    rows = bench_design.grade(workdir, bench_design.manifest_for(task))
    score.details = [{"test": r["name"], "result": "ok" if r["passed"] else "FAIL",
                      "why": r.get("detail") or r.get("why", "")} for r in rows]
    score.total = len(rows)
    score.passed = sum(1 for r in rows if r["passed"])
    return score


def run_design(tasks: list, modes: list, depth: int, lanes_file: Path | None,
               out_dir: Path, timeout_sec: int) -> dict:
    """Driver for the design suite. Negative proofs gate everything: if the gates do
    not reject bad output, spending free-lane time on them is meaningless and the
    live runs are refused."""
    from . import bench_design
    pool, defaults = lanes_mod.load_lanes(lanes_file)
    guard.enforce(pool)
    negatives = bench_design.run_negative_proofs(out_dir / "negatives")
    print(f"  negative proofs: {'PASS' if negatives.get('passed') else 'FAIL'} "
          f"({len(negatives.get('cases', []))} gate verdicts)", flush=True)
    result: dict = {"suite": "design", "depth": depth,
                    "negatives": negatives, "by_mode": {}, "scores": [],
                    "live_lanes": []}
    if not negatives.get("passed"):
        result["error"] = ("gates did not reject bad output (or tooling is missing); "
                           "refusing to run the live suite against worthless gates")
        return result

    health = lanes_mod.probe([ln for ln in pool if ln.enabled and not ln.readonly],
                             int(defaults.get("probe_timeout_sec", 90)),
                             int(defaults.get("max_parallel", 3)),
                             workdir=out_dir / "probe")
    result["live_lanes"] = health["live"]
    scores: list[Score] = []
    for task in tasks:
        for mode in modes:
            workdir = out_dir / task["id"] / mode
            if mode == "baseline":
                if not health["live"]:
                    scores.append(Score(task["id"], mode, error="no live builder lane"))
                    continue
                score = run_design_baseline(task, pool, health, workdir, timeout_sec)
            else:
                score = run_design_engine(task, workdir, depth, lanes_file, health)
            scores.append(score)
            result["scores"] = [s.__dict__ for s in scores]
            util.write_json(out_dir / "scores.json", result["scores"])
            print(f"  {task['id']:<24} {mode:<9} {score.passed}/{score.total} gates "
                  f"({score.rate:.0%})  {score.elapsed_sec}s  cost={score.cost}  "
                  f"{score.error}", flush=True)
            if "PAID COST" in (score.error or ""):
                result["paid_cost_detected"] = score.error
                return result

    by_mode = {}
    for mode in modes:
        rows = [s for s in scores if s.mode == mode]
        passed = sum(s.passed for s in rows)
        total = sum(s.total for s in rows)
        by_mode[mode] = {
            "gates_passed": passed, "gates_total": total,
            "rate": round(passed / total, 4) if total else 0.0,
            "tasks_fully_solved": sum(1 for s in rows if s.total and s.passed == s.total),
            "tasks": len(rows),
            "seconds": round(sum(s.elapsed_sec for s in rows), 1),
            "cost": round(sum(s.cost for s in rows), 6),
            "lane_calls": sum(s.calls for s in rows),
        }
    result["by_mode"] = by_mode
    result["total_cost"] = round(sum(s.cost for s in scores), 6)
    return result


def write_report(result: dict, out_dir: Path) -> Path:
    if "research" in result or "gates" in result:
        return write_research_report(result, out_dir)
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

    if "design" in result:
        d = result["design"]
        neg = d.get("negatives", {})
        lines += ["## Design suite",
                  f"Depth {d.get('depth')}. Gates are deterministic machine checks "
                  f"(source bytes, copy strings, PNG dimensions, decoded pixel variance, "
                  f"video duration and per-frame variance).", "",
                  "### Gate self-check (negative proofs)", "",
                  "| artefact | gate | expected | actual |", "|---|---|---|---|"]
        for c in neg.get("cases", []):
            lines.append(f"| {c['case']} | {c['gate']} | {c['expected']} "
                         f"| {c['actual']}{' (as expected)' if c['as_expected'] else ' — WRONG'} |")
        lines += ["", f"Self-check: {'PASS' if neg.get('passed') else 'FAIL'}"
                  + (f" — {neg.get('error')}" if neg.get("error") else ""), ""]
        if d.get("error"):
            lines += [f"**Suite refused live runs: {d['error']}**", ""]
        if d.get("by_mode"):
            lines += ["### Baseline vs engine", "",
                      "| mode | gates passed | rate | tasks fully solved | seconds "
                      "| lane calls | cost |", "|---|---|---|---|---|---|---|"]
            for mode, m in d["by_mode"].items():
                lines.append(f"| {mode} | {m['gates_passed']}/{m['gates_total']} "
                             f"| {m['rate']:.0%} | {m['tasks_fully_solved']}/{m['tasks']} "
                             f"| {m['seconds']} | {m['lane_calls']} | {m['cost']} |")
            lines.append("")
            if "baseline" in d["by_mode"] and "engine" in d["by_mode"]:
                b, e = d["by_mode"]["baseline"], d["by_mode"]["engine"]
                lines += [f"The pipeline moved the gate pass rate from {b['rate']:.0%} "
                          f"to {e['rate']:.0%} ({e['rate'] - b['rate']:+.0%}) on the "
                          f"same free models, at a total reported cost of "
                          f"{d.get('total_cost', e['cost'])}.", ""]
            lines += ["### Per task", "",
                      "| task | mode | gates | rate | seconds | lane | cost | note |",
                      "|---|---|---|---|---|---|---|---|"]
            for s in d["scores"]:
                total = s["total"] or 1
                lines.append(f"| {s['task']} | {s['mode']} | {s['passed']}/{s['total']} "
                             f"| {s['passed'] / total:.0%} | {s['elapsed_sec']} "
                             f"| {s['lane']} | {s['cost']} | {s.get('error', '')} |")
            lines.append("")
            lines += ["### Gate detail", ""]
            for s in d["scores"]:
                lines.append(f"#### {s['task']} ({s['mode']})")
                lines.append("")
                lines.append("| gate | result | measured |")
                lines.append("|---|---|---|")
                for det in s["details"]:
                    lines.append(f"| {det['test']} | {det['result']} "
                                 f"| {str(det.get('why', ''))[:160]} |")
                lines.append("")

    path = out_dir / "BENCH_REPORT.md"
    util.write_text(path, "\n".join(lines))
    util.write_json(out_dir / "bench.json", result)
    return path


# ======================================================================= research suite
#
# Same discipline as the quality suite, different object: the deliverable is a memo and
# the hidden tests are deterministic checks on it. A lane never sees the thresholds --
# how many sources, whether the URLs are real, whether a number outside Findings traces
# back to something cited, the word limits and the required structure. What a lane does
# see is the question and this department's own two gates, which the engine runs itself.
#
# run_gate_calibration() is the negative half of the proof. It takes a memo that passes
# everything, injects one defect at a time, and demands that the named check catches it.
# A gate that passes all of those defects is decorative, and this is how that gets
# measured instead of asserted.

MIN_SKILL_NOTE = 0
# Bare alternation: the grader wraps it in its own group so a match yields the number
# AND the unit. Wrapping it here as well made findall() return one string per hit and
# every tuple-unpack in the grader raise.
UNITS = (r"GB|MB|TB|GiB|MiB|credits?|requests?|builds?|deploys?|monitors?|checks?|"
         r"minutes?|hours?|days?|months?|sites?|projects?|seats?|objects?|buckets?|"
         r"operations|ops|%")
# (?<![A-Za-z0-9-]) keeps a product name out of the count: "an R2 bucket" is not
# "2 bucket", and "r2.dev" is not a quantity either.
NUM_UNIT = re.compile(r"(?<![A-Za-z0-9-])(\d[\d,.]*)\s*(" + UNITS + r")(?![A-Za-z])", re.I)
CITATION = re.compile(r"https?://|\[\d+\]|[\w.-]+\.[A-Za-z][A-Za-z0-9]{0,7}:\d+")
FACT_LABEL = re.compile(r"^\s*\**\s*(facts?|evidence)\s*:?\**\s*$", re.I)
INFERENCE_LABEL = re.compile(r"^\s*\**\s*(inferences?|reasoning)\s*:?\**\s*$", re.I)
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
FAIL_MODE_WORDS = ("429", "too many requests", "limit reached", "throttl", "paus",
                   "suspend", "stop", "stall", "hang", "block", "quota", "exhaust",
                   "denied", "rate limit", "degrade", "slow", "refus")
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")

RESEARCH_HEADINGS = {
    "question": r"^(the\s+)?question\b",
    "why": r"^(why\s+(it|this)\s+matters|decision\s+(it|this)\s+feeds)",
    "findings": r"^(key\s+)?findings\b",
    "options": r"^(options|alternatives|trade-?offs)\b",
    "recommendation": r"^recommendations?\b",
    "pre-mortem": r"^pre-?\s?mortem\b",
    "open questions": r"^(open\s+questions|unknowns)\b",
    "sources": r"^(sources|references)\b",
}


def research_root() -> Path:
    from . import departments as dept_mod
    return Path(dept_mod.DEPARTMENTS_ROOT)


def research_kit(dept: str = "research") -> Path:
    return research_root() / dept


def _params_lines(task: dict, memo: Path, kit: Path) -> str:
    """Constants baked into the generated grader; the thresholds stay out of the brief."""
    head = [
        f"MEMO_PATH = {str(memo)!r}",
        f"KIT_PATH = {str(kit)!r}",
        f"TASK_ID = {task['id']!r}",
        f"KIND = {task['kind']!r}",
        f"MIN_SOURCES = {int(task['min_sources'])}",
        f"MIN_DOMAINS = {int(task['min_domains'])}",
        f"REQUIRED_HOSTS = {list(task['required_hosts'])!r}",
        f"MIN_WORDS = {int(task['min_words'])}",
        f"MAX_WORDS = {int(task['max_words'])}",
        f"MIN_BLOCKS = {int(task['min_blocks'])}",
        f"MIN_CITED_SHARE = {float(task['min_cited_share'])}",
        f"MIN_FACT_BULLETS = {int(task['min_fact_bullets'])}",
        f"OPTION_TERMS = {list(task['option_terms'])!r}",
        f"MIN_OPTION_TERMS = {int(task['min_option_terms'])}",
        f"MIN_TABLE_ROWS = {int(task['min_table_rows'])}",
        f"NEEDS_CONSTRAINTS_BLOCK = {bool(task['needs_constraints_block'])!r}",
        f"NEEDS_LIMIT_BEHAVIOUR = {bool(task['needs_limit_behaviour'])!r}",
        f"MIN_PREMORTEM_CAUSES = {int(task['min_premortem_causes'])}",
        f"MIN_MEMO_BYTES = {int(task['min_memo_bytes'])}",
        f"HEADINGS = {[RESEARCH_HEADINGS[h] for h in task['headings']]!r}",
        f"USER_AGENT = {USER_AGENT!r}",
        f"UNITS = {UNITS!r}",
        f"FAIL_MODE_WORDS = {FAIL_MODE_WORDS!r}",
    ]
    return "\n".join(head) + "\n"


GRADER_BODY = r'''
import importlib.util
import re
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

MEMO = Path(MEMO_PATH)
KIT = Path(KIT_PATH)


def _kit_tool(name, filename):
    spec = importlib.util.spec_from_file_location(name, str(KIT / "tools" / filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cc = _kit_tool("kit_cite_check", "cite_check.py")
ml = _kit_tool("kit_memo_lint", "memo_lint.py")

TEXT = MEMO.read_text(errors="replace") if MEMO.exists() else ""
LINES = TEXT.splitlines()
MASK = cc.code_mask(LINES)
SECS = cc.sections(LINES, MASK)
CHECK = cc.check_text(TEXT) if TEXT else {"problems": [], "claims": 0, "cited": 0,
                                         "inference": 0, "sources": 0,
                                         "unused_sources": [], "has_claims_section": False}
NUM_UNIT = re.compile(r"(?<![A-Za-z0-9-])(\d[\d,.]*)\s*(" + UNITS + r")(?![A-Za-z])",
                     re.I)
HEADLINE = [re.compile(p, re.I) for p in HEADINGS]
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def secs(*patterns):
    rx = [re.compile(p, re.I) for p in patterns]
    return [s for s in SECS if any(r.match(s["title"]) for r in rx)]


def body(sec):
    return "\n".join(LINES[sec["start"] + 1: sec["end"]])


def is_cited(text):
    return bool(re.search(r"https?://", text) or re.search(r"\[\d+\]", text)
                or re.search(r"[\w.-]+\.[A-Za-z][A-Za-z0-9]{0,7}:\d+", text))


def findings_secs():
    return secs(r"^(key\s+)?findings\b")


def claim_secs():
    return [s for s in SECS if re.match(r"^(key\s+)?(findings|claims|evidence|facts)\b",
                                        s["title"], re.I)]


def blocks():
    """The ### blocks inside Findings."""
    out = []
    for f in findings_secs():
        out += [s for s in SECS if s["level"] >= 3 and f["start"] < s["start"] < f["end"]]
    return out


def source_entries():
    ids, entries, problems = {}, [], []
    for s in secs(r"^(sources|references)\b"):
        i, e, p = cc.parse_sources(LINES, s, MASK)
        ids.update(i)
        entries += e
        problems += p
    return ids, entries, problems


def source_urls():
    urls = []
    for s in secs(r"^(sources|references)\b"):
        for line in LINES[s["start"] + 1: s["end"]]:
            urls += [u.rstrip(".,;)") for u in re.findall(r"https?://\S+", line)]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def registrable(url):
    host = re.match(r"https?://([^/?#\s]+)", url)
    if not host:
        return ""
    h = host.group(1).rsplit("@", 1)[-1].split(":")[0].lower()
    parts = h.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def words():
    n = 0
    for i, line in enumerate(LINES):
        if MASK[i] or line.strip().startswith("#"):
            continue
        n += len(re.findall(r"[A-Za-z0-9][\w'.%/-]*", re.sub(r"https?://\S+", "", line)))
    return n


def table_rows(sec):
    rows = []
    for line in body(sec).splitlines():
        s = line.strip()
        if s.startswith("|") and not re.match(r"^\|?[\s:|-]+\|?$", s):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if any(cells):
                rows.append(cells)
    return rows


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                              "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()               # otherwise the object warns when it is collected
        return code, "HTTP %s" % code
    except Exception as exc:                                  # noqa: BLE001
        return None, type(exc).__name__ + ": " + str(exc)[:120]


class MemoGrader(unittest.TestCase):
    """Deterministic checks on the finished memo. No model adjudicates any of them."""

    def test_memo_exists_and_is_a_memo(self):
        self.assertTrue(MEMO.is_file(), "no memo at %s" % MEMO)
        self.assertGreaterEqual(MEMO.stat().st_size, MIN_MEMO_BYTES,
                                "memo is under %d bytes" % MIN_MEMO_BYTES)
        self.assertTrue(any(s["level"] == 1 for s in SECS), "memo has no # title")

    def test_department_cite_gate_passes(self):
        proc = subprocess.run([sys.executable, str(KIT / "tools" / "cite_check.py"),
                               str(MEMO)], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         "cite_check: " + (proc.stderr.strip() or proc.stdout)[-500:])

    def test_department_format_gate_passes(self):
        proc = subprocess.run([sys.executable, str(KIT / "tools" / "memo_lint.py"),
                               str(MEMO), "--kind", KIND],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         "memo_lint: " + (proc.stderr.strip() or proc.stdout)[-500:])

    def test_required_headings_present(self):
        missing = []
        for rx in HEADLINE:
            if not [s for s in SECS if s["level"] <= 2 and rx.match(s["title"])]:
                missing.append(rx.pattern)
        self.assertEqual(missing, [], "required headings missing: %s" % missing)

    def test_headings_in_order(self):
        pos = []
        for rx in HEADLINE:
            found = [s["start"] for s in SECS if s["level"] <= 2 and rx.match(s["title"])]
            if found:
                pos.append((rx.pattern, found[0]))
        self.assertEqual(pos, sorted(pos, key=lambda x: x[1]),
                         "sections out of order: %s" % [p[0] for p in pos])

    def test_sources_lists_enough_distinct_urls(self):
        urls = source_urls()
        self.assertGreaterEqual(len(urls), MIN_SOURCES,
                                "only %d distinct URLs in Sources, needs %d"
                                % (len(urls), MIN_SOURCES))

    def test_sources_span_enough_independent_domains(self):
        domains = sorted({registrable(u) for u in source_urls()})
        self.assertGreaterEqual(len(domains), MIN_DOMAINS,
                                "sources come from %s, needs %d domains"
                                % (domains, MIN_DOMAINS))
        blob = " ".join(source_urls()).lower()
        for host in REQUIRED_HOSTS:
            self.assertIn(host, blob, "no source from %s anywhere in Sources" % host)

    def test_source_urls_are_reachable(self):
        urls = source_urls()
        self.assertTrue(urls, "no URLs in Sources to check")
        probe, why = _fetch("https://example.com/")
        if probe is None:
            self.skipTest("grader has no network to check URLs with: %s" % why)
        dead = []
        for u in urls:
            status, err = _fetch(u)
            if status is None:
                if _fetch("https://example.com/")[0] is None:
                    self.skipTest("network went mid-check: %s" % err)
                dead.append("%s (%s)" % (u, err))
            elif status in (404, 410):
                dead.append("%s (HTTP %s)" % (u, status))
        self.assertEqual(dead, [], "cited pages that do not exist: %s" % dead)

    def test_every_findings_block_is_grounded(self):
        bl = blocks()
        self.assertGreaterEqual(len(bl), MIN_BLOCKS,
                                "only %d ### blocks under Findings, needs %d"
                                % (len(bl), MIN_BLOCKS))
        bare = []
        for b in bl:
            text = body(b)
            if not is_cited(text):
                bare.append(b["title"])
        self.assertEqual(bare, [], "Findings blocks with no citation: %s" % bare)

    def test_citation_share_of_claims(self):
        claims, cited = CHECK["claims"], CHECK["cited"]
        self.assertGreaterEqual(claims, 1, "no claim units found in Findings")
        share = cited / claims
        self.assertGreaterEqual(share, MIN_CITED_SHARE,
                                "only %d of %d claims cited (%.0f%%, needs %.0f%%)"
                                % (cited, claims, 100 * share, 100 * MIN_CITED_SHARE))

    def test_fact_bullets_all_cited(self):
        facts, uncited = 0, []
        for f in claim_secs():
            label = None
            for i in range(f["start"] + 1, f["end"]):
                if MASK[i]:
                    continue
                line = LINES[i]
                if re.match(r"^\s*\**\s*facts?\s*:?\**\s*$", line, re.I):
                    label = "fact"
                    continue
                if re.match(r"^\s*\**\s*(inferences?|reasoning)\s*:?\**\s*$",
                            line, re.I):
                    label = "inference"
                    continue
                if BULLET.match(line) and label == "fact":
                    facts += 1
                    unit = line
                    j = i + 1
                    while j < f["end"] and not MASK[j] and LINES[j].strip() \
                            and not BULLET.match(LINES[j]):
                        unit += " " + LINES[j].strip()
                        j += 1
                    if not is_cited(unit):
                        uncited.append("line %d: %s" % (i + 1, unit[:70]))
        self.assertGreaterEqual(facts, MIN_FACT_BULLETS,
                                "only %d fact bullets, needs %d" % (facts, MIN_FACT_BULLETS))
        self.assertEqual(uncited, [], "fact bullets with no citation: %s" % uncited)

    def test_numbers_outside_findings_trace_to_a_cited_claim(self):
        # No docstring here: unittest -v prints it and the harness parses one line per
        # test, so a long docstring wraps the result off the line that is matched.
        # A figure in the table, the recommendation or the pre-mortem must be one the
        # memo already established in Findings: numbers invented at the point of the
        # decision are the ones that mislead a reader.
        grounded = set()
        for f in claim_secs():
            for ln, unit, _label in cc.claim_units(LINES, f, MASK):
                for num, unit_name in NUM_UNIT.findall(re.sub(r"https?://\S+", "", unit)):
                    grounded.add((num.replace(",", ""), unit_name.lower()))
        loose = []

        def check(where, text):
            if is_cited(text):
                return
            for num, unit_name in NUM_UNIT.findall(re.sub(r"https?://\S+", "", text)):
                if (num.replace(",", ""), unit_name.lower()) not in grounded:
                    loose.append("%s: %s %s" % (where, num, unit_name))

        for sec in secs(r"^(options|alternatives|trade-?offs)\b",
                        r"^recommendations?\b", r"^pre-?\s?mortem\b"):
            # one table cell, one claim: a citation in a neighbouring cell proves
            # nothing about the number sitting in this one
            for row in table_rows(sec):
                for cell in row[1:]:
                    check(sec["title"], cell)
            for line in body(sec).splitlines():
                s = line.strip()
                if not s or s.startswith("|"):
                    continue
                check(sec["title"], s)
        self.assertEqual(loose, [], "uncited numbers outside Findings: %s" % loose[:6])

    def test_word_count_within_limits(self):
        n = words()
        self.assertGreaterEqual(n, MIN_WORDS, "memo is %d words, under %d" % (n, MIN_WORDS))
        self.assertLessEqual(n, MAX_WORDS, "memo is %d words, over %d" % (n, MAX_WORDS))

    def test_options_table_is_a_real_comparison(self):
        rows = []
        for sec in secs(r"^(options|alternatives|trade-?offs)\b"):
            rows += table_rows(sec)
        self.assertGreaterEqual(len(rows), MIN_TABLE_ROWS,
                                "options table has %d rows, needs %d"
                                % (len(rows), MIN_TABLE_ROWS))
        widest = max((len(r) for r in rows), default=0)
        self.assertGreaterEqual(widest, 3, "options table is not a comparison of options")

    def test_options_are_addressed(self):
        text = TEXT.lower()
        hit = [t for t in OPTION_TERMS if t in text]
        self.assertGreaterEqual(len(hit), MIN_OPTION_TERMS,
                                "memo addresses %s, needs %d of %s"
                                % (hit, MIN_OPTION_TERMS, OPTION_TERMS))

    def test_recommendation_commits(self):
        rec = " ".join(body(s) for s in secs(r"^recommendations?\b")).lower()
        self.assertTrue(rec.strip(), "no Recommendation body")
        self.assertIn("what would change it", rec,
                      "Recommendation does not say what would change it")
        self.assertTrue(any(t in rec for t in OPTION_TERMS) or "keep" in rec
                        or "neither" in rec or "stay" in rec,
                        "Recommendation names no option")

    def test_every_source_is_dated(self):
        undated = []
        for s in secs(r"^(sources|references)\b"):
            for line in LINES[s["start"] + 1: s["end"]]:
                if "http" in line and not re.search(
                        r"checked\s+\d{4}-\d{2}-\d{2}", line, re.I):
                    undated.append(line[:70])
        self.assertEqual(undated, [], "Sources entries without a checked date: %s" % undated)

    def test_dates_are_recent(self):
        bad = []
        for s in secs(r"^(sources|references)\b"):
            for line in LINES[s["start"] + 1: s["end"]]:
                for iso in re.findall(r"\d{4}-\d{2}-\d{2}", line):
                    try:
                        d = date.fromisoformat(iso)
                    except ValueError:
                        bad.append("%s is not a date" % iso)
                        continue
                    # The VM runs UTC while the company writes IST: a memo dated "today"
                    # in IST is tomorrow in UTC, so two days of skew is allowed.
                    if (d - date.today()).days > 2 or (date.today() - d).days > 400:
                        bad.append(iso)
        self.assertEqual(bad, [], "checked dates that are not plausible: %s" % bad)

    def test_result_line(self):
        hits = [l.strip() for l in LINES if l.strip().startswith("RESULT:")]
        self.assertTrue(hits, "memo ends with no RESULT: line")
        self.assertFalse(any("BLOCKED" in h for h in hits),
                         "run reported BLOCKED: %s" % hits)

    def test_first_principles_constraints_block(self):
        if not NEEDS_CONSTRAINTS_BLOCK:
            self.skipTest("not required for this task kind")
        titles = [b["title"].lower() for b in blocks()]
        self.assertTrue([t for t in titles if "constraint" in t or "first princip" in t],
                        "no constraints-from-first-principles block in Findings: %s" % titles)

    def test_free_limit_behaviour_stated(self):
        if not NEEDS_LIMIT_BEHAVIOUR:
            self.skipTest("not required for this task kind")
        weak = []
        for b in blocks():
            text = body(b)
            numbers = NUM_UNIT.findall(re.sub(r"https?://\S+", "", text))
            if not numbers:
                continue
            low = text.lower()
            if not any(w in low for w in FAIL_MODE_WORDS):
                weak.append("%s states %d limits but no failure mode"
                            % (b["title"], len(numbers)))
        self.assertEqual(weak, [], "blocks without a stated behaviour at the limit: %s" % weak)

    def test_premortem_lists_causes(self):
        if not MIN_PREMORTEM_CAUSES:
            self.skipTest("not required for this task kind")
        rows = []
        for sec in secs(r"^pre-?\s?mortem\b"):
            for line in body(sec).splitlines():
                if BULLET.match(line) and len(line.split()) >= 5:
                    rows.append(line)
        self.assertGreaterEqual(len(rows), MIN_PREMORTEM_CAUSES,
                                "pre-mortem has %d causes, needs %d"
                                % (len(rows), MIN_PREMORTEM_CAUSES))


if __name__ == "__main__":
    unittest.main(verbosity=2)
'''


def write_memo_grader(task: dict, workdir: Path, kit: Path,
                     name: str = "test_memo_hidden.py") -> Path:
    """The hidden suite, written only once the writing is finished.

    Every path is resolved: the engine runs a gate with the workdir as cwd, so a
    relative --out would otherwise turn into "cannot read memo.md: No such file".
    """
    workdir = Path(workdir).resolve()
    memo = workdir / "memo.md"
    source = _params_lines(task, memo, kit) + GRADER_BODY
    path = workdir / name
    util.write_text(path, source)
    return path


def run_memo_grader(task: dict, workdir: Path, kit: Path) -> tuple[int, int, int, list]:
    """Returns passed, total, skipped, per-test details. Total excludes skips."""
    workdir = Path(workdir)
    grader = workdir / "test_memo_hidden.py"
    if not grader.exists():
        grader = write_memo_grader(task, workdir, kit)
    memo = workdir / "memo.md"
    total_defined = len(re.findall(r"def test_", grader.read_text()))
    if not memo.exists():
        return 0, total_defined, 0, [{"test": "*", "result": "ERROR",
                                      "why": "memo.md was never written"}]
    try:
        proc = subprocess.run(
            ["python3", "-m", "unittest", "test_memo_hidden", "-v"],
            cwd=str(workdir), capture_output=True, text=True, timeout=600,
            errors="replace")
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return 0, total_defined, 0, [{"test": "*", "result": "ERROR",
                                      "why": "grader timed out"}]
    details = [{"test": m.group(1), "result": m.group(3)}
               for m in _TEST_LINE.finditer(out)]
    ran = re.search(r"Ran (\d+) tests?", out)
    total = int(ran.group(1)) if ran else len(details) or total_defined
    skipped = sum(1 for d in details if d["result"] == "skipped")
    passed = sum(1 for d in details if d["result"] == "ok")
    failed = [d["test"] for d in details if d["result"] in ("FAIL", "ERROR")]
    util.write_text(workdir / "hidden-memo-results.txt", out[-12000:])
    score_total = max(total - skipped, 0)
    if failed:
        util.write_json(workdir / "hidden-memo-failures.json",
                        {"failed": failed, "tail": out[-6000:]})
    return passed, (score_total if details else total_defined), skipped, details


# ---------------------------------------------------------------- research specs

RESEARCH_BASELINE_PROMPT = """You are doing research for a small software club. Answer \
the question below as one markdown memo and write it to the file {memo} in your current \
directory. Nothing else.

{statement}

Write the whole memo into that one file. If the question cannot be answered as asked, \
write the memo saying what is missing and end it with RESULT: BLOCKED."""


def build_research_spec(task: dict, workdir: Path, depth: int,
                        dept: str = "research") -> dict:
    """The spec a lane sees. The thresholds live in the grader, never here."""
    workdir = Path(workdir).resolve()
    memo = workdir / "memo.md"
    kit = research_kit(dept)
    return {
        "id": f"research-{task['id']}",
        "title": task["title"],
        "department": dept,
        "depth": depth,
        "goal": task["statement"].strip(),
        "deliverables": [{"path": str(memo), "min_bytes": int(task["min_memo_bytes"]),
                          "description": "the one memo that answers the question"}],
        "acceptance": [
            # The kit's own memo-format template runs memo_lint with no --kind, so an
            # absent Pre-mortem in a decision memo is invisible to it: auto falls back
            # to the quick order and passes. The task knows which kind it asked for, so
            # the kind-aware gate belongs here.
            {"name": "memo-format-decision" if task["kind"] == "decision"
             else "memo-format-quick",
             "cmd": f"python3 {kit}/tools/memo_lint.py {memo} --kind {task['kind']}",
             "expect_exit": 0},
        ],
        "authorized_paths": [str(workdir)],
        "banned_paths": [str(PIPELINE_DIR / "engine"),
                         "/home/ubuntu/.config", "/home/ubuntu/.ssh",
                         "/home/ubuntu/aaryas-life/departments/personal",
                         "/home/ubuntu/aaryas-life/departments/research"],
        "context_sources": [f"{str(kit)}/skills",
                            f"{str(kit)}/templates",
                            f"{str(kit)}/runbooks"],
        "context_questions": [
            "What exactly does this department's memo format require, section by section?",
            "Which free-tier limits for the options named in the question are documented "
            "by the vendor's own pages, and what do those pages say happens at the limit?",
            "What does the company charter forbid research from recommending?",
        ],
        "constraints": [
            "Write only the memo file at the deliverable path. Nothing else.",
            "Free tiers only: a paid plan, a paid tier or a card-gated trial is never "
            "the recommendation.",
            "Never invent a fact, a number, a URL or a citation.",
        ],
    }


def _engine_checks(prof, memo: Path) -> list:
    """The gate objects the engine would run for this deliverable."""
    from .spec import Acceptance
    checks = [Acceptance(**c) for c in prof.acceptance_for([{"path": str(memo)}])]
    return checks


def _spec_checks(spec_dict: dict, prof, memo: Path) -> list:
    from .spec import Acceptance
    checks = [Acceptance(cmd=c["cmd"], name=c.get("name") or f"check{i + 1}",
                         expect_exit=int(c.get("expect_exit", 0)), timeout_sec=120)
              for i, c in enumerate(spec_dict.get("acceptance") or [])]
    return checks + _engine_checks(prof, memo)


def run_research_baseline(task: dict, pool: list, health: dict, workdir: Path,
                          timeout_sec: int, dept: str = "research",
                          attempts: int = 3) -> Score:
    """One free lane, one shot, the question only: no kit, no gates, no second pass."""
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    kit = research_kit(dept)
    memo = workdir / "memo.md"
    score = Score(task["id"], "baseline")
    started = time.monotonic()
    tried, picked = [], []
    for attempt in range(1, attempts + 1):
        candidates = lanes_mod.pick(pool, health, "build", count=1,
                                    exclude_lanes=set(picked), needs_web=True)
        if not candidates:
            break
        lane = candidates[0]
        picked.append(lane.id)
        tried.append(lane.id)
        res = lanes_mod.invoke(lane, RESEARCH_BASELINE_PROMPT.format(
            memo=str(memo), statement=task["statement"].strip()), workdir, timeout_sec,
            title=f"research-{task['id']}-a{attempt}", mode="rw", web=True)
        score.calls += 1
        score.cost += res.cost
        if memo.exists() and memo.stat().st_size > 200:
            score.lane = lane.id
            score.error = "" if attempt == 1 else f"lane {attempt}: {','.join(tried)}"
            break
        score.error = f"no memo from {','.join(tried)} ({res.verdict})"
        score.lane = ",".join(tried)
    score.elapsed_sec = round(time.monotonic() - started, 1)
    write_memo_grader(task, workdir, kit)
    p, t, sk, details = run_memo_grader(task, workdir, kit)
    score.passed, score.total, score.skipped, score.details = p, t, sk, details
    return score


def run_research_engine(task: dict, workdir: Path, depth: int, lanes_file: Path | None,
                        health: dict | None = None,
                        dept: str = "research") -> Score:
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    score = Score(task["id"], "engine")
    run_dir = workdir.parent / f"{workdir.name}-run"
    kit = research_kit(dept)
    started = time.monotonic()
    ledger = Ledger(run_dir)
    try:
        spec = spec_mod.from_dict(build_research_spec(task, workdir, depth, dept))
        outcome = orchestrator.run(spec, run_dir, lanes_file=lanes_file, health=health)
        score.error = "" if outcome.status == "DONE" else outcome.status
    except Exception as exc:                                   # noqa: BLE001
        score.error = f"{type(exc).__name__}: {exc}"[:300]
    score.elapsed_sec = round(time.monotonic() - started, 1)
    summary = ledger.summary()
    score.cost = summary["total_cost"]
    score.calls = summary["lane_calls"]
    score.lane = ",".join(sorted({e.get("lane", "")
                                 for e in ledger.events("lane_call")}))[:60]
    score.gates = [{"name": g.get("check"), "passed": g.get("passed"),
                    "stage": g.get("stage"), "reason": g.get("reason")}
                   for g in ledger.events("gate")]
    write_memo_grader(task, workdir, kit)
    p, t, sk, details = run_memo_grader(task, workdir, kit)
    score.passed, score.total, score.skipped, score.details = p, t, sk, details
    return score


# ------------------------------------------------------------------ gate calibration

def _delete_section(text: str, title: str) -> str:
    lines = text.splitlines()
    start = end = None
    level = None
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if not m:
            continue
        if start is None and re.match(title, m.group(2), re.I):
            start, level = i, len(m.group(1))
            continue
        if start is not None and len(m.group(1)) <= level:
            end = i
            break
    if start is None:
        raise ValueError(f"no {title!r} section to delete")
    return "\n".join(lines[:start] + lines[end if end else len(lines):])


def _section_span(lines, title):
    start = end = None
    level = None
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if not m:
            continue
        if start is None and re.match(title, m.group(2), re.I):
            start, level = i, len(m.group(1))
            continue
        if start is not None and len(m.group(1)) <= level:
            end = i
            break
    return start, (end if end else len(lines))


def _replace_section_body(text: str, title: str, new_body: str) -> str:
    lines = text.splitlines()
    start, end = _section_span(lines, title)
    if start is None:
        raise ValueError(f"no {title!r} section to rewrite")
    return "\n".join(lines[:start + 1] + [new_body] + lines[end:])


def _move_section_before(text: str, moved: str, target: str) -> str:
    lines = text.splitlines()
    ms, me = _section_span(lines, moved)
    block = lines[ms:me]
    rest = lines[:ms] + lines[me:]
    ts, _te = _section_span(rest, target)
    if ts is None:
        raise ValueError(f"target section {target} missing")
    return "\n".join(rest[:ts] + block + rest[ts:])


def apply_probe_edits(text: str, edits: list) -> str:
    for edit in edits:
        if "sub" in edit:
            pattern, repl, count = edit["sub"]
            text, n = re.subn(pattern, repl, text, count or 0)
            if not n:
                raise ValueError(f"probe edit matched nothing: {pattern}")
        elif "delete_section" in edit:
            text = _delete_section(text, edit["delete_section"])
        elif "replace_section_body" in edit:
            title, new = edit["replace_section_body"]
            text = _replace_section_body(text, title, new)
        elif "cut_from" in edit:
            heading = edit["cut_from"]
            idx = text.find(heading)
            if idx < 0:
                raise ValueError(f"no {heading}")
            text = text[:idx].rstrip() + "\n"
        elif "move_section_before" in edit:
            moved, target = edit["move_section_before"]
            text = _move_section_before(text, moved, target)
        elif "delete_lines_matching" in edit:
            rx = re.compile(edit["delete_lines_matching"])
            text = "\n".join(l for l in text.splitlines() if not rx.match(l.strip()))
        else:
            raise ValueError(f"unknown probe edit {list(edit)}")
    return text


def run_gate_calibration(out_dir: Path, dept: str = "research",
                         task_id: str = "decision-archive-host") -> dict:
    """Does each gate actually reject the defect it claims to reject?

    Nothing here calls a model: it is the cheapest and most important measurement in
    the suite, because a gate that passes everything makes every other number a lie.
    """
    from . import departments as dept_mod
    from . import bench_tasks
    from .gate import run_check
    prof = dept_mod.load(research_kit(dept))
    task = bench_tasks.research_task(task_id)
    kit = Path(prof.dir).resolve()
    out_dir = Path(out_dir).resolve()
    util.write_json(out_dir / "GATE_TASK.json",
                    {k: v for k, v in task.items() if k != "statement"})

    rows = []
    for probe in bench_tasks.RESEARCH_GATE_PROBES:
        memo_text = apply_probe_edits(bench_tasks.GOOD_DECISION_MEMO, probe["edits"])
        workdir = out_dir / "probes" / probe["name"]
        workdir.mkdir(parents=True, exist_ok=True)
        memo = workdir / "memo.md"
        memo.write_text(memo_text)
        ledger = Ledger(workdir / "run")
        spec_dict = build_research_spec(task, workdir, 4, dept)
        checks = _spec_checks(spec_dict, prof, memo)
        results = [run_check(c, workdir) for c in checks]
        gate_rows = []
        for res in results:
            gate_rows.append({"name": res.name, "passed": res.passed,
                              "exit_code": res.exit_code, "reason": res.reason,
                              "first_problem": (res.stdout_tail.splitlines() or [""])[0],
                              "stderr_head": (res.stderr_tail.splitlines() or [""])[0],
                              "output": res.stdout_tail + "\n" + res.stderr_tail})
            util.write_text(out_dir / "probes" / probe["name"] /
                            f"gate.{util.slugify(res.name)}.txt",
                            f"$ {res.cmd}\nexit={res.exit_code} passed={res.passed}\n"
                            f"--- stdout ---\n{res.stdout_tail}\n"
                            f"--- stderr ---\n{res.stderr_tail}\n")
        ledger.event("calibration", probe=probe["name"], gates=gate_rows)

        write_memo_grader(task, workdir, kit)
        passed, total, skipped, details = run_memo_grader(task, workdir, kit)
        failed_tests = [d["test"] for d in details if d["result"] in ("FAIL", "ERROR")]

        expect = probe["expect"]
        if expect == "passes-everything":
            as_expected = (not failed_tests
                           and all(g["passed"] for g in gate_rows if g["name"] != "n/a"))
            caught_by = "nothing: the memo is clean"
        elif expect.startswith("gate:"):
            want = expect[len("gate:"):]
            hit = [g for g in gate_rows if g["name"] == want and not g["passed"]]
            as_expected = bool(hit) and (
                not probe.get("needle")
                or probe["needle"].lower() in hit[0]["output"].lower())
            caught_by = hit[0]["name"] if hit else "NOTHING: gate passed a bad memo"
        else:
            want = expect.split(":", 1)[1]
            as_expected = want in failed_tests
            caught_by = want if as_expected else "NOTHING: hidden test passed a bad memo"
        rows.append({"probe": probe["name"], "expect": expect, "note": probe.get("note", ""),
                     "gates": gate_rows, "hidden_passed": passed,
                     "hidden_total": total, "hidden_skipped": skipped,
                     "hidden_failed": failed_tests, "caught_by": caught_by,
                     "as_expected": as_expected,
                     "memo": str(memo)})

    clean = sum(1 for r in rows if r["expect"] != "passes-everything")
    caught = sum(1 for r in rows if r["expect"] != "passes-everything" and r["as_expected"])
    good_ok = any(r["expect"] == "passes-everything" and r["as_expected"] for r in rows)
    return {"suite": "gates", "department": dept, "task": task_id,
            "probes": len(rows) - 1, "defects_caught": caught, "defects_total": clean,
            "clean_memo_passes": good_ok, "all_as_expected": caught == clean and good_ok,
            "rows": rows}


# ------------------------------------------------------------------ research driver

def run_research_quality(tasks: list, modes: list, depth: int, lanes_file: Path | None,
                         out_dir: Path, timeout_sec: int,
                         dept: str = "research") -> dict:
    from . import departments as dept_mod
    out_dir = Path(out_dir).resolve()
    pool, defaults = lanes_mod.load_lanes(lanes_file)
    guard.enforce(pool)
    kit = dept_mod.load(research_kit(dept)).dir
    health = lanes_mod.probe([ln for ln in pool if ln.enabled and not ln.readonly],
                             int(defaults.get("probe_timeout_sec", 90)),
                             int(defaults.get("max_parallel", 3)),
                             workdir=out_dir / "probe")
    scores: list[Score] = []
    if not health["live"]:
        return {"suite": "research", "depth": depth, "live_lanes": [],
                "by_mode": {}, "scores": [], "error": "no live builder lane",
                "cost_violation": None}

    for task in tasks:
        for mode in modes:
            workdir = out_dir / task["id"] / mode
            if mode == "baseline":
                score = run_research_baseline(task, pool, health, workdir, timeout_sec,
                                              dept)
            else:
                score = run_research_engine(task, workdir, depth, lanes_file, health,
                                            dept)
            scores.append(score)
            util.write_json(out_dir / "research-scores.json", [s.as_dict() for s in scores])
            print(f"  {task['id']:<24} {mode:<9} {score.passed}/{score.total} "
                  f"({score.rate:.0%}) skipped={score.skipped} "
                  f"{score.elapsed_sec}s cost={score.cost} {score.error}", flush=True)
            if score.cost:
                # Free-only rule: stop the suite the moment anything is billed.
                util.write_json(out_dir / "COST_VIOLATION.json",
                                {"task": task["id"], "mode": mode, "cost": score.cost,
                                 "lanes": score.lane, "at": util.utc_now()})
                raise RuntimeError(f"NONZERO COST {score.cost} on {task['id']}/{mode} "
                                   f"(lanes {score.lane}); stopping, paid models are banned")
            if mode == "engine":
                leaked = audit_hidden_visibility(workdir.parent / f"{workdir.name}-run")
                util.write_json(out_dir / f"{task['id']}-visibility-audit.json", leaked)

    by_mode = {}
    for mode in modes:
        rows = [s for s in scores if s.mode == mode]
        passed = sum(s.passed for s in rows)
        total = sum(s.total for s in rows)
        by_mode[mode] = {
            "tests_passed": passed, "tests_total": total,
            "rate": round(passed / total, 4) if total else 0.0,
            "skipped": sum(s.skipped for s in rows),
            "memos_fully_graded": sum(1 for s in rows if s.total and s.passed == s.total),
            "tasks": len(rows),
            "seconds": round(sum(s.elapsed_sec for s in rows), 1),
            "cost": round(sum(s.cost for s in rows), 6),
            "lane_calls": sum(s.calls for s in rows),
            "lanes": sorted({l for s in rows for l in str(s.lane).split(",") if l}),
        }
    return {"suite": "research", "depth": depth, "department": dept, "kit": str(kit),
            "live_lanes": health["live"], "by_mode": by_mode,
            "scores": [s.as_dict() for s in scores], "cost_violation": None}


HIDDEN_MARKERS = ("test_memo_hidden", "MIN_CITED_SHARE", "MIN_SOURCES",
                  "GRADER_BODY", "numbers_outside_findings", "RESEARCH_GATE_PROBES",
                  "hidden thresholds")


def audit_hidden_visibility(run_dir: Path) -> dict:
    """Proof that no lane prompt or transcript ever contained the hidden thresholds.

    The grader is only written after the build, but a lane could in principle have read
    engine/bench.py and quoted what it found. This greps every prompt and reply the run
    stored and says so if any did.
    """
    hits = []
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return {"run_dir": str(run_dir), "scanned": 0, "hits": ["run dir missing"]}
    scanned = 0
    for path in list(run_dir.rglob("*.prompt.md")) + list(run_dir.rglob("*.reply.md")):
        scanned += 1
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for marker in HIDDEN_MARKERS:
            if marker in text:
                hits.append(f"{path.name}: {marker}")
    return {"run_dir": str(run_dir), "scanned": scanned, "hits": hits[:20],
            "clean": not hits}


def write_research_report(result: dict, out_dir: Path) -> Path:
    """The research receipt data: gate calibration first, then baseline versus engine."""
    lines = ["# Research department benchmark report", "",
             f"- Run: {out_dir.name}", f"- Finished: {util.ist_now()} ({util.utc_now()})",
             f"- Kit: {result.get('research', {}).get('kit', '')}",
             f"- Depth: {result.get('research', {}).get('depth')}", ""]

    g = result.get("gates")
    if g:
        lines += ["## Gate calibration (no models; this is the rejection test)", "",
                  f"- Defects injected: {g['defects_total']}, caught: "
                  f"{g['defects_caught']}, all as expected: {g['all_as_expected']}",
                  f"- Clean reference memo passes every gate and the hidden suite: "
                  f"{g['clean_memo_passes']}", "",
                  "| probe | expected catcher | actually caught by | hidden fails | verdict |",
                  "|---|---|---|---|---|"]
        for row in g["rows"]:
            hidden = ", ".join(row["hidden_failed"]) or "none"
            lines.append(f"| {row['probe']} | {row['expect']} | {row['caught_by']} "
                         f"| {hidden[:60]} | {'as expected' if row['as_expected'] else 'PROBLEM'} |")
        lines.append("")
        for row in g["rows"]:
            failing = [x for x in row["gates"] if not x["passed"]]
            if failing:
                lines.append(f"- `{row['probe']}` first problem: "
                             f"`{failing[0]['first_problem'][:160]}`")
        lines.append("")

    q = result.get("research")
    if q:
        lines += ["## Quality suite: one free lane, one shot, versus the pipeline", "",
                  f"- Live free lanes: {', '.join(q['live_lanes'])}", ""]
        if q.get("error"):
            lines += [f"- SUITE ERROR: {q['error']}", ""]
        lines += ["| mode | hidden checks passed | rate | memos fully graded | seconds "
                  "| lane calls | cost |", "|---|---|---|---|---|---|---|"]
        for mode, m in q["by_mode"].items():
            lines.append(f"| {mode} | {m['tests_passed']}/{m['tests_total']} "
                         f"| {m['rate']:.0%} | {m['memos_fully_graded']}/{m['tasks']} "
                         f"| {m['seconds']} | {m['lane_calls']} | {m['cost']} |")
        lines.append("")
        if "baseline" in q["by_mode"] and "engine" in q["by_mode"]:
            b, e = q["by_mode"]["baseline"], q["by_mode"]["engine"]
            lines += [f"The pipeline moved the hidden-check pass rate from {b['rate']:.0%} "
                      f"to {e['rate']:.0%} ({e['rate'] - b['rate']:+.0%}) on the same free "
                      f"models, at a total reported cost of {e['cost']}. Skipped checks: "
                      f"baseline {b['skipped']}, engine {e['skipped']} "
                      f"(skips are never counted as passes).", ""]
        lines += ["### Per task", "",
                  "| task | mode | lanes | passed | rate | skipped | seconds | cost "
                  "| gates failed | note |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for s in q["scores"]:
            total = s["total"] or 1
            gf = sorted({x["name"] for x in (s.get("gates") or []) if not x["passed"]})
            lines.append(f"| {s['task']} | {s['mode']} | {s['lane']} "
                         f"| {s['passed']}/{s['total']} | {s['passed'] / total:.0%} "
                         f"| {s.get('skipped', 0)} | {s['elapsed_sec']} | {s['cost']} "
                         f"| {', '.join(gf)[:80] or '-'} | {s.get('error', '')} |")
        lines.append("")
        for s in q["scores"]:
            if not s.get("details"):
                continue
            lines += [f"#### {s['task']} / {s['mode']}", ""]
            for d in s["details"]:
                lines.append(f"- {d['test']}: {d['result']}")
            lines.append("")
        audits = sorted(out_dir.glob("*-visibility-audit.json"))
        if audits:
            lines += ["### Hidden-test visibility audit", ""]
            for a in audits:
                data = util.read_json(a) or {}
                lines.append(f"- {data.get('run_dir')}: {data.get('scanned')} files "
                             f"scanned, clean={data.get('clean')}, "
                             f"hits={data.get('hits')}")
            lines.append("")

    path = out_dir / "BENCH_REPORT.md"
    util.write_text(path, "\n".join(lines))
    util.write_json(out_dir / "bench.json", result)
    return path


def output_negative_audit(memo: Path, out_dir: Path, task_id: str = "decision-archive-host",
                          dept: str = "research") -> dict:
    """Run the gates on the real artifact, then on three broken copies of it.

    A gate that passed the memo a lane actually wrote is only credible if the same
    command line fails when that memo is damaged. Each copy loses one thing, the way a
    bad memo loses it in practice: a citation removed, the Sources section cut, a
    placeholder left in. Nothing here calls a model, and the commands are the ones the
    engine expanded from the kit profile for this very deliverable.
    """
    from . import departments as dept_mod
    from . import bench_tasks
    from .gate import run_check
    prof = dept_mod.load(research_kit(dept))
    task = bench_tasks.research_task(task_id)
    memo = Path(memo).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    text = memo.read_text(errors="replace")

    def strip_a_claim_citation(t: str) -> str:
        """Delete one citation from inside Findings, not from the Sources list."""
        m = re.search(r"^#{1,3}\s+.*(findings|claims|evidence).*$", t, re.M | re.I)
        if not m:
            return t
        start = m.end()
        nxt = re.search(r"^#{1,2}\s+", t[start:], re.M)
        end = start + (nxt.start() if nxt else len(t) - start)
        region = t[start:end]
        for pattern in (r" ?\[\d+(?:,\s*\d+)*\]", r" ?\(https?://[^)\s]+\)",
                        r"https?://\S+"):
            shrunk = re.sub(pattern, "", region, count=1)
            if shrunk != region:
                return t[:start] + shrunk + t[end:]
        return t

    sources_heading = "## Sources" if "## Sources" in text else "## References"
    variants = [("as-written", text)]
    variants.append(("citation-removed", strip_a_claim_citation(text)))
    variants.append(("sources-section-cut",
                     apply_probe_edits(text, [{"cut_from": sources_heading}])
                     if sources_heading in text else text))
    variants.append(("placeholder-left-in", text + "\n\n## Appendix\n[insert the count]\n"))
    variants.append(("recommendation-deleted",
                     apply_probe_edits(text, [{"delete_section": "Recommendation"}])
                     if re.search(r"^##\s+Recommendation", text, re.M) else text))

    checks = _spec_checks(build_research_spec(task, memo.parent, 4, dept), prof, memo)
    rows = []
    for name, body in variants:
        workdir = out_dir / name
        workdir.mkdir(parents=True, exist_ok=True)
        copy = workdir / "memo.md"
        copy.write_text(body)
        gate_checks = _spec_checks(build_research_spec(task, workdir, 4, dept), prof, copy)
        results = []
        for check in gate_checks:
            res = run_check(check, workdir)
            results.append({"name": res.name, "cmd": res.cmd, "passed": res.passed,
                            "exit_code": res.exit_code, "reason": res.reason,
                            "first_problem": (res.stdout_tail.splitlines()
                                              or res.stderr_tail.splitlines() or [""])[0][:200]})
            util.write_text(workdir / f"gate.{util.slugify(res.name)}.txt",
                            f"$ {res.cmd}\nexit={res.exit_code} passed={res.passed}\n"
                            f"--- stdout ---\n{res.stdout_tail}\n"
                            f"--- stderr ---\n{res.stderr_tail}\n")
        rows.append({"variant": name, "bytes": copy.stat().st_size,
                     "gates": results,
                     "all_passed": all(r["passed"] for r in results),
                     "failed": [r["name"] for r in results if not r["passed"]]})

    written = rows[0]["all_passed"]
    rejected = [r for r in rows[1:] if not r["all_passed"]]
    return {"memo": str(memo), "task": task_id, "out_dir": str(out_dir),
            "as_written_passes": written, "variants_tested": len(rows) - 1,
            "variants_rejected": len(rejected),
            "every_damage_rejected": written and len(rejected) == len(rows) - 1,
            "rows": rows}
