"""Final report and the board record.

The report is written from the ledger, not from what any lane said about itself.
Every number in it is traceable to a recorded exit code or a file size.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import util


def write_report(spec, outcome, ledger, run_dir: Path) -> Path:
    s = ledger.summary()
    data = outcome.data
    health = data.get("health", {})
    reviewed = data.get("reviewed", [])
    plan = data.get("plan", {})

    lines = [
        f"# Run report — {spec.title}",
        "",
        f"- Result: **{outcome.result_line}**",
        f"- Spec id: `{spec.id}`  depth: {spec.depth} "
        f"({', '.join(f'{k}={v}' for k, v in spec.profile.items())})",
        f"- Run dir: `{run_dir}`",
        f"- Finished: {util.ist_now()} ({util.utc_now()})",
        "",
        "## Goal",
        spec.goal,
        "",
        "## Lanes",
        f"- Live at dispatch ({len(health.get('live', []))}): "
        f"{', '.join(health.get('live', [])) or 'none'}",
    ]
    dead = health.get("dead", {})
    if dead:
        lines.append("- Excluded by the health probe: "
                     + ", ".join(f"{k} ({v})" for k, v in dead.items()))
    lines += [
        "",
        "## Work done",
        f"- Lane calls: {s['lane_calls']}, total lane time {s['lane_seconds']}s",
        f"- Total cost reported by providers across every call: **{s['total_cost']}** "
        f"(free-only rule; any non-zero value trips the cost breaker and fails the run)",
        f"- Lane verdicts: {json.dumps(s['verdicts'])}",
        f"- Gates run: {s['gates_run']}, passed: {s['gates_passed']}",
        f"- Stages completed: {', '.join(s['stages_done'])}",
        "",
    ]

    if plan.get("summary"):
        lines += ["## Plan", str(plan["summary"]), ""]
        if plan.get("revised_after_redteam"):
            lines.append(f"The red team forced a revision; "
                         f"{plan.get('addressed_findings', 0)} serious findings were "
                         f"fixed before any build started.\n")
        if plan.get("file_conflicts"):
            lines.append("File ownership conflicts detected: "
                         + "; ".join(plan["file_conflicts"]) + "\n")

    if reviewed:
        lines += ["## Parts", "",
                  "| part | built by | family | verified | reviewer | verdict | serious findings |",
                  "|---|---|---|---|---|---|---|"]
        for r in reviewed:
            rev = r.get("review", {}) or {}
            serious = sum(1 for f in rev.get("findings", [])
                          if str(f.get("severity", "")).lower() in ("critical", "high"))
            lines.append(
                f"| {r['part_id']} | {r['winner_lane']} | {r.get('winner_family', '-')} "
                f"| {'yes' if r['verified'] else 'NO'} | {rev.get('lane', '-')} "
                f"| {rev.get('verdict', '-')} | {serious} |")
        lines.append("")

    receipts = data.get("receipts", [])
    if receipts:
        lines += ["## Deliverables", "", "| path | bytes | min | ok |", "|---|---|---|---|"]
        for rec in receipts:
            lines.append(f"| `{rec['path']}` | {rec['bytes']} | {rec['min_bytes']} "
                         f"| {'yes' if rec['exists'] and rec['bytes'] >= rec['min_bytes'] else 'NO'} |")
        lines.append("")

    checks = data.get("checks", [])
    if checks:
        lines += ["## Acceptance checks (run by the engine)", ""]
        for c in checks:
            lines += [f"### {c['name']} — {'PASS' if c['passed'] else 'FAIL'}",
                      f"```\n$ {c['cmd']}\nexit={c['exit_code']}  {c['reason']}\n```"]
            if c.get("stdout_tail"):
                lines.append(f"```\n{util.clip(c['stdout_tail'], 1200)}\n```")
        lines.append("")

    integ = data.get("integration", {})
    if integ and not integ.get("skipped"):
        lines += ["## Integration",
                  f"Integrator lane: {integ.get('lane')} ({integ.get('verdict')})", ""]

    trip = data.get("tripwire") or {}
    lines += ["## Protected-path tripwire",
              f"- Strict roots changed during the run: "
              f"{len(trip.get('strict', []))} (any change fails the run)"]
    if trip.get("strict"):
        lines += [f"  - `{p}`" for p in trip["strict"][:20]]
    lines.append(f"- Banned paths changed during the run: {len(trip.get('banned', []))} "
                 f"(reported for review; scheduled jobs can also write there)")
    if trip.get("banned"):
        lines += [f"  - `{p}`" for p in trip["banned"][:20]]
    cred = data.get("credential_access") or {}
    lines += [f"- Credential-path reads completed: {len(cred.get('completed', []))} "
              f"(any completion fails the run); denied attempts: "
              f"{len(cred.get('denied', []))} (the permission layer held)"]
    lines.append("")

    findings = []
    for r in reviewed:
        for f in (r.get("review", {}) or {}).get("findings", []):
            if str(f.get("severity", "")).lower() in ("critical", "high"):
                findings.append((r["part_id"], f))
    if findings:
        lines += ["## Serious review findings", ""]
        for pid, f in findings:
            lines.append(f"- [{f.get('severity')}] {pid} {f.get('location', '')}: "
                         f"{f.get('problem')} → {f.get('fix')}")
        lines.append("")

    lines += ["## Audit trail",
              f"- Full ledger: `{ledger.path}` ({len(ledger.events())} events)",
              f"- Every prompt and reply: `{run_dir}/lanes/`",
              f"- Gate transcripts: `{run_dir}/gates/`",
              f"- Context pack: `{run_dir}/context/CONTEXT_PACK.md`",
              ""]

    path = run_dir / "RUN_REPORT.md"
    util.write_text(path, "\n".join(lines))
    return path


def post_to_board(issue_id: str, body: str) -> tuple[bool, str]:
    """Comment on a Paperclip issue as the board operator."""
    if not issue_id:
        return False, "no issue id"
    quoted = body.replace("'", "'\\''")
    cmd = f"paperclipai issue comment {issue_id} --body '{quoted}' --json"
    try:
        proc = subprocess.run(["bash", "-lc", cmd], capture_output=True,
                              text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "paperclipai timed out"
    if proc.returncode != 0:
        return False, util.redact(proc.stderr[-400:])
    try:
        return True, json.loads(proc.stdout).get("id", "")
    except ValueError:
        return True, "posted"


def board_summary(spec, outcome, ledger, report_path: Path) -> str:
    s = ledger.summary()
    data = outcome.data
    receipts = data.get("receipts", [])
    ok_files = sum(1 for r in receipts if r["exists"] and r["bytes"] >= r["min_bytes"])
    reviewed = data.get("reviewed", [])
    return (
        f"{outcome.result_line} | engine run for '{spec.title}' (depth {spec.depth}). "
        f"Report: {report_path} . "
        f"Lanes live at dispatch: {', '.join(data.get('health', {}).get('live', [])) or 'none'}. "
        f"Parts: {len(reviewed)}, verified {sum(1 for r in reviewed if r['verified'])}. "
        f"Deliverables present and non-trivial: {ok_files}/{len(receipts)}. "
        f"Acceptance checks passed: {s['gates_passed']}/{s['gates_run']}. "
        f"Lane calls: {s['lane_calls']} totalling {s['lane_seconds']}s, "
        f"total provider-reported cost {s['total_cost']}. "
        f"Every prompt, reply, exit code and gate transcript is on disk under "
        f"{ledger.dir} — this summary is generated from that ledger, not from any "
        f"lane's self-report."
    )
