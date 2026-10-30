# quality-2 independent review — Engineering task engine (organisation-rebuild)

**Reviewer:** quality-2 (independent, different model family from builder Qoder)
**Scope:** `organisation-rebuild/departments/engineering/pipeline/` + `ENGINE_DESIGN.md`
**Tests:** `python3 -m unittest discover -s tests -v` → 39/39 PASS
**Verdict:** APPROVE with non-blocking findings (no paid-lane, no credential, no path-traversal exposure found)

## What I checked
- Free-lane guard (`guard.py`): every enabled lane identifier must end in `:free`/`-free` and contain none of the paid markers. `lanes.yaml` passes `test_lane_pool_on_disk_is_all_free`.
- Receipt enforcement (`ledger.check_receipts`, `gate.check_deliverables`): missing or trivial files cannot pass as done. Tested.
- Gate execution (`gate.run_check`): timeout enforced, exit code + stdout/stderr recorded, redacted.
- Lane invocation (`lanes.invoke`): bounded by hard `timeout`, process group killed on hang, `--title` passed to avoid paid title call, `--auto` only on build/fix/integrate.
- Concurrency: `ThreadPoolExecutor(max_workers)` with default 3; isolated `--dir` per attempt. No shared lock on execution path.
- Independent review family exclusion (`lanes.pick` with `exclude_families`): reviewer forced off builder's family.
- Redaction (`util.redact`): applied to all stored artifacts; tests pass.
- Spec intake gate: refuses specs with no acceptance/deliverables or thin goal.

## Findings
- **M-1 (medium) gate.run_check timeout path:** after `os.killpg`, calls `proc.wait(timeout=10)` with no outer guard. A second `TimeoutExpired` would propagate and abort the whole gate instead of being recorded as a timeout result. Fix: wrap in try/except and set rc=124.
- **M-2 (medium) run_fix lane reuse:** reuses the exact builder lane for fix-ups. Charter allows up to 2 fix rounds by the same builder, so this is compliant, but if that lane died between build and fix, `lane_by_id` still holds a stale lane and `pick` fallback only triggers when lane.id not in live set. Acceptable, but worth logging when fallback fires (currently silent).
- **M-3 (low) guard DENY_SUBSTRINGS breadth:** the substring `"max"` would reject any future free model whose name contains "max" (e.g. a hypothetical `foo-max:free`). Not a current problem — all lanes pass. Consider anchoring to tier markers rather than substrings when new lanes are added.
- **M-4 (low) sanitize_title word replacement:** replaces whole-word "max"/"heavy"/etc. globally, which could mangle legitimate titles ("maximum" → "fullimum"). Cosmetic; titles are capped at 60 chars. Low risk.
- **M-5 (low) _dump_files path reads:** reads deliverable paths verbatim. Specs are author-controlled in this staging context, but if the engine is later fed untrusted specs, add a path-containment check against the workdir/authorized paths.
- **M-6 (info) no Paperclip write-back:** the engine does not update board issue status; that is by design (Paperclip is system of record, engine is executor) and documented. CEO must drive status transitions externally. Fine.

## Non-findings (verified clean)
- No `shell=True` anywhere; all subprocess calls use argument lists.
- No credential reads; `redact` applied to stored text.
- No paid model can be dispatched: `guard.enforce` raises before dispatch and `invoke` re-checks per call.
- No writes outside workdir by the engine itself (lanes are constrained by `--dir`; path discipline is a post-hoc check).

## Recommendation
Stage is sound. Tests pass. Ready for CEO review of `INSTALL_PLAN.md` before anything lands in `agents/` or `departments/`. I recommend M-1 be fixed before first live run; M-2..M-6 can ride along or be tracked as follow-ups.
