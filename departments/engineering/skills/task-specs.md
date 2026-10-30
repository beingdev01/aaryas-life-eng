# Writing task specs the engine can verify

The engine decides "done" by running your checks itself. Write them so fake work fails.

## Deliverables
Absolute paths inside `authorized_paths`, each with a realistic `min_bytes` (the default
is 1 byte, so an empty file passes). Code or docs: at least 200, ideally near the real
size (a 150-line tool: 3000). Say in `description` what the file must contain.

## Acceptance: bad and good
| bad (passes on a fake) | good (fails on a fake) |
|---|---|
| `test -f tool.py` | `python3 -m py_compile tool.py` plus a test run |
| `ls dist/` | `cd app && npm test` |
| `python3 tool.py; echo ok` | `python3 tool.py --json \| python3 -c "import json,sys; d=json.load(sys.stdin); assert d['rows']; print('JSON_OK')"` with `expect_stdout: JSON_OK` |
| `pytest \|\| true` | `grep -q 'def classify' tool.py && ! grep -n TODO tool.py` |
| `cat README.md` | `! python3 tool.py empty.csv` (the failure path is part of the contract) |

Rules: join steps with `&&`, never `;` (the exit code is the last command's); no `|| true`;
quote any command starting with `[` (YAML reads it as a list); compile-only is never enough.

## Depth (engine/spec.py)
| depth | recon slices | sampling K | review rounds | red team | fix rounds | use for |
|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 0 | no | 1 | one-file fix, triage, a report |
| 2 | 2 | 1 | 1 | no | 1 | small multi-file change |
| 3 | 3 | 1 | 1 | yes | 2 | a normal build, the default |
| 4 | 4 | 2 | 2 | yes | 2 | wrong answer is expensive; best-of-2 per hard part |
| 5 | 6 | 3 | 2 | yes | 2 | department-scale builds |

## Titles and paths
Never use max, heavy, complex or architecture in a title: the old qoder runner matches them
and moves to a paid tier. List `banned_paths` (clubsite, clubsite-git, agents, bin). Never
authorize agents/, bin/, ~/.ssh or the engine's own code: the tripwire fails the run.

## Before running
`python3 tools/spec_lint.py <spec>` must exit 0, then `engctl validate <spec>`.
Start from `templates/task-spec.yaml`.
