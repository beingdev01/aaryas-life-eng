# Lane health and resource watch

Company work runs on free model lanes (kilo and opencode CLIs). When a free provider runs
out of quota the CLI does not exit, it hangs (R03), and Paperclip keeps showing the agent
as `running` because the process is alive.

## Signatures
- Hung lane: an `opencode run` or `kilo run` process older than 1 hour, sleeping, about
  400-470 MB resident. No engine lane call runs past 15 minutes (`timeout_sec: 900`), so
  anything older is not working. On 30 Oct six opencode processes pinned to
  `opencode/mimo-v2.6-flash-free` and `opencode/beam-free` had been alive 11-14 hours.
- A kilo lane is two processes: a ~35 MB `node .../kilo` wrapper and a `.kilo` worker that
  can reach 800 MB while working. Count the pair once.
- Provider errors, from stderr or error events only: "Free usage limit reached" (quota),
  "Insufficient account funds" (no_funds), "rate limit" or 429 (rate_limited), "Not logged
  in" or "Unauthorized" (auth). A lane that quotes these in its reply is not exhausted.
- /tmp growth: one `/tmp/paperclip-run-<issue>-<run>-<rand>` per Paperclip run, never
  cleaned; engine scratch is `/tmp/eng-*`. On 30 Oct: 1,726 directories but only 1.4 MiB,
  so today it is clutter, not disk pressure. Report the count and the trend.

## How to read them
1. `health_report.py --out <work_root>/health/<stamp>.md` lists lane processes with pid,
   ppid, age, RSS, model and title, and breaches on any older than 1 hour.
2. `engctl reap --older-than 3600` lists the same. It is list-only; it signals nothing
   unless `--kill` is passed, which is the CEO's call after checking in Paperclip that no
   in_progress issue depends on the run.
3. `tmp_sandbox_report.py --root /tmp --older-than-hours 24` sizes sandboxes and marks any
   a live process holds (cwd or open fd, from /proc). Its cleanup command for the CEO
   re-checks /proc at the moment it runs.
4. MemAvailable under 1 GiB with hung lanes present: suspect the lanes first.

## In the report
Counts and totals (processes, MiB held, oldest age), pids, the model each is pinned to,
and the reap command for the CEO. Never `--kill`, never `rm`, never probe a lane yourself:
probing runs a model CLI, and that is the engine's job.
