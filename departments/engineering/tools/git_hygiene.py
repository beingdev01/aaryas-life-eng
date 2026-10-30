#!/usr/bin/env python3
"""Read-only git hygiene report for a repository, built to gate "push immediately".

On 20 Oct 2026 the branch feat/cert-templates-api was reset in a shared working copy
and seven reviewed commits survived only through a backup/* branch and the reflog.
They were at risk because they existed on one disk and nowhere else. This tool finds
that state before it costs anything:

- current branch, or a detached HEAD (and whether its commits are on any branch);
- dirty files (tracked changes and untracked files);
- every local branch with no upstream, a gone upstream, or commits ahead of it;
- commits on each branch that are on no remote-tracking ref (the work at risk);
- stash count, and an unfinished merge, rebase, cherry-pick or bisect;
- whether .git looks broken (for example the live clubsite deploy tree, which has a
  .git directory holding only config and ORIG_HEAD).

Only read-only git commands run: rev-parse, status, branch, rev-list, stash list,
with GIT_OPTIONAL_LOCKS=0 so status does not even refresh the index. Nothing is
fetched, so "on a remote" means "on a remote-tracking ref as of the last fetch".

Exit codes: 0 nothing at risk, 1 unpushed work at risk or a broken repository
(or dirty files with --fail-on-dirty), 2 not a repository or a usage error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from os import environ as process_env
from pathlib import Path

GIT_TIMEOUT = 60
IN_PROGRESS = {"MERGE_HEAD": "merge", "rebase-merge": "rebase", "rebase-apply": "rebase or am",
               "CHERRY_PICK_HEAD": "cherry-pick", "REVERT_HEAD": "revert", "BISECT_LOG": "bisect"}


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    env = dict(process_env)
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
                "GIT_CEILING_DIRECTORIES": str(repo.parent)})
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git {args[0]} could not run: {exc}") from exc
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def broken_git_dir(repo: Path) -> list:
    """Missing pieces of a .git directory. Empty list means it looks whole."""
    gd = repo / ".git"
    if gd.is_file():
        return []            # worktree or submodule pointer; git itself will judge it
    missing = [name for name in ("HEAD", "objects", "refs") if not (gd / name).exists()]
    return missing


def branches(repo: Path) -> list:
    fmt = "%(refname)%09%(upstream:short)%09%(upstream:track,nobracket)%09%(committerdate:relative)"
    out = git(repo, "branch", "--list", f"--format={fmt}")
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = (line.split("\t") + ["", "", "", ""])[:4]
        if not parts[0].startswith("refs/heads/"):
            continue          # the "(HEAD detached at ...)" pseudo-entry
        rows.append({"name": parts[0][len("refs/heads/"):], "upstream": parts[1], "track": parts[2],
                     "last_commit": parts[3]})
    return rows


def count(repo: Path, *args: str) -> int:
    return int(git(repo, "rev-list", "--count", *args).strip() or 0)


def inspect(repo: Path) -> dict:
    repo = repo.resolve()
    report = {"repo": str(repo), "broken": False, "problems": [], "warnings": []}
    if not (repo / ".git").exists():
        raise GitError(f"{repo} is not a git repository (no .git)")
    missing = broken_git_dir(repo)
    if missing:
        report["broken"] = True
        report["problems"].append(
            f".git exists but is missing {', '.join(missing)}: this is not a working copy "
            "(a deploy target or a damaged clone). Never commit, reset or pull here; work "
            "in a proper clone")
        return report
    try:
        top = git(repo, "rev-parse", "--show-toplevel").strip()
    except GitError as exc:
        if "dubious ownership" in str(exc) or "safe.directory" in str(exc):
            raise GitError(f"{repo} is owned by another user; git refuses to read it "
                           "(safe.directory). Run as the owner") from exc
        report["broken"] = True
        report["problems"].append(f"git cannot read this repository: {exc}")
        return report
    if Path(top).resolve() != repo:
        raise GitError(f"{repo} is inside the repository {top}; pass the top-level directory")

    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir").strip())
    head_ok = git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).strip()
    report["head"] = head_ok[:12] if head_ok else None
    abbrev = git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    report["detached"] = abbrev == "HEAD"
    report["branch"] = None if report["detached"] else (abbrev or None)
    remotes_refs = [r.strip() for r in git(repo, "branch", "-r", "--format=%(refname:short)").splitlines()
                    if r.strip()]
    report["remote_tracking_refs"] = len(remotes_refs)

    status = git(repo, "status", "--porcelain=v1", "--untracked-files=normal")
    tracked, untracked = [], []
    for line in status.splitlines():
        if line.startswith("??"):
            untracked.append(line[3:])
        elif line.strip():
            tracked.append(line[3:])
    report["dirty_tracked"] = tracked
    report["untracked"] = untracked

    rows = branches(repo) if head_ok else []
    at_risk = []
    for b in rows:
        ref = f"refs/heads/{b['name']}"
        b["unique_commits"] = count(repo, ref, "--not", "--remotes")
        b["ahead"] = b["behind"] = 0
        if b["upstream"] and b["track"] != "gone":
            lr = git(repo, "rev-list", "--left-right", "--count",
                     f"{ref}...{b['upstream']}", check=False).split()
            if len(lr) == 2:
                b["ahead"], b["behind"] = int(lr[0]), int(lr[1])
        if not b["upstream"]:
            b["state"] = "no upstream"
        elif b["track"] == "gone":
            b["state"] = "upstream gone"
        elif b["ahead"]:
            b["state"] = f"ahead {b['ahead']}"
        else:
            b["state"] = "pushed"
        if b["unique_commits"]:
            at_risk.append(b)
    report["branches"] = rows
    report["at_risk"] = [b["name"] for b in at_risk]

    if report["detached"] and head_ok:
        orphan = count(repo, "HEAD", "--not", "--branches", "--remotes")
        report["detached_unique_commits"] = orphan
        if orphan:
            report["problems"].append(
                f"detached HEAD carries {orphan} commit(s) on no branch and no remote; "
                "create a branch for them and push it before anything else")
        else:
            report["warnings"].append("detached HEAD (no unique commits)")

    stash = [ln for ln in git(repo, "stash", "list", check=False).splitlines() if ln.strip()]
    report["stashes"] = len(stash)
    if stash:
        report["warnings"].append(f"{len(stash)} stash entr{'y' if len(stash) == 1 else 'ies'}; "
                                  "a stash is local only and is lost with the clone")
    ops = [label for name, label in IN_PROGRESS.items() if (git_dir / name).exists()]
    report["in_progress"] = ops
    if ops:
        report["warnings"].append(f"unfinished {', '.join(ops)} in progress")
    if not head_ok:
        report["warnings"].append("repository has no commits yet")
    if not remotes_refs:
        report["warnings"].append("no remote-tracking refs at all: nothing in this repository "
                                  "exists anywhere but this disk")
    for b in at_risk:
        why = {"no upstream": "has no upstream", "upstream gone": "lost its upstream"}.get(
            b["state"], f"is {b['state']} of {b['upstream']}")
        report["problems"].append(
            f"branch {b['name']} {why}; {b['unique_commits']} commit(s) exist on no remote")
    if tracked or untracked:
        report["warnings"].append(f"{len(tracked)} modified tracked file(s), "
                                  f"{len(untracked)} untracked")
    return report


def push_commands(report: dict) -> list:
    cmds = []
    for b in report.get("branches", []):
        if b["name"] not in report.get("at_risk", []):
            continue
        if b["name"] in ("main", "master") and b["upstream"]:
            cmds.append(f"git -C {report['repo']} push origin {b['name']}    "
                        "# fast-forward only; never --force on main")
        elif report.get("remote_tracking_refs"):
            cmds.append(f"git -C {report['repo']} push -u origin {b['name']}")
        else:
            cmds.append(f"# {b['name']}: no remote configured; add one (CEO decision) before "
                        "this work can be pushed anywhere")
    return cmds


def render(report: dict) -> str:
    lines = [f"# Git hygiene: {report['repo']}", ""]
    if report["broken"]:
        lines += ["- Verdict: **BROKEN**", ""] + [f"- {p}" for p in report["problems"]]
        return "\n".join(lines) + "\n"
    verdict = "AT RISK" if report["problems"] else "OK"
    lines += [
        f"- Verdict: **{verdict}**",
        f"- HEAD: {'detached at ' + str(report['head']) if report['detached'] else report['branch']}"
        f" ({report['head'] or 'no commits'})",
        f"- Dirty: {len(report['dirty_tracked'])} modified tracked, {len(report['untracked'])} untracked",
        f"- Stashes: {report['stashes']}",
        f"- Remote-tracking refs: {report['remote_tracking_refs']} (as of the last fetch; "
        "this tool never fetches)",
        f"- Unfinished operations: {', '.join(report['in_progress']) or 'none'}", "",
        "## Branches", "", "| branch | upstream | state | commits on no remote | last commit |",
        "|---|---|---|---|---|"]
    for b in report["branches"]:
        lines.append(f"| {b['name']} | {b['upstream'] or '-'} | {b['state']} | "
                     f"{b['unique_commits']} | {b['last_commit']} |")
    if report["dirty_tracked"] or report["untracked"]:
        lines += ["", "## Dirty files (first 20)", ""]
        lines += [f"- M {p}" for p in report["dirty_tracked"][:20]]
        lines += [f"- ? {p}" for p in report["untracked"][:max(0, 20 - len(report['dirty_tracked']))]]
    lines += ["", "## Problems", ""] + ([f"- {p}" for p in report["problems"]] or ["None."])
    lines += ["", "## Warnings", ""] + ([f"- {w}" for w in report["warnings"]] or ["None."])
    cmds = push_commands(report)
    if cmds:
        lines += ["", "## To make the work safe", "", "```"] + cmds + ["```"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="git_hygiene.py",
        description="Read-only git hygiene report. Fails when local commits exist on no "
                    "remote (unpushed work at risk) or the .git directory is broken.")
    p.add_argument("repo", help="top-level directory of the repository")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument("--fail-on-dirty", action="store_true",
                   help="also fail when the working tree has changes")
    args = p.parse_args(argv)
    try:
        report = inspect(Path(args.repo))
    except GitError as exc:
        print(f"git_hygiene: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else render(report), end="" if not args.json else "\n")
    failing = list(report["problems"])
    if args.fail_on_dirty and (report.get("dirty_tracked") or report.get("untracked")):
        failing.append("working tree is dirty")
    if failing:
        print(f"git_hygiene: {report['repo']}: {len(failing)} problem(s): {failing[0][:200]}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
