# Code review checklist

For quality-2 (and opencode-1 on review duty). Never use it on your own build. Every "no"
becomes a finding with severity, file:line, problem and fix.

## Before reading code
- [ ] I did not build any part of this. The run's parts table names a different builder
      and a different model family.
- [ ] I have the spec, the frozen contract for each part, and the RUN_REPORT.md.
- [ ] I re-ran every acceptance command myself and recorded the exit codes.

## Correctness
- [ ] Each part does what its contract says for valid input, and the failure path behaves
      as specified (exit codes, error messages, no partial writes).
- [ ] Boundaries: empty input, one item, the maximum, unicode, a missing file.
- [ ] Tests exercise the real code path, not a mock that always passes; deleting the core
      logic would make at least one test fail.

## Completeness
- [ ] No stub, `pass` body, placeholder return, TODO, FIXME or commented-out code.
- [ ] Every feature named in the contract exists; nothing extra was added.
- [ ] `--help` works and errors exit non-zero with a one-line reason on stderr (tools).

## Constraints
- [ ] No credential read or printed; no `.env`, `~/.config`, `~/.ssh` paths.
- [ ] No network call, send, deploy or service restart unless the spec allows it.
- [ ] Writes only inside the part's owned files; nothing under banned paths.
- [ ] No paid model named or selected; no title or issue text with max, heavy, complex or
      architecture.
- [ ] Standard library only where the spec says so.

## Style (only where it affects correctness or readability)
- [ ] Names say what things are; functions do one thing; no dead branches.

## Report
- [ ] Written from `templates/review-report.md`; `python3 tools/review_lint.py <file>` exits 0.
- [ ] Verdict APPROVE only with no critical or high finding open. APPROVE with no findings
      is fine; REVISE lists exactly what to change.
