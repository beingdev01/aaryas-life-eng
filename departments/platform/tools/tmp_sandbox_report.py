#!/usr/bin/env python3
"""Read-only report of stale lane sandbox directories under /tmp.

Paperclip leaves one /tmp/paperclip-run-<issue>-<run>-<rand> scratch directory per
run, and engine builders leave /tmp/eng-* scratch. Nothing cleans them. This tool
lists them with size, file count and age (time since the newest file inside was
modified), marks any directory a live process still holds open (its cwd or an open
file descriptor, read from /proc/*/cwd and /proc/*/fd), and prints the exact
cleanup command for the CEO.

It never deletes anything. --print0-stale prints the stale, unheld directories
NUL-separated so the CEO's cleanup command can pipe them to `xargs -0 rm -rf --`;
the /proc check is repeated at that moment, so a directory that became busy in the
meantime is skipped.

Exit codes: 0 report produced, 2 usage error (root missing or unreadable).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import stat
import sys
import time
from pathlib import Path

DEFAULT_PATTERNS = ("paperclip-run-*", "eng-*")


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GiB"


def _disk_bytes(st) -> int:
    return st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size


def tree_stats(path: Path) -> dict:
    """Size, file count and newest mtime of a tree, never following symlinks."""
    size, files, unreadable = 0, 0, 0
    top = path.lstat()
    newest = top.st_mtime
    size += _disk_bytes(top)          # directory entries take blocks too
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        unreadable += 1
                        continue
                    newest = max(newest, st.st_mtime)
                    size += _disk_bytes(st)
                    if stat.S_ISDIR(st.st_mode):
                        stack.append(entry.path)
                    else:
                        files += 1
        except OSError:
            unreadable += 1
    return {"bytes": size, "files": files, "newest_mtime": newest, "unreadable": unreadable}


def held_paths(proc: Path) -> tuple[set, int]:
    """Every cwd and open-file target of every process we are allowed to read."""
    held, denied = set(), 0
    try:
        entries = list(proc.iterdir())
    except OSError:
        return held, 1
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            held.add(os.readlink(entry / "cwd"))
        except OSError:
            denied += 1
            continue
        try:
            for fd in os.listdir(entry / "fd"):
                try:
                    held.add(os.readlink(entry / "fd" / fd))
                except OSError:
                    pass
        except OSError:
            pass
    return held, denied


def is_held(path: str, held: set) -> bool:
    prefix = path.rstrip("/") + "/"
    return any(h == path or h.startswith(prefix) for h in held)


def scan(root: Path, patterns, older_than_h: float, proc: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    held, denied = held_paths(proc)
    uid = os.getuid()
    rows = []
    for entry in sorted(root.iterdir()):
        if not any(fnmatch.fnmatch(entry.name, p) for p in patterns):
            continue
        try:
            st = entry.lstat()
        except OSError:
            continue
        if not stat.S_ISDIR(st.st_mode):
            continue          # files and symlinks are never candidates
        info = tree_stats(entry)
        age_h = (now - info["newest_mtime"]) / 3600
        holder = is_held(str(entry), held)
        mine = st.st_uid == uid
        rows.append({
            "path": str(entry), "bytes": info["bytes"], "files": info["files"],
            "age_hours": round(age_h, 1), "held_open": holder, "owned_by_me": mine,
            "unreadable_entries": info["unreadable"],
            "stale": (age_h >= older_than_h) and not holder and mine,
        })
    stale = [r for r in rows if r["stale"]]
    return {
        "root": str(root), "patterns": list(patterns), "older_than_hours": older_than_h,
        "dirs": len(rows), "bytes": sum(r["bytes"] for r in rows),
        "stale_dirs": len(stale), "stale_bytes": sum(r["bytes"] for r in stale),
        "held_dirs": sum(1 for r in rows if r["held_open"]),
        "not_mine": sum(1 for r in rows if not r["owned_by_me"]),
        "procs_unreadable": denied, "rows": rows,
    }


def cleanup_command(report: dict, tool: str) -> str:
    pats = " ".join(f"--pattern '{p}'" for p in report["patterns"])
    return (f"python3 {tool} --root {report['root']} --older-than-hours "
            f"{report['older_than_hours']:g} {pats} --print0-stale | xargs -0 -r rm -rf --")


def render(report: dict, tool: str, limit: int) -> str:
    rows = sorted(report["rows"], key=lambda r: -r["bytes"])
    lines = [
        f"# /tmp sandbox report: {report['root']}", "",
        f"- Patterns: {', '.join(report['patterns'])}",
        f"- Directories: {report['dirs']}, {human(report['bytes'])} on disk",
        f"- Stale (no change for {report['older_than_hours']:g}h or more, not held open, "
        f"owned by this user): {report['stale_dirs']}, {human(report['stale_bytes'])}",
        f"- Held open by a live process: {report['held_dirs']}",
        f"- Owned by another user (never touched): {report['not_mine']}",
    ]
    if report["procs_unreadable"]:
        lines.append(f"- {report['procs_unreadable']} processes belong to other users and "
                     "could not be inspected; directories they hold are not visible here")
    lines += ["", f"## Largest {min(limit, len(rows))} directories", "",
              "| path | size | files | age h | held | stale |", "|---|---|---|---|---|---|"]
    for r in rows[:limit]:
        lines.append(f"| {r['path']} | {human(r['bytes'])} | {r['files']} | {r['age_hours']} | "
                     f"{'yes' if r['held_open'] else '-'} | {'yes' if r['stale'] else '-'} |")
    lines += ["", "## Commands for the CEO", ""]
    if not report["stale_dirs"]:
        lines.append("No commands needed: nothing is stale.")
    else:
        lines += ["platform-1 never deletes. To reclaim the stale directories, run as ubuntu "
                  "(the /proc check is repeated at that moment, so busy directories are skipped):",
                  "", "```", f"du -sh {report['root']}", cleanup_command(report, tool),
                  f"du -sh {report['root']}", "```"]
    return "\n".join(lines) + "\n"


def build_parser():
    p = argparse.ArgumentParser(
        prog="tmp_sandbox_report.py",
        description="Read-only report of stale paperclip-run-* and eng-* sandbox "
                    "directories. Never deletes; prints the CEO's cleanup command.")
    p.add_argument("--root", default="/tmp", help="directory to scan (default /tmp)")
    p.add_argument("--older-than-hours", type=float, default=24.0,
                   help="a directory with no change for this long is stale (default 24)")
    p.add_argument("--pattern", action="append", default=None,
                   help="glob for candidate directory names (repeatable; default "
                        "paperclip-run-* and eng-*)")
    p.add_argument("--proc", default="/proc", help="proc filesystem root (for tests)")
    p.add_argument("--limit", type=int, default=40, help="rows to show in the table")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.add_argument("--out", default=None, help="also write the markdown report here")
    p.add_argument("--print0-stale", action="store_true",
                   help="print only stale, unheld directory paths, NUL-separated")
    return p


def main(argv=None, now: float | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"tmp_sandbox_report: root {root} is not a directory", file=sys.stderr)
        return 2
    if args.older_than_hours < 1:
        print("tmp_sandbox_report: --older-than-hours below 1 would catch live runs; refused",
              file=sys.stderr)
        return 2
    try:
        report = scan(root.resolve(), args.pattern or DEFAULT_PATTERNS, args.older_than_hours,
                      Path(args.proc), now)
    except OSError as exc:
        print(f"tmp_sandbox_report: cannot scan {root}: {exc}", file=sys.stderr)
        return 2
    tool = str(Path(__file__).resolve())
    if args.print0_stale:
        for r in report["rows"]:
            if r["stale"]:
                sys.stdout.write(r["path"] + "\0")
        return 0
    text = render(report, tool, args.limit)
    if args.out:
        try:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text)
        except OSError as exc:
            print(f"tmp_sandbox_report: cannot write {args.out}: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps({**report, "cleanup_command": cleanup_command(report, tool)}, indent=2))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
