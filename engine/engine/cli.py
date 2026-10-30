"""engctl command line.

    engctl draft "<request>"          plain English -> validated spec (the front door)
    engctl draft --issue <id> --run   draft from a board issue, then run it
    engctl probe                      health-probe every lane, print the live pool
    engctl lanes                      show the pool and the free-tier audit
    engctl validate <spec>            intake gate only: is this task specifiable?
    engctl run <spec> [--dry-run]     full pipeline
    engctl status <run-id|path>       ledger summary for a run
    engctl reap [--kill]              find hung lane processes (reap only if asked)
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from . import guard, lanes as lanes_mod, orchestrator, report as report_mod, spec as spec_mod, util
from .ledger import Ledger


def _install_reaper() -> None:
    """Never leave a lane behind: reap child process groups on exit and on signals."""
    atexit.register(lanes_mod.reap_all_children)

    def handler(signum, _frame):
        n = lanes_mod.reap_all_children()
        print(f"\nengctl: received signal {signum}, reaped {n} lane process group(s)",
              file=sys.stderr)
        sys.exit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, handler)


def _print_lane_audit(audit: dict) -> None:
    print(f"{'lane':<14} {'free':<5} {'on':<4} model")
    print("-" * 78)
    for v in audit["verdicts"]:
        print(f"{v['lane']:<14} {'yes' if v['free'] else 'NO':<5} "
              f"{'yes' if v['enabled'] else '-':<4} {v['model']}")
    print(f"\nenabled lanes: {audit['enabled_total']}, "
          f"provably free: {audit['enabled_free']}")
    if audit["violations"]:
        print("\nREFUSED (enabled but not provably free):")
        for v in audit["violations"]:
            print(f"  {v['lane']}: {v['reason']}")


def cmd_lanes(args) -> int:
    pool, defaults = lanes_mod.load_lanes(args.lanes)
    audit = guard.audit_lanes(pool)
    _print_lane_audit(audit)
    print(f"\ndefaults: {json.dumps(defaults)}")
    return 1 if audit["violations"] else 0


def cmd_probe(args) -> int:
    pool, defaults = lanes_mod.load_lanes(args.lanes)
    try:
        guard.enforce(pool)
    except guard.PaidModelRefused as exc:
        print(f"RESULT: BLOCKED - {exc}")
        return 2
    print(f"probing {sum(1 for l in pool if l.enabled)} enabled lanes "
          f"({defaults.get('probe_timeout_sec', 90)}s ceiling each, "
          f"{defaults.get('max_parallel', 3)} at a time)...\n")
    health = lanes_mod.probe(pool, int(defaults.get("probe_timeout_sec", 90)),
                             int(defaults.get("max_parallel", 3)))
    for res in health["results"]:
        mark = "ok  " if res["verdict"] == "ok" else "DEAD"
        print(f"{mark} {res['lane_id']:<14} {res['verdict']:<14} "
              f"{res['elapsed_sec']:>5}s  cost={res.get('cost', 0)}  {res['model']}")
    print(f"\nlive: {', '.join(health['live']) or 'NONE'}")
    print(f"total reported cost across all probes: {health.get('total_cost', 0)}")
    if health.get("dead"):
        print(f"dead: {json.dumps(health['dead'])}")
    if args.out:
        util.write_json(Path(args.out), health)
        print(f"written: {args.out}")
    return 0 if health["live"] else 2


def cmd_validate(args) -> int:
    try:
        spec = spec_mod.load(args.spec)
    except spec_mod.SpecError as exc:
        print(f"RESULT: BLOCKED - spec rejected: {exc}")
        return 2
    print(f"spec ok: {spec.id}")
    print(f"  title       : {spec.title}")
    print(f"  depth       : {spec.depth} -> {json.dumps(spec.profile)}")
    print(f"  deliverables: {len(spec.deliverables)}")
    print(f"  acceptance  : {len(spec.acceptance)}")
    print(f"  context src : {len(spec.context_sources)}")
    print(f"  parts frozen: {len(spec.parts)}")
    return 0


def cmd_run(args) -> int:
    try:
        spec = spec_mod.load(args.spec)
    except spec_mod.SpecError as exc:
        print(f"RESULT: BLOCKED - spec rejected: {exc}")
        return 2
    return _run_spec(spec, args)


def _run_spec(spec, args) -> int:
    pool, _ = lanes_mod.load_lanes(args.lanes)
    try:
        audit = guard.enforce(pool)
    except guard.PaidModelRefused as exc:
        print(f"RESULT: BLOCKED - {exc}")
        return 2

    run_id = args.run_id or f"{util.utc_now().replace(':', '').replace('-', '')}-{spec.id}"
    run_dir = Path(args.run_dir) if args.run_dir else util.RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    util.write_json(run_dir / "FREE_LANE_AUDIT.json", audit)

    print(f"run     : {run_id}")
    print(f"dir     : {run_dir}")
    print(f"spec    : {spec.title} (depth {spec.depth})")
    print(f"lanes   : {audit['enabled_free']} free lanes enabled, paid refused\n")

    ledger = Ledger(run_dir)
    try:
        outcome = orchestrator.run(spec, run_dir, dry_run=args.dry_run,
                                   lanes_file=args.lanes)
    except Exception as exc:                       # noqa: BLE001 - must always report
        ledger.event("run_error", error=str(exc)[:1500], type=type(exc).__name__)
        print(f"RESULT: FAILED - {type(exc).__name__}: {exc}")
        return 3

    report_path = report_mod.write_report(spec, outcome, ledger, run_dir)
    ledger.event("run_end", status=outcome.status, detail=outcome.detail[:800])
    print(f"\n--- {outcome.result_line}")
    print(f"report: {report_path}")
    print(f"ledger: {ledger.path}")
    print(json.dumps(ledger.summary(), indent=2))

    issue = args.board_issue or spec.board_issue
    if issue and not args.dry_run:
        body = report_mod.board_summary(spec, outcome, ledger, report_path)
        ok, detail = report_mod.post_to_board(issue, body)
        print(f"board comment: {'posted ' + detail if ok else 'FAILED ' + detail}")

    return 0 if outcome.status == "DONE" else 1


def cmd_draft(args) -> int:
    """Plain-English request or board issue -> validated spec, optionally run."""
    from . import draft as draft_mod

    if args.issue:
        try:
            title, request = draft_mod.fetch_issue(args.issue)
        except RuntimeError as exc:
            print(f"RESULT: BLOCKED - {exc}")
            return 2
        slug = args.slug or title
    else:
        request = " ".join(args.request).strip()
        slug = args.slug or request[:48]
    if len(request) < 20:
        print("RESULT: BLOCKED - the request is too short to draft a task from. "
              "Say what outcome you want and how you will judge it.")
        return 2

    pool, defaults = lanes_mod.load_lanes(args.lanes)
    try:
        guard.enforce(pool)
    except guard.PaidModelRefused as exc:
        print(f"RESULT: BLOCKED - {exc}")
        return 2

    profile = None
    if args.dept:
        from . import departments as dept_mod
        try:
            profile = dept_mod.find(args.dept)
        except (dept_mod.ProfileError, OSError) as exc:
            print(f"RESULT: BLOCKED - department '{args.dept}' could not be loaded: {exc}")
            return 2

    # Probe only the lanes drafting can use, so the front door stays fast.
    candidates = [ln for ln in pool
                  if ln.enabled and (ln.supports("plan") or ln.supports("redteam"))]
    print(f"probing {len(candidates)} drafting lanes...")
    health = lanes_mod.probe(candidates, int(defaults.get("probe_timeout_sec", 90)),
                             int(defaults.get("max_parallel", 3)))
    print(f"live: {', '.join(health['live']) or 'NONE'}")
    if not health["live"]:
        print("RESULT: BLOCKED - no live drafting lane: " + json.dumps(health["dead"]))
        return 2

    result = draft_mod.draft_spec(request, pool, health,
                                  int(defaults.get("timeout_sec", 900)), slug_hint=slug,
                                  profile=profile, depth=args.depth)
    if result.get("blocked"):
        print(f"RESULT: ESCALATED - the request needs an Owner decision: {result['blocked']}")
        return 1
    if result.get("rejected"):
        print(f"RESULT: BLOCKED - the drafted spec still fails the intake gate after "
              f"one repair: {result['rejected']}")
        print(f"draft log: {result['log_dir']}")
        return 2

    spec_dict = result["spec"]
    if args.board_issue or args.issue:
        spec_dict["board_issue"] = args.board_issue or args.issue
    path = draft_mod.save_spec(spec_dict, Path(__file__).resolve().parent.parent / "specs")
    print(f"\nspec drafted and validated: {path}")
    print(f"  title       : {spec_dict['title']}")
    print(f"  depth       : {spec_dict.get('depth')}")
    print(f"  deliverables: {len(spec_dict.get('deliverables') or [])}")
    print(f"  acceptance  : {len(spec_dict.get('acceptance') or [])}")
    print(f"  workdir     : {result['workdir']}")
    print(f"  draft trail : {result['log_dir']}")
    for step in result["history"]:
        print(f"    - {step['stage']}: lane {step['lane']}, {step.get('verdict')}, "
              f"{step.get('elapsed_sec')}s")

    if not args.run:
        print(f"\nreview it, then:  engctl run {path}")
        return 0
    spec = spec_mod.load(path)
    args.run_id = args.run_id or None
    args.run_dir = None
    args.dry_run = False
    return _run_spec(spec, args)


def cmd_bench(args) -> int:
    """Benchmark the department: safety guarantees, live lanes, and hidden-test quality."""
    from . import bench as bench_mod, bench_tasks
    stamp = util.utc_now().replace(":", "").replace("-", "")
    out_dir = Path(args.out) if args.out else bench_mod.BENCH_ROOT / f"bench-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {}

    if args.departments:
        # Benchmark against staged kits before they are installed live.
        from . import departments as dept_mod
        dept_mod.DEPARTMENTS_ROOT = Path(args.departments)
        os.environ["ENG_DEPARTMENTS"] = str(args.departments)
        print(f"departments: {args.departments}")

    if args.suite in ("safety", "all"):
        print("=== safety suite (deterministic, no models) ===", flush=True)
        s = bench_mod.run_safety()
        result["safety"] = s
        print(f"  {'PASS' if s['passed'] else 'FAIL'} — {s['tests']} tests")
        for f in s["failures"]:
            print(f"    {f}")

    if args.suite in ("lanes", "all"):
        print("\n=== lane suite (live health probe) ===", flush=True)
        ln = bench_mod.run_lanes(args.lanes, out_dir)
        result["lanes"] = ln
        print(f"  {len(ln['live'])}/{ln['enabled']} live across "
              f"{len(ln['families'])} families, cost {ln['total_cost']}")
        if ln["dead"]:
            print(f"  dead: {json.dumps(ln['dead'])}")

    if args.suite in ("quality", "all"):
        tasks = ([bench_tasks.by_id(t) for t in args.tasks.split(",")]
                 if args.tasks else bench_tasks.TASKS[:args.limit])
        modes = args.modes.split(",")
        print(f"\n=== quality suite ({len(tasks)} tasks, modes {modes}, "
              f"depth {args.depth}) ===", flush=True)
        result["quality"] = bench_mod.run_quality(
            tasks, modes, args.depth, args.lanes, out_dir, args.timeout)
        for mode, m in result["quality"]["by_mode"].items():
            print(f"  {mode}: {m['tests_passed']}/{m['tests_total']} "
                  f"({m['rate']:.0%}), {m['tasks_fully_solved']}/{m['tasks']} fully solved")

    if args.suite == "design":
        from . import bench_design
        tasks = ([bench_design.by_id(t) for t in args.tasks.split(",")]
                 if args.tasks else bench_design.DESIGN_TASKS)
        modes = args.modes.split(",")
        print(f"\n=== design suite ({len(tasks)} tasks, modes {modes}, "
              f"depth {args.depth}) ===", flush=True)
        result["design"] = bench_mod.run_design(
            tasks, modes, args.depth, args.lanes, out_dir, args.timeout)
        d = result["design"]
        if d.get("error"):
            print(f"  REFUSED: {d['error']}")
        for mode, m in d.get("by_mode", {}).items():
            print(f"  {mode}: {m['gates_passed']}/{m['gates_total']} gates "
                  f"({m['rate']:.0%}), {m['tasks_fully_solved']}/{m['tasks']} fully solved")
        if d.get("paid_cost_detected"):
            print(f"  STOPPED: {d['paid_cost_detected']}")

    if args.suite in ("gates", "research"):
        print("\n=== gate calibration (deterministic: does each gate reject what it "
              "claims to?) ===", flush=True)
        g = bench_mod.run_gate_calibration(out_dir / "gates", dept=args.dept)
        result["gates"] = g
        print(f"  defects caught {g['defects_caught']}/{g['defects_total']}; clean memo "
              f"passes everything: {g['clean_memo_passes']}")
        for row in g["rows"]:
            mark = "ok " if row["as_expected"] else "BAD"
            print(f"  {mark} {row['probe']:<34} expect={row['expect']:<46} "
                  f"caught_by={row['caught_by']}")

    if args.suite == "research":
        tasks = ([bench_tasks.research_task(t) for t in args.tasks.split(",")]
                 if args.tasks else bench_tasks.RESEARCH_TASKS)
        modes = args.modes.split(",")
        print(f"\n=== research suite ({len(tasks)} memos, modes {modes}, "
              f"depth {args.depth}, kit {args.dept}) ===", flush=True)
        try:
            result["research"] = bench_mod.run_research_quality(
                tasks, modes, args.depth, args.lanes, out_dir, args.timeout, args.dept)
        except RuntimeError as exc:
            result["research"] = {"suite": "research", "error": str(exc), "by_mode": {},
                                  "scores": []}
            print(f"  STOPPED: {exc}")
        for mode, m in result["research"].get("by_mode", {}).items():
            print(f"  {mode}: {m['tests_passed']}/{m['tests_total']} "
                  f"({m['rate']:.0%}), {m['memos_fully_graded']}/{m['tasks']} memos "
                  f"fully graded, cost {m['cost']}")

    path = bench_mod.write_report(result, out_dir)
    print(f"\nreport: {path}")
    failed = (result.get("safety", {}).get("passed") is False
              or bool(result.get("lanes", {}).get("violations"))
              or (result.get("gates") or {}).get("all_as_expected") is False
              or bool((result.get("research") or {}).get("cost_violation"))
              or bool((result.get("research") or {}).get("error"))
              or result.get("design", {}).get("paid_cost_detected") is not None
              or (args.suite == "design"
                  and (result.get("design", {}).get("error") is not None
                       or result.get("design", {}).get("negatives", {}).get("passed") is False)))
    return 1 if failed else 0


def cmd_dept(args) -> int:
    """Validate a department kit: profile, charter, runbook, skills, tools and tests."""
    from . import departments as dept_mod
    target = Path(args.path)
    if not (target / "profile.yaml").exists():
        target = dept_mod.DEPARTMENTS_ROOT / args.path
    problems = dept_mod.validate(target, run_tool_tests=not args.no_tests)
    if problems:
        print(f"department kit {target}: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    prof = dept_mod.load(target)
    print(f"department kit {target}: OK")
    print(f"  name     : {prof.name}  (output: {prof.output_kind}, web: {prof.web})")
    print(f"  agents   : {', '.join(a['name'] + '@d' + str(a.get('depth', prof.default_depth)) for a in prof.agents)}")
    print(f"  skills   : {len(prof.skills)}   tools: {len(prof.tools)}   "
          f"acceptance templates: {len(prof.acceptance_templates)}")
    print(f"  brief    : {len(prof.brief_section())} chars injected per lane prompt")
    print(f"  skills   : {prof.skill_chars()} of {dept_mod.SKILL_BUDGET} chars used of "
          f"the injection budget")
    for note in prof.skills_dropped():
        print(f"  warn     : {note}")
    return 0


def cmd_status(args) -> int:
    target = Path(args.run)
    if not target.exists():
        target = util.RUNS_DIR / args.run
    if not target.exists():
        print(f"no such run: {args.run}")
        return 2
    ledger = Ledger(target)
    print(f"run dir: {target}")
    print(json.dumps(ledger.summary(), indent=2))
    report = target / "RUN_REPORT.md"
    if report.exists():
        print(f"\nreport: {report} ({report.stat().st_size} bytes)")
    return 0


def cmd_reap(args) -> int:
    """Find lane processes that are hung. Killing is opt-in and never automatic."""
    out = subprocess.run(["bash", "-lc",
                          "ps -eo pid,etimes,rss,args | grep -E '[ko](ilo|pencode)' "
                          "| grep -v grep"],
                         capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, etimes, rss, cmd = parts
        try:
            etimes, rss = int(etimes), int(rss)
        except ValueError:
            continue
        if etimes >= args.older_than:
            rows.append((pid, etimes, rss, cmd))

    if not rows:
        print(f"no lane process older than {args.older_than}s")
        return 0
    total_mb = sum(r[2] for r in rows) / 1024
    print(f"{len(rows)} lane process(es) older than {args.older_than}s, "
          f"holding {total_mb:.0f} MB:\n")
    for pid, etimes, rss, cmd in rows:
        print(f"  pid {pid:<8} age {etimes // 3600}h{(etimes % 3600) // 60:02d}m  "
              f"rss {rss // 1024}MB  {cmd[:90]}")
    if not args.kill:
        print("\nread-only. re-run with --kill to terminate these.")
        return 0
    for pid, *_ in rows:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(int(pid), sig)
            except (ProcessLookupError, PermissionError) as exc:
                print(f"  pid {pid}: {exc}")
                break
    print(f"\nsignalled {len(rows)} process(es)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="engctl",
        description="Engineering department task engine. Free lanes only, "
                    "deterministic gates, receipts enforced in code.")
    parser.add_argument("--lanes", default=None, help="path to lanes.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("lanes", help="show the lane pool and free-tier audit").set_defaults(
        func=cmd_lanes)

    p = sub.add_parser("probe", help="health-probe every enabled lane")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("validate", help="run the intake gate on a spec")
    p.add_argument("spec")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="execute a task spec")
    p.add_argument("spec")
    p.add_argument("--dry-run", action="store_true",
                   help="validate intake and lane selection, dispatch nothing")
    p.add_argument("--run-id", default=None)
    p.add_argument("--run-dir", default=None)
    p.add_argument("--board-issue", default=None,
                   help="Paperclip issue id to post the summary to")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="ledger summary for a run")
    p.add_argument("run")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("dept", help="validate a department kit")
    p.add_argument("path", help="department directory, or a department name")
    p.add_argument("--no-tests", action="store_true")
    p.set_defaults(func=cmd_dept)

    p = sub.add_parser("bench", help="benchmark safety guarantees, live lanes, and quality")
    p.add_argument("--suite",
                   choices=["safety", "lanes", "quality", "design", "research", "gates",
                            "all"], default="all")
    p.add_argument("--modes", default="baseline,engine",
                   help="quality modes: baseline (one shot) and/or engine (full pipeline)")
    p.add_argument("--tasks", default=None, help="comma-separated benchmark task ids")
    p.add_argument("--limit", type=int, default=2, help="how many tasks when --tasks is unset")
    p.add_argument("--depth", type=int, default=3)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--dept", default="research",
                   help="department kit for the research and gates suites")
    p.add_argument("--departments", default=None,
                   help="department root to use (e.g. the staged kits)")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("draft", help="turn a plain-English request or a board issue "
                                     "into a validated spec")
    p.add_argument("request", nargs="*", help="the request, in plain English")
    p.add_argument("--issue", default=None, help="draft from a Paperclip issue id")
    p.add_argument("--dept", default=None, help="department kit to draft for")
    p.add_argument("--depth", type=int, default=None, help="force engine depth 1-5")
    p.add_argument("--slug", default=None)
    p.add_argument("--run", action="store_true", help="run the spec once it validates")
    p.add_argument("--run-id", default=None)
    p.add_argument("--board-issue", default=None)
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("reap", help="list (and optionally kill) hung lane processes")
    p.add_argument("--older-than", type=int, default=3600)
    p.add_argument("--kill", action="store_true")
    p.set_defaults(func=cmd_reap)

    args = parser.parse_args(argv)
    if args.lanes:
        args.lanes = Path(args.lanes)
    _install_reaper()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
