"""Execution stages: parallel build with sampling, independent review, fix, integrate.

The two mechanisms that buy quality from weak models live here:

- Sampling: on a hard part, K lanes from different families solve the same frozen
  contract in separate workdirs, then a judge picks the best. Cheap lanes, run a few
  times, beat one cheap lane run once.
- Independent review: the reviewer is forced onto a different model family than the
  builder, because a reviewer that shares the builder's blind spots finds nothing.
"""

from __future__ import annotations

import ast
import builtins
import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import gate as gate_mod
from . import lanes as lanes_mod
from . import util
from .spec import Acceptance, TaskSpec, to_brief
from .stages import CONTEXT_BUDGET, _parse_json_reply

BUILD_PROMPT = """You are a build lane. You implement one part of a larger plan.

{brief}

## Context pack (known state, gathered by recon)
{pack}

## YOUR PART — this is a frozen contract. Do not redesign it.
- id: {part_id}
- title: {title}
- contract: {contract}
- files you own (you may write ONLY these, plus files under your workdir): {owns}
- notes: {notes}

## Required outputs
{deliverables}

## Your workdir
{workdir}

## Instructions
1. Read what you need before writing anything.
2. Implement the contract completely. No stubs, no placeholders, no "TODO later",
   no commented-out dead code. If you cannot finish it, say so explicitly.
3. Create every required output at its exact path.
4. Verify your own work with a command before you finish, and show the output.
5. If the contract is wrong or impossible, do NOT improvise a different design.
   Stop and reply with: BLOCKED: <the precise reason and what you need>.

Do not touch any file owned by another part. Do not change the plan.
Finish by listing each file you created or modified, with its byte size."""

JUDGE_PROMPT = """You are judging independent attempts at the same frozen contract.

## The contract
{contract}

## Required outputs
{deliverables}

## The candidates
{candidates}

## Instructions
Pick the single best candidate on correctness first, then completeness, then
simplicity. A candidate that produced the required files beats one that only
described them. Ignore length and confidence of tone.

Reply with ONLY a JSON object:
{{"winner": "<candidate id>", "why": "one or two sentences",
  "defects_in_winner": ["anything the winner still gets wrong"]}}"""

REVIEW_PROMPT = """You are an independent reviewer. You did not build this and you
will not rebuild it. Your job is to find what is actually wrong.

{brief}

## The part under review
- id: {part_id}
- contract: {contract}
- claimed outputs: {deliverables}

## What the builder reported
{builder_report}

## What the engine's own checks found when it ran them
{gate_results}

## The files as they exist on disk now
{file_dump}

## Instructions
Check, in this order:
1. Does every required output exist, and does its content actually satisfy the
   contract? Quote the line that proves it, or the absence that disproves it.
2. If a check above FAILED, read its real output and find the cause in the code. A
   failing check outranks your own impression of the code: do not approve work that
   the engine has measured as broken. If instead the check itself is malformed, say
   so as a finding against the check.
3. Correctness: logic errors, wrong assumptions, unhandled real cases. Ignore
   hypothetical cases that cannot occur.
4. Completeness: stubs, placeholders, dead code, half-finished edits, broken imports.
5. Constraint breaches: credentials touched, writes outside owned files, sends,
   deploys, anything the brief forbids.
6. Only then, style — and only where it affects correctness or readability.

Reply with ONLY a JSON object:
{{"verdict": "APPROVE" or "REVISE",
  "findings": [{{"severity": "critical|high|medium|low",
                 "location": "file:line",
                 "problem": "what is wrong",
                 "fix": "the concrete change"}}]}}

Approve only if nothing critical or high remains. Do not invent findings to look
thorough: an empty findings list with APPROVE is a valid and useful answer."""

FIX_PROMPT = """You built this part. An independent reviewer found defects. Fix them.

{brief}

## Your part
- id: {part_id}
- contract: {contract}
- files you own: {owns}
- workdir: {workdir}

## Findings you must fix
```json
{findings}
```

## Instructions
Fix every finding listed. Do not redesign beyond them, and do not argue with the
reviewer. If a finding is factually wrong, fix what is real and state plainly why
the remainder does not apply, quoting the file:line that shows it.

Finish by listing each file you changed, with its byte size."""


def _deliverable_lines(items) -> str:
    if not items:
        return "- (none declared for this part)"
    out = []
    for d in items:
        if isinstance(d, dict):
            out.append(f"- `{d.get('path')}` (min {d.get('min_bytes', 1)} bytes)")
        else:
            out.append(f"- `{d}`")
    return "\n".join(out)


def _dump_files(items, limit_per_file: int = 4000, max_total: int = 16000) -> str:
    chunks, total = [], 0
    for d in items or []:
        path = Path(d.get("path") if isinstance(d, dict) else str(d))
        if not path.exists():
            chunks.append(f"### {path}\n(MISSING — this file does not exist)\n")
            continue
        try:
            body = path.read_text(errors="replace")
        except OSError as exc:
            chunks.append(f"### {path}\n(unreadable: {exc})\n")
            continue
        shown = util.clip(body, limit_per_file)
        chunk = f"### {path} ({path.stat().st_size} bytes)\n```\n{shown}\n```\n"
        if total + len(chunk) > max_total:
            chunks.append(f"### {path}\n({path.stat().st_size} bytes, not shown: "
                          f"review budget exhausted)\n")
            continue
        total += len(chunk)
        chunks.append(chunk)
    return "\n".join(chunks) or "(no files declared)"


def _part_deliverables(part: dict) -> list:
    return part.get("deliverables") or []


_PY_ALWAYS_BOUND = frozenset(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__builtins__", "__spec__", "__package__",
}

# Bindings a payload could create that static analysis cannot see.
_PY_DYNAMIC_CALLS = {"exec", "eval"}
_PY_DYNAMIC_NAMES = {"globals", "locals", "vars"}


def unbound_names(payload: str) -> list[str]:
    """Names a python -c payload reads but never binds, in order of first use.

    `python3 -c 'for i in x: pass'` compiles cleanly and still cannot run: x does not
    exist. Treating that as a failing check condemns correct work and sends the repair
    loop chasing a phantom (the same class of bug as the semicolon SyntaxError below),
    so a payload that reads an undefined name is discarded as unrunnable.
    """
    try:
        tree = ast.parse(payload)
    except (SyntaxError, ValueError):
        return []                      # the compile check reports that better

    bound: set[str] = set()
    dynamic = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    dynamic = True
                else:
                    bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _PY_DYNAMIC_CALLS:
                dynamic = True
        elif isinstance(node, ast.Name):
            if node.id in _PY_DYNAMIC_NAMES:
                dynamic = True

    if dynamic:
        return []

    free: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in bound and node.id not in _PY_ALWAYS_BOUND and node.id not in free:
                free.append(node.id)
    return free


def validate_verify_cmd(cmd: str) -> tuple[bool, str]:
    """Check that a planner-proposed check can actually run before it gates anything.

    A model will happily write `python3 -c 'import x; for i in y: ...'`, which is a
    SyntaxError: compound statements cannot be separated by semicolons. On the first
    hard benchmark that made a fully correct solution look like a failure, and the
    repair loop then chased a phantom. A check that cannot parse is not a check.
    """
    if not cmd or not cmd.strip():
        return False, "empty command"

    for match in re.finditer(r"""python3?\s+-c\s+(['"])(.*?)\1""", cmd, re.S):
        payload = match.group(2)
        try:
            compile(payload, "<verify_cmd>", "exec")
        except SyntaxError as exc:
            return False, f"python payload does not compile: {exc.msg} (line {exc.lineno})"
        free = unbound_names(payload)
        if free:
            return False, ("python payload cannot run: it reads "
                           + ", ".join(free[:4]) + " but nothing in it defines that")

    try:
        proc = subprocess.run(["bash", "-n", "-c", cmd], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not syntax-check: {exc}"
    if proc.returncode != 0:
        return False, f"shell syntax error: {proc.stderr.strip()[:200]}"
    return True, "ok"


def _verify_part(part: dict, ledger, workdir: Path, stage: str) -> tuple[bool, list, list]:
    """Engine-run verification of one part: deliverables first, then verify_cmd."""
    declared = [{"path": d.get("path"), "min_bytes": int(d.get("min_bytes", 1))}
                for d in _part_deliverables(part) if isinstance(d, dict) and d.get("path")]
    ok_files, receipts = (True, [])
    if declared:
        ok_files, receipts = ledger.check_receipts(declared)
        for rec in receipts:
            ledger.event("gate", stage=stage, check=f"deliverable:{rec.path}",
                         passed=rec.ok, exit_code=0 if rec.ok else 1, bytes=rec.bytes,
                         reason=("ok" if rec.ok else
                                 ("missing" if not rec.exists else "too small")))
    checks = []
    cmd = part.get("verify_cmd")
    ok_cmd = True
    if cmd:
        usable, why = validate_verify_cmd(cmd)
        if not usable:
            # The part is still judged, by its deliverables and by the task's own
            # acceptance checks. A broken check must not condemn working code.
            ledger.event("warning", stage=stage,
                         message="planner verify_cmd discarded: it cannot run",
                         part=part.get("id"), reason=why, cmd=str(cmd)[:400])
        else:
            check = Acceptance(cmd=cmd, name=f"verify:{part.get('id')}", timeout_sec=600)
            ok_cmd, checks = gate_mod.run_all([check], workdir, ledger, stage)
    return (ok_files and ok_cmd), receipts, checks


def run_build(spec: TaskSpec, plan: dict, lane_pool: list, health: dict, ledger,
              pack: str, max_parallel: int, timeout_sec: int) -> list:
    """Dispatch all parts in parallel. Hard parts get K independent attempts."""
    brief = to_brief(spec)
    clipped = util.clip(pack, CONTEXT_BUDGET)
    profile = spec.profile
    parts = plan.get("parts", [])

    jobs = []
    for part in parts:
        pid = util.slugify(part.get("id") or part.get("title") or "part")
        k = profile["sample_k"] if str(part.get("difficulty", "")).lower() == "high" else 1
        builders = lanes_mod.pick(lane_pool, health, "build", count=max(1, k),
                       needs_web=spec.web)
        if not builders:
            raise RuntimeError("no live lane available for build")
        for attempt, lane in enumerate(builders, start=1):
            workdir = ledger.dir / "parts" / pid / f"a{attempt}-{lane.id}"
            prompt = BUILD_PROMPT.format(
                brief=brief, pack=clipped, part_id=pid,
                title=part.get("title", ""), contract=part.get("contract", ""),
                owns=", ".join(part.get("owns_files", []) or []) or "(none declared)",
                notes=part.get("notes", "") or "(none)",
                deliverables=_deliverable_lines(_part_deliverables(part)),
                workdir=workdir,
            )
            jobs.append(dict(part=part, pid=pid, lane=lane, attempt=attempt,
                             workdir=workdir, prompt=prompt))

    def one(job):
        res = lanes_mod.invoke(job["lane"], job["prompt"], job["workdir"],
                               timeout_sec, title=f"build-{job['pid']}", mode="rw", web=spec.web)
        ledger.record_lane_call("build", f"{job['pid']}.a{job['attempt']}",
                                job["prompt"], res)
        return {**job, "result": res}

    with ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
        done = list(pool.map(one, jobs))

    # Group attempts per part, verify each, pick a winner.
    by_part: dict[str, list] = {}
    for item in done:
        by_part.setdefault(item["pid"], []).append(item)

    outcomes = []
    for pid, attempts in by_part.items():
        part = attempts[0]["part"]
        scored = []
        for att in attempts:
            ok, receipts, checks = _verify_part(
                part, ledger, att["workdir"], f"build.{pid}.a{att['attempt']}")
            blocked = att["result"].text.strip().upper().startswith("BLOCKED")
            scored.append({**att, "verified": ok, "receipts": receipts,
                           "checks": checks, "blocked": blocked})

        passing = [s for s in scored if s["verified"] and not s["blocked"]]
        if len(passing) > 1:
            winner = _judge(part, passing, lane_pool, health, ledger, timeout_sec)
        elif passing:
            winner = passing[0]
        else:
            winner = max(scored, key=lambda s: len(s["result"].text or ""))

        outcomes.append({
            "part_id": pid, "part": part,
            "winner_lane": winner["lane"].id, "winner_model": winner["lane"].model,
            "winner_family": winner["lane"].family,
            "workdir": str(winner["workdir"]),
            "verified": bool(winner.get("verified")),
            "blocked": bool(winner.get("blocked")),
            "verdict": winner["result"].verdict,
            "elapsed_sec": winner["result"].elapsed_sec,
            "builder_report": util.clip(winner["result"].text or "", 5000),
            "attempts": len(scored),
            "attempts_passing": len(passing),
        })

    ledger.stage_done("build", parts=len(outcomes),
                      verified=sum(1 for o in outcomes if o["verified"]),
                      lane_calls=len(done))
    util.write_json(ledger.dir / "BUILD.json", outcomes)
    return outcomes


def _judge(part: dict, passing: list, lane_pool: list, health: dict,
           ledger, timeout_sec: int):
    """Pick between verified attempts with a lane from an unused family."""
    used = {p["lane"].family for p in passing}
    judges = lanes_mod.pick(lane_pool, health, "review", count=1, exclude_families=used)
    if not judges:
        judges = lanes_mod.pick(lane_pool, health, "review", count=1)
    if not judges:
        return passing[0]

    cand_text = []
    for p in passing:
        cand_text.append(
            f"### candidate {p['lane'].id}\nworkdir: {p['workdir']}\n"
            f"report:\n{util.clip(p['result'].text or '', 2500)}\n"
            f"files:\n{_dump_files(_part_deliverables(part), 1800, 6000)}\n")

    prompt = JUDGE_PROMPT.format(
        contract=part.get("contract", ""),
        deliverables=_deliverable_lines(_part_deliverables(part)),
        candidates="\n".join(cand_text)[:20000])
    res = lanes_mod.invoke(judges[0], prompt, ledger.dir / "review",
                           timeout_sec, title=f"judge-{part.get('id')}", mode="ro")
    ledger.record_lane_call("judge", util.slugify(part.get("id", "part")), prompt, res)
    verdict = _parse_json_reply(res.text) or {}
    winner_id = verdict.get("winner")
    for p in passing:
        if p["lane"].id == winner_id:
            return p
    return passing[0]


def _gate_results(ledger, part_id: str) -> str:
    """The engine's measured results for this part, so review is not blind to them."""
    lines = []
    for event in ledger.events("gate"):
        stage = str(event.get("stage", ""))
        if part_id not in stage:
            continue
        verdict = "PASS" if event.get("passed") else "FAIL"
        lines.append(f"- {verdict} {event.get('check')}: {event.get('reason', '')}")
        if not event.get("passed"):
            slug = util.slugify(str(event.get("check", "")))
            transcript = ledger.dir / "gates" / f"{stage}.{slug}.txt"
            if transcript.exists():
                body = transcript.read_text(errors="replace")
                lines.append("```\n" + util.clip(body, 2200) + "\n```")
    for event in ledger.events("warning"):
        if str(event.get("part", "")) == part_id:
            lines.append(f"- NOTE: {event.get('message')} ({event.get('reason', '')})")
    return "\n".join(lines)[:9000] or "(the engine ran no checks on this part)"


def run_review(spec: TaskSpec, outcomes: list, lane_pool: list, health: dict,
               ledger, timeout_sec: int, max_parallel: int) -> list:
    """Independent review of every part, on a different family than its builder."""
    brief = to_brief(spec)

    def one(outcome):
        part = outcome["part"]
        reviewers = lanes_mod.pick(lane_pool, health, "review", count=1,
                                   exclude_families={outcome["winner_family"]})
        if not reviewers:
            reviewers = lanes_mod.pick(lane_pool, health, "review", count=1,
                                       exclude_lanes={outcome["winner_lane"]})
        if not reviewers:
            return {**outcome, "review": {"verdict": "SKIPPED",
                                          "findings": [],
                                          "reason": "no independent lane available"}}
        prompt = REVIEW_PROMPT.format(
            brief=brief, part_id=outcome["part_id"],
            contract=part.get("contract", ""),
            deliverables=_deliverable_lines(_part_deliverables(part)),
            builder_report=util.clip(outcome["builder_report"], 4000),
            gate_results=_gate_results(ledger, outcome["part_id"]),
            file_dump=_dump_files(_part_deliverables(part)))
        res = lanes_mod.invoke(reviewers[0], prompt, ledger.dir / "review",
                               timeout_sec, title=f"review-{outcome['part_id']}",
                               mode="ro", web=spec.web)
        ledger.record_lane_call("review", outcome["part_id"], prompt, res)
        review = _parse_json_reply(res.text) or {
            "verdict": "UNPARSED", "findings": [],
            "reason": f"reviewer returned no JSON ({res.verdict})"}
        review["lane"] = reviewers[0].id
        review["family"] = reviewers[0].family
        return {**outcome, "review": review}

    with ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
        reviewed = list(pool.map(one, outcomes))

    util.write_json(ledger.dir / "REVIEW.json",
                    [{k: v for k, v in r.items() if k != "part"} for r in reviewed])
    serious = sum(1 for r in reviewed
                  for f in r["review"].get("findings", [])
                  if str(f.get("severity", "")).lower() in ("critical", "high"))
    ledger.stage_done("review", parts=len(reviewed), serious_findings=serious)
    return reviewed


def run_fix(spec: TaskSpec, reviewed: list, lane_pool: list, health: dict, ledger,
            timeout_sec: int, max_parallel: int, round_no: int) -> list:
    """Send critical and high findings back to the lane that built the part."""
    brief = to_brief(spec)
    lane_by_id = {ln.id: ln for ln in lane_pool}

    needs_fix = []
    for item in reviewed:
        serious = [f for f in item["review"].get("findings", [])
                   if str(f.get("severity", "")).lower() in ("critical", "high")]
        if serious or not item["verified"]:
            needs_fix.append((item, serious))

    if not needs_fix:
        return reviewed

    def one(entry):
        item, serious = entry
        lane = lane_by_id.get(item["winner_lane"])
        if not lane or lane.id not in set(health.get("live", [])):
            alt = lanes_mod.pick(lane_pool, health, "fix", count=1, needs_web=spec.web)
            lane = alt[0] if alt else None
        if not lane:
            return item
        part = item["part"]
        prompt = FIX_PROMPT.format(
            brief=brief, part_id=item["part_id"],
            contract=part.get("contract", ""),
            owns=", ".join(part.get("owns_files", []) or []) or "(none declared)",
            workdir=item["workdir"],
            findings=json.dumps(serious, indent=2)[:6000] or
                     '[{"severity":"high","problem":"required output missing or failed '
                     'verification","fix":"produce the declared deliverable and make '
                     'verify_cmd pass"}]')
        res = lanes_mod.invoke(lane, prompt, Path(item["workdir"]), timeout_sec,
                               title=f"fix{round_no}-{item['part_id']}", mode="rw", web=spec.web)
        ledger.record_lane_call(f"fix{round_no}", item["part_id"], prompt, res)
        ok, receipts, checks = _verify_part(part, ledger, Path(item["workdir"]),
                                            f"fix{round_no}.{item['part_id']}")
        return {**item, "verified": ok,
                "fix_rounds": item.get("fix_rounds", 0) + 1,
                "fix_report": util.clip(res.text or "", 3000)}

    with ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
        fixed = list(pool.map(one, needs_fix))

    by_id = {f["part_id"]: f for f in fixed}
    merged = [by_id.get(item["part_id"], item) for item in reviewed]
    ledger.stage_done(f"fix{round_no}", attempted=len(needs_fix),
                      verified_after=sum(1 for m in merged if m["verified"]))
    return merged


REPAIR_PROMPT = """The work is built, but the engine's final checks failed. Fix it.

{brief}

## The deliverables as they exist now
{file_dump}

## The checks that FAILED, run by the engine itself, with their real output
{failures}

## Instructions
1. Read the failing output carefully and find the real cause. Decide whether the code
   or the test is wrong by checking both against the task's goal and constraints.
2. Fix the cause. Do not weaken a check to make it pass: never delete a test, never
   loosen an assertion, never remove required behaviour. If a test asserts something
   the goal does not require, fix the test to assert the correct behaviour instead.
3. Do not edit the acceptance commands; you cannot change them anyway.
4. Run the failing command yourself before you finish and show that it now passes.

Finish by listing each file you changed, with its byte size, and one sentence on the
root cause."""

SHRINK_LIMIT = 0.6   # a repair that cuts a deliverable below 60% of its size is suspect


def run_repair(spec: TaskSpec, failed_checks: list, reviewed: list, lane_pool: list,
               health: dict, ledger, timeout_sec: int, round_no: int) -> dict:
    """One targeted repair round driven by real gate output, then the caller re-verifies."""
    owners = [r for r in reviewed if r.get("winner_lane")]
    preferred = {r["winner_lane"] for r in owners}
    builders = [ln for ln in lane_pool
                if ln.id in preferred and ln.id in set(health.get("live", []))
                and not lanes_mod.is_cooling(ln.id)]
    if not builders:
        builders = lanes_mod.pick(lane_pool, health, "fix", count=1,
                             needs_web=spec.web)
    if not builders:
        return {"attempted": False, "reason": "no live lane for repair"}
    lane = builders[0]

    before = {}
    for d in spec.deliverables:
        p = Path(d.path)
        before[d.path] = p.stat().st_size if p.exists() else 0

    failures = []
    for c in failed_checks:
        failures.append(
            f"### {c.name}\n```\n$ {c.cmd}\nexit={c.exit_code}  ({c.reason})\n"
            f"--- stdout (tail) ---\n{util.clip(c.stdout_tail or '', 2500)}\n"
            f"--- stderr (tail) ---\n{util.clip(c.stderr_tail or '', 2500)}\n```")
    prompt = REPAIR_PROMPT.format(
        brief=to_brief(spec),
        file_dump=_dump_files([{"path": d.path} for d in spec.deliverables],
                              limit_per_file=6000, max_total=22000),
        failures="\n\n".join(failures)[:14000])
    workdir = ledger.dir / "parts" / f"_repair{round_no}"
    res = lanes_mod.invoke(lane, prompt, workdir, timeout_sec,
                           title=f"repair{round_no}-{spec.id}", mode="rw", web=spec.web)
    ledger.record_lane_call(f"repair{round_no}", spec.id, prompt, res)

    shrunk = []
    for path, old in before.items():
        p = Path(path)
        new = p.stat().st_size if p.exists() else 0
        if old and new < old * SHRINK_LIMIT:
            shrunk.append(f"{path}: {old}B -> {new}B")
    ledger.stage_done(f"repair{round_no}", lane=lane.id, verdict=res.verdict,
                      failed_checks=[c.name for c in failed_checks], shrunk=shrunk)
    return {"attempted": True, "lane": lane.id, "verdict": res.verdict,
            "shrunk": shrunk, "report": util.clip(res.text or "", 3000)}


INTEGRATE_PROMPT = """You are the integrator. One lane, one delivery folder.

{brief}

## Parts that were built and reviewed
{parts}

## Your job
Assemble the final delivery in: {delivery}

1. Bring each part's verified output together into a coherent whole.
2. Resolve mismatches between parts (naming, imports, duplicated logic, conflicting
   assumptions). Mismatches between independently built parts are expected — finding
   and fixing them is the point of this stage.
3. Produce every required deliverable of the overall task at its exact path.
4. Do not silently drop a part. If a part is unusable, say which and why.

## Required final deliverables
{deliverables}

Finish by listing every file in the delivery folder with its byte size."""


def run_integrate(spec: TaskSpec, reviewed: list, lane_pool: list, health: dict,
                  ledger, timeout_sec: int) -> dict:
    """Single integrator writes the delivery folder. Never a parallel stage."""
    if len(reviewed) == 1 and not spec.raw.get("force_integrate"):
        ledger.stage_done("integrate", skipped="single part, nothing to integrate")
        return {"skipped": True, "reason": "single part"}

    delivery = ledger.dir / "delivery"
    integrators = lanes_mod.pick(lane_pool, health, "integrate", count=1)
    if not integrators:
        integrators = lanes_mod.pick(lane_pool, health, "build", count=1)
    if not integrators:
        raise RuntimeError("no live lane available for integration")

    part_text = "\n".join(
        f"### {r['part_id']} (built by {r['winner_lane']}, verified={r['verified']})\n"
        f"workdir: {r['workdir']}\n"
        f"contract: {r['part'].get('contract', '')}\n"
        f"outputs: {_deliverable_lines(_part_deliverables(r['part']))}\n"
        for r in reviewed)

    prompt = INTEGRATE_PROMPT.format(
        brief=to_brief(spec), parts=util.clip(part_text, 9000),
        delivery=delivery,
        deliverables=_deliverable_lines(
            [{"path": d.path, "min_bytes": d.min_bytes} for d in spec.deliverables]))
    res = lanes_mod.invoke(integrators[0], prompt, delivery, timeout_sec,
                           title="integrate", mode="rw", web=spec.web)
    ledger.record_lane_call("integrate", "final", prompt, res)
    ledger.stage_done("integrate", lane=integrators[0].id, verdict=res.verdict)
    return {"skipped": False, "lane": integrators[0].id, "verdict": res.verdict,
            "report": util.clip(res.text or "", 4000)}
