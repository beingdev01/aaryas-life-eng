# Department kit contract

Every department in Aarya's Life is one shared execution engine plus a **kit**. The
engine (`departments/engineering/pipeline/`, command `engctl`) does the work through free
model lanes. The kit makes the work come out right for that department, and lets the
department's own tools check it.

A kit lives in `departments/<dept>/` and must contain:

```
departments/<dept>/
  profile.yaml            machine-readable profile (schema below) — the engine loads it
  CHARTER.md              mission, authority, outputs, escalation — the human contract
  runbooks/<dept>.md      how work actually gets done here, step by step
  skills/*.md             procedural knowledge injected into every lane prompt
  tools/*.py              stdlib-only Python tools, each with tools/test_<name>.py
  templates/*             the document skeletons the department produces
  checklists/*.md         the checks a reviewer runs on this department's output
```

`engctl dept <dir>` validates a kit. It must report `OK` before the kit is installed.

## profile.yaml

```yaml
department: research                 # must equal the directory name
name: Research
mission: >
  Two to four sentences. What this department exists to produce, for whom.
default_depth: 3                     # engine depth 1-5 when an agent does not set one
agents:                              # the Paperclip agents that sit in this department
  - name: research-1                 # exact Paperclip agent name
    depth: 2                         # engine depth for this agent's tasks
    focus: quick lookups, comparisons, landscape scans
  - name: research-2
    depth: 4
    focus: decision memos, first-principles analysis, pre-mortems
output_kind: memo                    # memo | code | design | drafts | tracker | checklist | report | mixed
work_root: /home/ubuntu/aaryas-life/departments/research/work
may:                                 # authority, one line each
  - research, analyse and recommend
never:                               # hard prohibitions, one line each
  - execute the plans it recommends
constraints:                         # extra rules appended to every task spec of this department
  - Every factual claim carries a source URL or a file:line, or is marked INFERENCE.
skills:                              # relative paths; each injected into lane prompts (>= 400 bytes)
  - skills/source-hierarchy.md
  - skills/memo-format.md
tools:                               # relative paths; each needs tools/test_<stem>.py
  - path: tools/cite_check.py
    usage: python3 {dept}/tools/cite_check.py <memo.md>
    purpose: fails if a memo has uncited claims or no Sources section
acceptance_templates:                # become engine-run gates on matching deliverables
  - name: cited
    applies_to: "*.md"               # glob on the deliverable's file name
    cmd: python3 {dept}/tools/cite_check.py {deliverable}
lane_policy:
  web: true                          # may read-only lanes fetch web pages? research: yes; most: no
escalate_when:
  - the question turns on taste, money, relationships, or risk only the Owner can decide
hands_to:
  - to: engineering
    when: a recommendation needs building
```

Placeholders: `{dept}` becomes the department directory, `{deliverable}` the path of
the deliverable being checked, `{work_root}` the work root.

## Rules for every kit

1. **Free models only.** Nothing in a kit may call, name, or route to a paid model.
2. **Tools are Python 3 standard library only** (PyYAML is available). No pip, no
   network calls unless the department's profile has `web: true` and the tool is a
   read-only fetch. No tool reads `~/.config`, `.env` files, or `~/.ssh`. No tool sends
   email, messages, or posts — `smtplib` and `sendmail` are rejected by the validator.
3. **Every tool has tests** in `tools/test_<stem>.py` using `unittest`, runnable with
   `python3 -m unittest discover -s tools -p 'test_*.py'`. Tests use temp dirs and
   never touch live data.
4. **Tools must exit non-zero on failure** with a one-line reason on stderr, so the
   engine can use them as gates. Every tool supports `--help`.
5. **Skills are procedural, not inspirational.** A skill says how to do the thing:
   steps, formats, worked examples, the mistakes to avoid and why. Specific to this
   company (Code.SCRIET, SCRIET/CCSU Meerut, Lakshya, the IITM BS programme) where that
   is true. No generic advice a model already knows.
6. **Ground everything in what exists.** Read the department's current files on the VM
   first. Existing scripts run by cron must keep working unchanged: new tools go in
   `tools/`, never on top of an existing script.
7. **Writing voice** for any human-facing copy: plain, specific, human. No hype, no
   decorative symbols or emojis. The site is always written in full as
   `https://codescriet.dev`.
