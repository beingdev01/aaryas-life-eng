# Aarya's Life — engineering substrate

Sanitised export of the agent-organisation tooling built on one VM, running entirely on
**free model tiers**. Contains the build-and-verify engine, the nine department kits,
the runner scripts and the audit record.

Live data — CRM records, sponsor prospects, application trackers, rendered assets,
raw run transcripts — is deliberately **not** here. It lives in a private sibling repo.

## What is in here

| Path | What it is |
|---|---|
| `engine/` | the pipeline: intake → probe → recon → plan → plan red-team → best-of-K build → deterministic gate → cross-family review → fix → integrate → verify → repair. `engctl` is the CLI, `engine/*.py` the modules, `lanes.yaml` the model lanes. |
| `engine/tests/` | the engine's own regression suite. |
| `departments/` | nine department kits: `profile.yaml`, `CHARTER.md`, `runbooks/`, `skills/` (injected into every lane prompt), `tools/` (stdlib Python, each with a `test_*.py`), `templates/`, `checklists/`. |
| `agents/` | `CHARTER.md` (the organisation's rules), `DIRECTORY.md` (who does what), `ROUTING.md` (task → owner → chain → verifier). |
| `bin/` | process-adapter runners the scheduler invokes. |

## Running it

```bash
cd engine && python3 -W error::ResourceWarning -m unittest discover -s tests
./engctl lanes            # lane inventory and free-tier proof
./engctl probe            # which lanes actually answer right now
./engctl dept ../departments/research   # validate a department kit
./engctl draft --text "..."             # plain English -> validated task spec
./engctl run <spec.yaml>  # the full pipeline
./engctl bench --suite quality --modes baseline,engine
```

Requires one of `kilo`, `opencode` or `qodercli` on `PATH`, logged into a free tier.
No API key is stored in this repo; the runners read keys from `600`-permission files
outside the working tree.

## The rule this repo is built around

**Nothing here may call a paid model tier.** That is enforced in code, not prose:

1. every lane must prove the free offer is open by fetching the provider's own page
   (fail-closed, re-checked every 24 h);
2. a pre-run audit refuses to start if any enabled lane is not provably free;
3. every call is re-checked before it fires;
4. a runtime cost breaker kills the run the moment a lane reports nonzero cost;
5. issue titles are sanitised so words that route to a paid tier (`max`, `heavy`,
   `complex`, `architecture`) cannot appear in them.

Benchmark scores reported in `engine/` are measured against hidden tests that are copied
in only *after* the build, so no lane can code to them. Read
`engine/AUDIT.md` for what was broken before, and `departments/engineering/` for the
design notes. Treat the reported pass rates as sample-size-limited — the audit trail is
the point, not the headline number.

## Verify before publishing anything from this tree

```bash
python3 tools/scan_public.py <private-tree> <public-tree>
```

It cross-checks the candidate tree against every name, contact and phone in the private
data plus secret-shaped strings, and fails on any binary. The allowlist inside it records
why each accepted hit is safe; new hits require a human read.
