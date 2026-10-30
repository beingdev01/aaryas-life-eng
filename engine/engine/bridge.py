"""Paperclip bridge: a Paperclip agent seat runs the engine with its department kit.

Paperclip's process adapter starts this on every wake. One run of the bridge:

1. works out which agent it is and which department kit that agent sits in;
2. finds the issue to work: the wake's task id, else the highest-priority todo or
   in-progress issue in the agent's inbox; a timer wake with nothing to do exits in
   seconds instead of spinning up a model;
3. refuses to repeat work: an issue already finished by the bridge is skipped unless
   someone has touched it since (a new comment, a status change);
4. claims the issue atomically with checkout, so two runs can never work it at once
   (the old runners never checked out, and duplicated work);
5. posts a first receipt immediately, then drafts a spec from the issue with the
   department kit, runs the engine, and posts the ledger-generated summary with the
   report attached;
6. closes the issue as done only when the engine's own gates passed; otherwise parks
   it as blocked with a concrete unblock action, which is the only form of "blocked"
   Paperclip accepts from an agent (the old runner's escalation failed with a 422).

The model lanes never see the agent's Paperclip key: it stays in this process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import departments as dept_mod
from . import draft as draft_mod
from . import guard, lanes as lanes_mod, orchestrator, report as report_mod
from . import spec as spec_mod
from . import util
from .ledger import Ledger

API = os.environ.get("PAPERCLIP_API_URL", "http://127.0.0.1:3100").rstrip("/")
STATE_DIR = Path(os.environ.get("ENG_BRIDGE_STATE", str(util.HOME / "state" / "bridge")))
WORKABLE = ("todo", "in_progress")
CHECKOUT_FROM = "todo,backlog,blocked,in_progress,in_review"
PRIORITY_ORDER = {"critical": 0, "urgent": 0, "high": 1, "medium": 2, "low": 3}


def log(msg: str) -> None:
    print(f"[bridge {util.utc_now()}] {msg}", flush=True)


class Paperclip:
    """Minimal client. Agent identity when run by Paperclip, board identity by hand."""

    def __init__(self):
        self.key = os.environ.get("PAPERCLIP_API_KEY", "")
        self.run_id = os.environ.get("PAPERCLIP_RUN_ID", "")
        self.agent_id = os.environ.get("PAPERCLIP_AGENT_ID", "")
        self.company = os.environ.get("PAPERCLIP_COMPANY_ID", util.COMPANY_ID)

    @property
    def mode(self) -> str:
        return "agent" if self.key else "board"

    def _req(self, method: str, path: str, body: dict | None = None,
             timeout: int = 60) -> tuple[int, dict | list | str]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{API}/api{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.key:
            req.add_header("Authorization", f"Bearer {self.key}")
        if self.run_id:
            req.add_header("X-Paperclip-Run-Id", self.run_id)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode(errors="replace")
                code = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            code = exc.code
        except (urllib.error.URLError, TimeoutError) as exc:
            return 0, str(exc)
        try:
            return code, json.loads(raw) if raw else {}
        except ValueError:
            return code, raw[:400]

    def issue(self, issue_id: str) -> dict | None:
        code, body = self._req("GET", f"/issues/{issue_id}")
        return body if code == 200 and isinstance(body, dict) else None

    def inbox(self) -> list:
        if self.mode != "agent":
            return []
        env = dict(os.environ)
        proc = subprocess.run(["bash", "-lc", "paperclipai agent inbox --json"],
                              capture_output=True, text=True, timeout=90, env=env)
        if proc.returncode != 0:
            log(f"inbox fetch failed: {util.redact(proc.stderr[-200:])}")
            return []
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            return []
        items = data if isinstance(data, list) else data.get("items", data.get("issues", []))
        return [i for i in items if isinstance(i, dict)]

    def checkout(self, issue_id: str) -> tuple[bool, str]:
        if self.mode != "agent":
            return True, "board mode: no checkout"
        code, body = self._req("POST", f"/issues/{issue_id}/checkout",
                               {"agentId": self.agent_id,
                                "expectedStatuses": CHECKOUT_FROM.split(",")})
        if 200 <= code < 300:
            return True, "checked out"
        return False, f"HTTP {code}: {str(body)[:200]}"

    def comment(self, issue_id: str, text: str) -> tuple[bool, str]:
        code, body = self._req("POST", f"/issues/{issue_id}/comments",
                               {"body": util.redact(text)})
        if 200 <= code < 300:
            return True, (body.get("id", "") if isinstance(body, dict) else "")
        time.sleep(3)
        code, body = self._req("POST", f"/issues/{issue_id}/comments",
                               {"body": util.redact(text)})
        return 200 <= code < 300, f"HTTP {code}: {str(body)[:200]}"

    def set_status(self, issue_id: str, status: str) -> tuple[bool, str]:
        code, body = self._req("PATCH", f"/issues/{issue_id}", {"status": status})
        return 200 <= code < 300, f"HTTP {code}: {str(body)[:200]}"

    def park(self, issue_id: str, action: str) -> tuple[bool, str]:
        """Blocked with an unblock descriptor naming this agent, the accepted form."""
        payload = {"status": "blocked",
                   "unblockDescriptor": {"owner": {"agentId": self.agent_id},
                                         "action": action[:1900]}}
        if self.mode != "agent":
            payload["unblockDescriptor"] = {"owner": "board", "action": action[:1900]}
        code, body = self._req("PATCH", f"/issues/{issue_id}", payload)
        if 200 <= code < 300:
            return True, "parked"
        return False, f"HTTP {code}: {str(body)[:240]}"

    def attach(self, issue_id: str, path: Path) -> tuple[bool, str]:
        cmd = (f"paperclipai issue attachment:upload {issue_id} -C {self.company} "
               f"--file '{path}' --json")
        proc = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True,
                              timeout=120, env=dict(os.environ))
        if proc.returncode == 0:
            return True, "attached"
        return False, util.redact(proc.stderr[-200:])


# ------------------------------------------------------------------ loop guard

def _state_path(issue_id: str) -> Path:
    return STATE_DIR / f"{issue_id}.json"


def already_handled(issue: dict) -> bool:
    state = util.read_json(_state_path(issue["id"]))
    if not state:
        return False
    return state.get("updated_at") == issue.get("updatedAt")


def remember(issue_id: str, outcome: str, updated_at: str | None, run_dir: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    util.write_json(_state_path(issue_id), {"outcome": outcome, "updated_at": updated_at,
                                            "run_dir": run_dir, "at": util.utc_now()})


# ---------------------------------------------------------------- resolution

def resolve_agent(pc: Paperclip) -> str:
    name = os.environ.get("ENG_AGENT_NAME", "")
    if name:
        return name
    if pc.agent_id:
        code, body = pc._req("GET", f"/agents/{pc.agent_id}")
        if code == 200 and isinstance(body, dict):
            return str(body.get("name") or "")
    return ""


def pick_issue(pc: Paperclip, forced: str | None) -> dict | None:
    task_id = forced or os.environ.get("PAPERCLIP_TASK_ID", "")
    if task_id:
        issue = pc.issue(task_id)
        if issue and issue.get("status") not in ("done", "cancelled"):
            return issue
        log(f"task {task_id} is not workable ({issue.get('status') if issue else 'missing'})")
        return None
    items = [i for i in pc.inbox() if i.get("status") in WORKABLE]
    items.sort(key=lambda i: (PRIORITY_ORDER.get(str(i.get("priority", "medium")), 2),
                              i.get("updatedAt", "")))
    for item in items:
        full = pc.issue(item["id"]) or item
        if not already_handled(full):
            return full
    return None


# ----------------------------------------------------------------------- main

def run(forced_issue: str | None = None, dry: bool = False) -> int:
    pc = Paperclip()
    wake = os.environ.get("PAPERCLIP_WAKE_REASON", "manual")
    agent_name = resolve_agent(pc)
    log(f"wake={wake} mode={pc.mode} agent={agent_name or '?'} run={pc.run_id or '-'}")

    profile = None
    dept_name = os.environ.get("ENG_DEPT", "")
    try:
        profile = (dept_mod.find(dept_name) if dept_name
                   else dept_mod.for_agent(agent_name) if agent_name else None)
    except (dept_mod.ProfileError, OSError) as exc:
        log(f"department kit could not load: {exc}")
    if profile is None:
        log("no department kit for this agent; refusing to run without one")
        return 2
    depth = int(os.environ.get("ENG_DEPTH") or profile.agent_depth(agent_name))

    issue = pick_issue(pc, forced_issue)
    if not issue:
        log("nothing to do")
        return 0
    iid, ident = issue["id"], issue.get("identifier", issue["id"])
    if already_handled(issue) and not forced_issue:
        log(f"{ident} already handled and unchanged since; skipping")
        return 0

    ok, why = pc.checkout(iid)
    if not ok:
        log(f"{ident}: checkout refused ({why}); another run owns it")
        return 0

    stamp = util.utc_now().replace(":", "").replace("-", "")
    run_id = f"{util.slugify(ident)}-{stamp}"
    run_dir = util.RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    pc.comment(iid, (
        f"Picked up by {agent_name} ({profile.name} department, engine depth {depth}). "
        f"Engine run {run_id} is starting on free model lanes only. Working files: "
        f"{run_dir} . Next receipt: the drafted task spec, then the run report."))
    if dry:
        log("dry run: stopping after first receipt")
        return 0

    pool, defaults = lanes_mod.load_lanes()
    try:
        guard.enforce(pool)
    except guard.PaidModelRefused as exc:
        pc.comment(iid, f"RESULT: BLOCKED - {exc}")
        pc.park(iid, f"Free-lane guard refused to start: {exc}")
        remember(iid, "BLOCKED", (pc.issue(iid) or {}).get("updatedAt"), str(run_dir))
        return 0

    request = (f"Board issue {ident}: {issue.get('title', '')}\n\n"
               f"{issue.get('description') or ''}")
    drafting = [ln for ln in pool if ln.enabled and (ln.supports("plan") or
                                                      ln.supports("redteam"))]
    health = lanes_mod.probe(drafting, int(defaults.get("probe_timeout_sec", 90)),
                             int(defaults.get("max_parallel", 3)),
                             workdir=run_dir / "lanes" / "draft-probe")
    if not health["live"]:
        msg = f"no live drafting lane: {json.dumps(health['dead'])}"
        pc.comment(iid, f"RESULT: BLOCKED - {msg}")
        pc.park(iid, f"Retry when a free lane recovers. {msg}")
        remember(iid, "BLOCKED", (pc.issue(iid) or {}).get("updatedAt"), str(run_dir))
        return 0

    try:
        drafted = draft_mod.draft_spec(request, pool, health,
                                       int(defaults.get("timeout_sec", 900)),
                                       slug_hint=ident, profile=profile, depth=depth)
    except RuntimeError as exc:
        drafted = {"rejected": str(exc), "log_dir": str(run_dir)}

    if drafted.get("blocked"):
        question = drafted["blocked"]
        pc.comment(iid, f"RESULT: ESCALATED - {question}")
        pc.park(iid, f"Owner or CEO decision needed: {question}")
        remember(iid, "ESCALATED", (pc.issue(iid) or {}).get("updatedAt"), str(run_dir))
        return 0
    if drafted.get("rejected"):
        reason = drafted["rejected"]
        pc.comment(iid, (f"RESULT: BLOCKED - the task could not be turned into a checkable "
                         f"spec: {reason}. Draft trail: {drafted.get('log_dir')}. Add the "
                         f"expected deliverable and how it will be judged, then comment to "
                         f"resume."))
        pc.park(iid, f"Clarify deliverables and acceptance: {reason}")
        remember(iid, "BLOCKED", (pc.issue(iid) or {}).get("updatedAt"), str(run_dir))
        return 0

    spec_dict = drafted["spec"]
    spec_dict["board_issue"] = iid
    spec_path = draft_mod.save_spec(spec_dict, run_dir)
    spec = spec_mod.load(spec_path)
    pc.comment(iid, (f"Task spec drafted and validated: {spec_path} "
                     f"({spec_path.stat().st_size} bytes). {len(spec.deliverables)} "
                     f"deliverable(s), {len(spec.acceptance)} engine-run check(s), "
                     f"department gates included. Running the engine now."))

    ledger = Ledger(run_dir)
    try:
        outcome = orchestrator.run(spec, run_dir)
    except Exception as exc:                                   # noqa: BLE001
        ledger.event("run_error", error=str(exc)[:1500], type=type(exc).__name__)
        pc.comment(iid, f"RESULT: BLOCKED - engine error {type(exc).__name__}: {exc}. "
                        f"Ledger: {ledger.path}")
        pc.park(iid, f"Engine error, see {ledger.path}")
        remember(iid, "FAILED", (pc.issue(iid) or {}).get("updatedAt"), str(run_dir))
        return 1

    report_path = report_mod.write_report(spec, outcome, ledger, run_dir)
    ledger.event("run_end", status=outcome.status, detail=outcome.detail[:800])
    summary = report_mod.board_summary(spec, outcome, ledger, report_path)
    pc.comment(iid, summary)
    attached, how = pc.attach(iid, report_path)
    log(f"report attach: {attached} {how}")

    if outcome.status == "DONE":
        ok, why = pc.set_status(iid, "done")
        log(f"{ident}: done -> {ok} {why}")
    else:
        ok, why = pc.park(iid, f"{outcome.result_line}. Report: {report_path}")
        log(f"{ident}: parked -> {ok} {why}")
    remember(iid, outcome.status, (pc.issue(iid) or {}).get("updatedAt"), str(run_dir))
    return 0


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="engine-agent",
                                description="Paperclip process-adapter entry for the engine")
    p.add_argument("--issue", default=None, help="work this issue (manual or forced)")
    p.add_argument("--dry", action="store_true", help="stop after the first receipt")
    args = p.parse_args(argv)
    lanes_mod.reset_cooldowns()
    try:
        return run(args.issue, args.dry)
    finally:
        lanes_mod.reap_all_children()


if __name__ == "__main__":
    sys.exit(main())
