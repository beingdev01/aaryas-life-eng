"""Orchestrator: stage sequencing, safety post-checks, and the final verification gate."""

from __future__ import annotations

import json
from pathlib import Path

from . import execute, gate as gate_mod, lanes as lanes_mod, stages, util
from .ledger import Ledger
from .spec import TaskSpec, to_brief

# A write under any of these during a run is a hard failure, whatever the lanes report.
# Nothing else on the VM writes here on its own schedule, so a change can only be ours.
STRICT_ROOTS = [
    util.HOME / "agents",
    util.HOME / "bin",
    Path("/home/ubuntu/.ssh"),
    util.PIPELINE_DIR / "engine",
    util.PIPELINE_DIR / "lanes.yaml",
]


class RunOutcome:
    def __init__(self, status: str, detail: str = "", data: dict | None = None):
        self.status = status          # DONE | BLOCKED | ESCALATED | FAILED
        self.detail = detail
        self.data = data or {}

    @property
    def result_line(self) -> str:
        if self.status == "DONE":
            return "RESULT: DONE"
        return f"RESULT: {self.status} - {self.detail}"

    def __repr__(self) -> str:
        return f"<RunOutcome {self.status}: {self.detail[:60]}>"


def run(spec: TaskSpec, run_dir: Path, dry_run: bool = False,
        only_probe: bool = False, lanes_file: Path | None = None,
        health: dict | None = None) -> RunOutcome:
    ledger = Ledger(run_dir)
    lanes_mod.COST_BREAKER.reset()

    strict_before = gate_mod.snapshot(STRICT_ROOTS)
    banned = [Path(p) for p in spec.banned_paths]
    banned_before = gate_mod.snapshot(banned) if banned else {}

    try:
        outcome = _execute(spec, run_dir, ledger, dry_run, only_probe, lanes_file, health)
    finally:
        lanes_mod.reap_all_children()

    # Safety post-checks run on every exit path, including failures.
    strict_diff = gate_mod.diff_snapshots(strict_before, gate_mod.snapshot(STRICT_ROOTS))
    banned_diff = (gate_mod.diff_snapshots(banned_before, gate_mod.snapshot(banned))
                   if banned else {"created": [], "modified": [], "deleted": []})
    touched_strict = strict_diff["created"] + strict_diff["modified"] + strict_diff["deleted"]
    touched_banned = banned_diff["created"] + banned_diff["modified"] + banned_diff["deleted"]

    ledger.event("tripwire", strict_changes=touched_strict[:50],
                 banned_changes=touched_banned[:50])
    outcome.data["tripwire"] = {"strict": touched_strict, "banned": touched_banned,
                                "banned_note": ("banned paths can also change through "
                                                "scheduled jobs on this VM, so these are "
                                                "reported for review, not auto-failed")}

    if lanes_mod.COST_BREAKER.tripped:
        hit = lanes_mod.COST_BREAKER.tripped_by
        ledger.event("cost_breaker", **hit)
        return RunOutcome(
            "FAILED",
            f"a provider reported a non-zero cost ({hit['cost']}) on lane {hit['lane']} "
            f"({hit['model']}); all further calls were refused. Free-only rule: this "
            f"lane must be disabled in lanes.yaml before any further run.",
            outcome.data)

    if touched_strict:
        return RunOutcome(
            "FAILED",
            "a lane wrote under a protected path: " + ", ".join(touched_strict[:5]),
            outcome.data)

    # A completed read of a credential path is a security incident, not a style issue.
    # Denied attempts are recorded but do not fail the run: the permission layer held.
    breaches = [h for h in ledger.sensitive_access() if h.get("status") == "completed"]
    attempts = [h for h in ledger.sensitive_access() if h.get("status") != "completed"]
    outcome.data["credential_access"] = {"completed": breaches, "denied": attempts}
    if breaches:
        detail = "; ".join(f"{h['lane']}/{h['tool']}: {h['input'][:80]}"
                           for h in breaches[:3])
        return RunOutcome("FAILED",
                          f"SECURITY: a lane read a credential path ({detail}). "
                          f"Review the run ledger before reusing anything it produced.",
                          outcome.data)

    return outcome


def _execute(spec: TaskSpec, run_dir: Path, ledger: Ledger, dry_run: bool,
             only_probe: bool, lanes_file: Path | None,
             health: dict | None = None) -> RunOutcome:
    lane_pool, defaults = lanes_mod.load_lanes(lanes_file)
    timeout_sec = int(defaults.get("timeout_sec", 900))
    probe_timeout = int(defaults.get("probe_timeout_sec", 90))
    max_parallel = int(spec.max_parallel or defaults.get("max_parallel", 3))

    ledger.event("run_start", spec_id=spec.id, title=spec.title, depth=spec.depth,
                 profile=spec.profile, dry_run=dry_run, max_parallel=max_parallel,
                 at_ist=util.ist_now())
    util.write_json(run_dir / "SPEC.json", spec.raw)
    util.write_text(run_dir / "BRIEF.md", to_brief(spec))

    # ---- probe. A dead lane can look healthy, so this is never skipped on a real run.
    # A caller that already probed may pass its result in, which avoids paying twice.
    if dry_run:
        health = {"live": [ln.id for ln in lane_pool if ln.enabled], "dead": {},
                  "results": [], "note": "dry run: lanes not probed"}
    elif health is None:
        health = lanes_mod.probe(lane_pool, probe_timeout, max_parallel,
                                 workdir=run_dir / "lanes" / "probe")
    else:
        health = {**health, "reused_from_caller": True}
    util.write_json(run_dir / "LANES_LIVE.json", health)
    ledger.stage_done("probe", live=len(health["live"]), dead=len(health.get("dead", {})),
                      live_lanes=health["live"])

    if not health["live"]:
        return RunOutcome("BLOCKED", "no live model lane: " +
                          json.dumps(health.get("dead", {}))[:300], {"health": health})
    if only_probe:
        return RunOutcome("DONE", "probe only", {"health": health})

    families = {ln.family for ln in lane_pool if ln.id in set(health["live"])}
    if len(families) < 2:
        ledger.event("warning", stage="probe",
                     message=("only one live model family, so independent review will "
                              "share the builder's blind spots"),
                     families=sorted(families))

    if dry_run:
        plan_preview = {"parts": spec.parts or [], "dry_run": True}
        util.write_json(run_dir / "PLAN.json", plan_preview)
        ledger.stage_done("dry_run", note="intake and lane selection validated")
        return RunOutcome("DONE", "dry run: spec valid, lanes selected, nothing dispatched",
                          {"health": health, "plan": plan_preview})

    # ---- recon
    pack, _digests = stages.run_recon(spec, lane_pool, health, ledger,
                                      max_parallel, timeout_sec)

    # ---- plan + red team
    plan = stages.run_plan(spec, lane_pool, health, ledger, pack, timeout_sec)
    if plan.get("blocked"):
        return RunOutcome("BLOCKED", f"planner needs an answer: {plan['blocked']}",
                          {"health": health, "plan": plan})
    if plan.get("file_conflicts"):
        ledger.event("warning", stage="plan", message="file ownership conflicts",
                     conflicts=plan["file_conflicts"])

    # ---- build
    outcomes = execute.run_build(spec, plan, lane_pool, health, ledger, pack,
                                 max_parallel, timeout_sec)

    # ---- review and fix
    profile = spec.profile
    reviewed = outcomes
    if profile["review_rounds"] > 0:
        reviewed = execute.run_review(spec, outcomes, lane_pool, health, ledger,
                                      timeout_sec, max_parallel)
        for round_no in range(1, profile["fix_rounds"] + 1):
            pending = [r for r in reviewed
                       if not r["verified"] or any(
                           str(f.get("severity", "")).lower() in ("critical", "high")
                           for f in r["review"].get("findings", []))]
            if not pending:
                break
            reviewed = execute.run_fix(spec, reviewed, lane_pool, health, ledger,
                                       timeout_sec, max_parallel, round_no)
            if round_no < profile["review_rounds"]:
                reviewed = execute.run_review(spec, reviewed, lane_pool, health,
                                              ledger, timeout_sec, max_parallel)

    # ---- integrate
    integration = execute.run_integrate(spec, reviewed, lane_pool, health,
                                        ledger, timeout_sec)

    # ---- verify. The engine checks; no lane is asked whether it succeeded.
    deliv_ok, receipts = gate_mod.check_deliverables(spec.deliverables, ledger, "verify")
    checks_ok, checks = gate_mod.run_all(spec.acceptance, run_dir, ledger, "verify")

    # ---- repair. Feed the real failing output back to a builder, then re-verify.
    # Iterating against actual test output is how cheap lanes reach correctness.
    repairs = []
    max_repairs = 1 if spec.depth <= 2 else 2
    for round_no in range(1, max_repairs + 1):
        if deliv_ok and checks_ok:
            break
        failed = [c for c in checks if not c.passed]
        if not failed and not deliv_ok:
            failed = []
        rep = execute.run_repair(spec, failed, reviewed, lane_pool, health, ledger,
                                 timeout_sec, round_no)
        repairs.append(rep)
        if not rep.get("attempted"):
            break
        deliv_ok, receipts = gate_mod.check_deliverables(spec.deliverables, ledger,
                                                         f"verify.r{round_no}")
        checks_ok, checks = gate_mod.run_all(spec.acceptance, run_dir, ledger,
                                             f"verify.r{round_no}")
        if rep.get("shrunk"):
            ledger.event("warning", stage=f"repair{round_no}",
                         message="repair shrank a deliverable sharply; treating as suspect",
                         shrunk=rep["shrunk"])
            checks_ok = False
            break

    parts_ok = all(r["verified"] for r in reviewed) if reviewed else False
    ledger.stage_done("verify", deliverables_ok=deliv_ok, acceptance_ok=checks_ok,
                      parts_ok=parts_ok, repair_rounds=len(repairs))

    data = {"health": health, "plan": plan, "reviewed": [
        {k: v for k, v in r.items() if k != "part"} for r in reviewed],
        "integration": integration, "repairs": repairs,
        "receipts": [r.__dict__ for r in receipts],
        "checks": [c.__dict__ for c in checks],
        "summary": ledger.summary()}

    # The task's own acceptance checks and deliverables are the definition of done.
    # Per-part verification is a means to that end, so a part that failed its own
    # verify command does not fail a run whose final deliverables all pass.
    if deliv_ok and checks_ok:
        if not parts_ok:
            ledger.event("warning", stage="verify",
                         message="final gates passed although some parts failed "
                                 "their own verify command; integration recovered them",
                         parts=[r["part_id"] for r in reviewed if not r["verified"]])
        return RunOutcome("DONE", "all final gates passed", data)

    reasons = []
    if not deliv_ok:
        missing = [r.path for r in receipts if not r.ok]
        reasons.append(f"deliverables failed: {', '.join(missing[:4])}")
    if not checks_ok:
        failed = [f"{c.name} ({c.reason})" for c in checks if not c.passed]
        reasons.append(f"acceptance failed: {', '.join(failed[:4])}")
    blocked = [r["part_id"] for r in reviewed if r.get("blocked")]
    if blocked:
        return RunOutcome("ESCALATED",
                          f"build lane reported BLOCKED on: {', '.join(blocked)}; "
                          + "; ".join(reasons), data)
    return RunOutcome("FAILED", "; ".join(reasons) or "unknown gate failure", data)
