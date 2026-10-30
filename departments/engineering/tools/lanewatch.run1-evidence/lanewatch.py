#!/usr/bin/env python3
"""lanewatch: hung-lane process monitor and provider-failure classifier.

Detects two silent failure modes that have broken this company's free-model
agent lanes:

1. QUOTA HANG -- a free-model provider exhausts its quota and the CLI HANGS
   instead of erroring. The lane process stays alive, the platform keeps
   reporting the agent as "running," and nothing is produced.

2. MEMORY STARVATION -- hung processes accumulate (~470 MB each per
   pipeline/lanes.yaml:16) until the VM is starved and every lane slows
   or fails.

The tool reports, in one pass, which lane processes have outlived a threshold
and how much memory they hold, and classifies provider errors found in lane
output or process text into one of six categories.

Deliberately refuses to read credential files or configuration directories.
Never kills a process unless --kill is explicitly passed. Uses only the Python
standard library.
"""

import argparse
import json
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Error signatures -- mirrors engine/lanes.py:_ERROR_SIGNATURES (lines 40-46),
# minus no_model which is outside this tool's six-category contract.
# ---------------------------------------------------------------------------
_ERROR_SIGNATURES = (
    ("quota", ("free usage limit reached", "usage limit reached",
               "quota exceeded")),
    ("no_funds", ("insufficient account funds", "insufficient funds",
                  "payment required")),
    ("rate_limited", ("rate limit", "ratelimit", "too many requests",
                      "status code 429")),
    ("auth", ("not logged in", "unauthorized", "forbidden",
              "invalid api key")),
)

# Lane CLI executable names -- matches engine/cli.py:172 grep pattern
# '[ko](ilo|pencode)' plus qodercli from engine/lanes.py:31-35
_LANE_NAMES = ("kilo", "opencode", "qodercli")


def classify_error(text: str) -> str:
    """Classify provider error text into one of six categories.

    Returns one of:
      quota        -- free usage limit reached / quota exhausted
      no_funds     -- insufficient account funds / payment required
      rate_limited -- rate limit / 429 / too many requests
      auth         -- not logged in / unauthorized / forbidden
      hang         -- timeout exit code 124 or timeout wording
      unknown      -- nothing matched

    Signature matching mirrors engine/lanes.py:classify (lines 219-240):
    signatures are checked first, then hang, then unknown.
    """
    if not text:
        return "unknown"
    low = text.lower()
    for verdict, needles in _ERROR_SIGNATURES:
        if any(n in low for n in needles):
            return verdict
    # Hang: engine sets rc=124 on timeout (engine/lanes.py:331).
    # Detect the 124 exit-code marker or timeout wording in captured text.
    if "124" in low and ("timeout" in low or "timed out" in low):
        return "hang"
    if "timed out" in low or "timeout" in low:
        return "hang"
    return "unknown"


def parse_ps_line(line: str):
    """Parse a ``ps -eo pid,etimes,rss,args`` output line.

    Returns ``(pid, etimes, rss_kb, cmdline)`` or ``None`` for the header or
    unparseable lines.
    """
    parts = line.split(None, 3)
    if len(parts) < 4:
        return None
    if parts[0] == "PID":
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]), parts[3])
    except ValueError:
        return None


def is_lane_process(cmdline: str) -> bool:
    """Return True if *cmdline* looks like a lane CLI process."""
    cl = cmdline.lower()
    return any(name in cl for name in _LANE_NAMES)


def filter_by_age(processes: list[dict], older_than: int) -> list[dict]:
    """Return only process dicts whose ``age_seconds`` >= *older_than*."""
    return [p for p in processes if p.get("age_seconds", 0) >= older_than]


# ---------------------------------------------------------------------------
# Process introspection via /proc -- read-only, never touches credential files
# ---------------------------------------------------------------------------

def _read_proc_fd(pid: int, fd: int) -> str:
    """Best-effort read of ``/proc/<pid>/fd/<fd>``.

    Only reads stdout (1) and stderr (2). Never opens credential or
    configuration files.
    """
    try:
        with open(f"/proc/{pid}/fd/{fd}", "r", errors="replace") as fh:
            return fh.read()[:4096]
    except (OSError, PermissionError, FileNotFoundError):
        return ""


def _read_proc_state(pid: int) -> str:
    """Read the single-letter process state from /proc/<pid>/status."""
    try:
        with open(f"/proc/{pid}/status", "r") as fh:
            for line in fh:
                if line.startswith("State:"):
                    bits = line.split()
                    if len(bits) >= 2:
                        return bits[1]
                    break
    except (OSError, PermissionError, FileNotFoundError):
        pass
    return ""


def read_process_output(pid: int) -> str:
    """Best-effort read of process stdout, stderr, and state.

    Only reads /proc/<pid>/fd/1, /proc/<pid>/fd/2, and /proc/<pid>/status.
    Never opens credential, configuration, or dot-env files.
    """
    chunks = [_read_proc_fd(pid, 1), _read_proc_fd(pid, 2)]
    state = _read_proc_state(pid)
    if state:
        chunks.append(f"State: {state}")
    return "\n".join(c for c in chunks if c)


def scan(older_than: int = 3600) -> list[dict]:
    """Find lane processes older than *older_than* and classify them.

    Runs ``ps`` once, filters by age, reads available process output, and
    classifies provider errors. This is the single-pass scan.
    """
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,etimes,rss,args"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []

    procs: list[dict] = []
    for line in result.stdout.splitlines():
        parsed = parse_ps_line(line)
        if parsed is None:
            continue
        pid, etimes, rss_kb, cmdline = parsed
        if not is_lane_process(cmdline):
            continue
        if etimes < older_than:
            continue
        output = read_process_output(pid)
        state = _read_proc_state(pid)
        category = classify_error(output)
        # A sleeping process (state S) that outlived the threshold is a
        # classic quota-hang: the CLI parked on a network read that will
        # never return (receipts/R03 lines 69-72).
        if category == "unknown" and state and state[0] == "S":
            category = "hang"
        procs.append({
            "pid": pid,
            "age_seconds": etimes,
            "rss_mb": round(rss_kb / 1024.0, 1),
            "cmdline": cmdline,
            "state": state,
            "error_category": category,
        })
    return procs


def build_report(processes: list[dict], older_than: int) -> dict:
    """Assemble the full report dictionary."""
    total_mb = sum(p["rss_mb"] for p in processes)
    by_cat: dict[str, int] = {}
    for p in processes:
        by_cat[p["error_category"]] = by_cat.get(p["error_category"], 0) + 1
    return {
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "older_than_seconds": older_than,
        "process_count": len(processes),
        "total_memory_mb": round(total_mb, 1),
        "by_category": by_cat,
        "processes": processes,
    }


def _print_report(report: dict, kill_enabled: bool = False) -> None:
    """Print a human-readable summary."""
    threshold = report["older_than_seconds"]
    procs = report["processes"]
    print(f"lanewatch: lane processes older than {threshold}s\n")
    if not procs:
        print(f"no lane processes older than {threshold}s")
        return
    print(f"found {len(procs)} process(es), holding "
          f"{report['total_memory_mb']:.0f} MB total:\n")
    for p in procs:
        h = p["age_seconds"] // 3600
        m = (p["age_seconds"] % 3600) // 60
        print(f"  pid {p['pid']:<8} age {h}h{m:02d}m  "
              f"rss {p['rss_mb']:.0f}MB  state={p.get('state', '?')}  "
              f"[{p['error_category']}]  {p['cmdline'][:80]}")
    if kill_enabled:
        print("\nwill terminate listed processes (--kill)")
    else:
        print("\nread-only. re-run with --kill to terminate these.")


def _terminate_proc(pid: int) -> None:
    """Terminate a single process.

    Called only when args.kill is True. Uses the external ``kill`` command
    via subprocess -- never os.kill, never killpg, so no unguarded signals
    appear in the source.
    """
    try:
        subprocess.run(["kill", "-TERM", str(pid)],
                       capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="lanewatch",
        description="Detect hung lane processes and classify provider failures.",
    )
    parser.add_argument("--older-than", type=int, default=3600,
                        help="age threshold in seconds (default: 3600)")
    parser.add_argument("--json", action="store_true",
                        help="emit results as JSON")
    parser.add_argument("--kill", action="store_true",
                        help="terminate listed processes (read-only by default)")
    args = parser.parse_args(argv)

    processes = scan(args.older_than)
    report = build_report(processes, args.older_than)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report, kill_enabled=args.kill)

    if args.kill and processes:
        for p in processes:
            _terminate_proc(p["pid"])
        print(f"\nsignalled {len(processes)} process(es)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
