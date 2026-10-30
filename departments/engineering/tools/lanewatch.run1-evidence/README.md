# lanewatch — Lane Health and Hung-Process Monitor

## What it detects

Two silent failure modes that have broken this company's free-model agent lanes:

1. **Quota hang.** A free-model provider (OpenCode Zen, Kilo gateway) runs out of
   quota and its CLI *hangs* instead of exiting with an error. The lane process
   stays alive in `State: S (sleeping)`, the platform keeps reporting the agent as
   `"running"`, and zero output is produced. The process parks on a network read
   that will never return.

2. **Memory starvation.** Hung processes accumulate — each holding roughly 470 MB
   resident (per `pipeline/lanes.yaml:16`) — until the VM is starved and every lane
   slows or fails. Six hung `opencode` processes were observed holding ~2.8 GB
   (receipts/R03 lines 69-70).

## How to run

```
python3 lanewatch.py                 # default: --older-than 3600, text output
python3 lanewatch.py --json          # structured JSON (pipeable, machine-readable)
python3 lanewatch.py --older-than 600  # flag processes older than 600 seconds
python3 lanewatch.py --kill          # terminate listed processes (opt-in only)
python3 lanewatch.py --json --older-than 1200 | jq .
```

Flags are composable. Without arguments the tool runs read-only with a 3600-second
threshold and prints a human-readable summary.

## How to read the output

JSON mode (`--json`) emits a top-level object with these keys:

| key                  | type   | description                                         |
|----------------------|--------|-----------------------------------------------------|
| `scanned_at`         | string | UTC timestamp of the scan                           |
| `older_than_seconds` | int    | threshold used                                      |
| `process_count`      | int    | number of matching processes                        |
| `total_memory_mb`    | float  | sum of RSS across all listed processes              |
| `by_category`        | object | count of processes per `error_category`             |
| `processes`          | array  | per-process detail (see below)                      |

Each entry in `processes` contains:

| field            | type   | description                                           |
|------------------|--------|-------------------------------------------------------|
| `pid`            | int    | OS process ID                                         |
| `age_seconds`    | int    | elapsed seconds since the process started             |
| `rss_mb`         | float  | resident set size in MB                               |
| `cmdline`        | string | full command line that started the process             |
| `state`          | string | process state letter from `/proc/<pid>/status` (e.g. `S`) |
| `error_category` | string | one of the six categories below                        |

### Error categories (`error_category`)

All values are lowercase. The tool classifies provider errors found in lane
output or log text into:

| category       | meaning                                                       |
|----------------|---------------------------------------------------------------|
| `quota`        | Free usage limit reached / quota exceeded                     |
| `no_funds`     | Insufficient account funds / payment required                 |
| `rate_limited` | Rate limit / ratelimit / status code 429 / too many requests  |
| `auth`         | Not logged in / unauthorized / forbidden / invalid api key    |
| `hang`         | Timeout (exit 124) or sleeping process that outlived threshold |
| `unknown`      | No matching signature found                                   |

Signature matching mirrors `engine/lanes.py:_ERROR_SIGNATURES` — signatures are
checked first, then hang (exit-code 124 or timeout wording), then unknown.

### Example JSON output

```json
{
  "scanned_at": "2026-10-30T14:57:00Z",
  "older_than_seconds": 3600,
  "process_count": 2,
  "total_memory_mb": 935.0,
  "by_category": {"hang": 1, "quota": 1},
  "processes": [
    {
      "pid": 3421,
      "age_seconds": 7200,
      "rss_mb": 470.0,
      "cmdline": "/usr/bin/opencode run --format json --title probe -m opencode/mimo-v2.6-flash-free",
      "state": "S",
      "error_category": "quota"
    },
    {
      "pid": 3430,
      "age_seconds": 3601,
      "rss_mb": 465.0,
      "cmdline": "/usr/bin/kilo run --format json -m kilo/poolside/laguna-s-2.1:free",
      "state": "S",
      "error_category": "hang"
    }
  ]
}
```

Text mode prints the same processes in aligned columns with human-readable
age (`Xh Ym`) and RSS (`N MB`).

## What it deliberately refuses

- **Never reads ~/.config, .env, or API keys.** It only reads `/proc/<pid>/fd/1`,
  `/proc/<pid>/fd/2`, and `/proc/<pid>/status` for process introspection. No
  credential file, configuration directory, or environment-variable file is ever
  opened.
- **Never kills without --kill.** By default the tool is read-only. The `--kill`
  flag must be passed explicitly to terminate any process.
- **Uses only Python stdlib.** No third-party packages, no pip installs.
- **Never auto-restarts or modifies services.** It reports and diagnoses only.
