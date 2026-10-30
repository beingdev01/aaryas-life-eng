"""Deterministic gates. The engine runs the checks; no model adjudicates itself.

This is the module that makes the difference between "the lane said it worked" and
"it works". Acceptance commands execute here, in a subprocess with a timeout, and
their exit code and output are recorded verbatim in the ledger.
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from . import util


@dataclass
class CheckResult:
    name: str
    cmd: str
    passed: bool
    exit_code: int
    reason: str
    stdout_tail: str = ""
    stderr_tail: str = ""


def run_check(check, cwd: Path) -> CheckResult:
    work = Path(check.cwd or cwd)
    try:
        proc = subprocess.Popen(
            ["bash", "-lc", check.cmd], cwd=str(work),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", start_new_session=True,
        )
    except OSError as exc:
        return CheckResult(check.name, check.cmd, False, 126, f"could not start: {exc}")

    with proc:
        try:
            out, err = proc.communicate(timeout=check.timeout_sec)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait(timeout=10)
            out, err, rc = "", f"timed out after {check.timeout_sec}s", 124

    passed, reason = True, "ok"
    if rc != check.expect_exit:
        passed, reason = False, f"exit {rc}, expected {check.expect_exit}"
    elif check.expect_stdout and check.expect_stdout not in out:
        passed, reason = False, f"stdout missing {check.expect_stdout!r}"
    elif check.forbid_stdout and check.forbid_stdout in out:
        passed, reason = False, f"stdout contains forbidden {check.forbid_stdout!r}"

    return CheckResult(
        check.name, check.cmd, passed, rc, reason,
        util.redact(out[-2000:]), util.redact(err[-2000:]),
    )


def run_all(checks: list, cwd: Path, ledger, stage: str) -> tuple[bool, list[CheckResult]]:
    results = []
    for check in checks:
        res = run_check(check, cwd)
        results.append(res)
        ledger.event("gate", stage=stage, check=res.name, cmd=res.cmd,
                     passed=res.passed, exit_code=res.exit_code, reason=res.reason)
        util.write_text(ledger.dir / "gates" / f"{stage}.{util.slugify(res.name)}.txt",
                        f"$ {res.cmd}\nexit={res.exit_code} passed={res.passed} "
                        f"reason={res.reason}\n\n--- stdout ---\n{res.stdout_tail}\n"
                        f"--- stderr ---\n{res.stderr_tail}\n")
    return all(r.passed for r in results), results


def check_deliverables(deliverables: list, ledger, stage: str) -> tuple[bool, list]:
    """Receipt enforcement: declared artifacts must exist and be non-trivial."""
    declared = [{"path": d.path, "min_bytes": d.min_bytes} for d in deliverables]
    ok, receipts = ledger.check_receipts(declared)
    for rec in receipts:
        ledger.event("gate", stage=stage, check=f"deliverable:{rec.path}",
                     passed=rec.ok, exit_code=0 if rec.ok else 1,
                     reason=("ok" if rec.ok else
                             ("missing" if not rec.exists
                              else f"{rec.bytes}B < min {rec.min_bytes}B")),
                     bytes=rec.bytes)
    return ok, receipts


PRUNE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def snapshot(paths: list, max_files: int = 20000) -> dict:
    """mtime+size snapshot of a path set. Prunes heavy dirs instead of walking them."""
    snap: dict[str, list] = {}
    for root in paths:
        root = Path(root)
        if root.is_file():
            try:
                st = root.stat()
                snap[str(root)] = [st.st_mtime, st.st_size]
            except OSError:
                pass
            continue
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
            for name in filenames:
                if len(snap) >= max_files:
                    snap["__truncated__"] = [len(snap), 0]
                    return snap
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                snap[full] = [st.st_mtime, st.st_size]
    return snap


def diff_snapshots(before: dict, after: dict) -> dict:
    """Files created, modified, or deleted between two snapshots."""
    b = {k: v for k, v in before.items() if k != "__truncated__"}
    a = {k: v for k, v in after.items() if k != "__truncated__"}
    created = sorted(set(a) - set(b))
    deleted = sorted(set(b) - set(a))
    modified = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    return {"created": created, "modified": modified, "deleted": deleted,
            "truncated": "__truncated__" in before or "__truncated__" in after}
