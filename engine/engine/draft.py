"""The front door: turn any plain-English request into a validated task spec.

The intake gate refuses work whose completion cannot be checked mechanically. That is
correct, but it would make the engine useless for "any task I give" if every request
had to arrive as hand-written YAML. This module closes that gap. A reasoning lane drafts
the spec, a lane from a different family attacks its checkability, and the engine's own
intake gate is the final judge. The engine never runs a draft that it would refuse.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

from . import lanes as lanes_mod
from . import spec as spec_mod
from . import util
from .stages import _parse_json_reply

WORK_ROOT = Path(os.environ.get(
    "ENG_WORK_ROOT", str(util.HOME / "organisation-rebuild/departments/engineering/work")))

ALWAYS_BANNED = [
    "/home/ubuntu/.ssh",
    "/home/ubuntu/.config",
    "/home/ubuntu/aaryas-life/agents",
    "/home/ubuntu/aaryas-life/bin",
    "/home/ubuntu/clubsite",
]

SCHEMA_GUIDE = """A task spec is a JSON object with these fields:

- "title": short, specific, human-readable. Avoid the words max, heavy, complex,
  architecture (they trigger paid model escalation in this company's older runners).
- "goal": 3-8 sentences. The outcome wanted, who it is for, and how it will be judged.
- "depth": integer 1-5. 1 = trivial single-file change. 3 = normal multi-part work.
  5 = the hardest, highest-stakes work (most recon, sampling and review).
- "deliverables": list of {"path": ABSOLUTE path, "min_bytes": int, "description": str}.
  Every path must be inside the workdir given below. min_bytes must be a realistic
  floor for a finished file, not 1.
- "acceptance": list of {"name": str, "cmd": shell command, "expect_exit": 0,
  "expect_stdout": optional substring}. These run on the VM, by the engine, after the
  work. They must FAIL if the work was not really done. A command that only checks a
  file exists is too weak when a stronger check is possible: compile it, run its
  tests, run it, parse its output, grep for required content.
- "context_sources": list of ABSOLUTE paths (files or directories) that a builder must
  read. Only paths that actually exist. Prefer specific files over huge directories.
- "context_questions": list of the questions the builders need answered first.
- "authorized_paths": list of ABSOLUTE paths the work may write to (normally just the
  workdir).
- "banned_paths": list of ABSOLUTE paths that must never be touched.
- "constraints": list of task-specific rules beyond the defaults (never send, never
  deploy, never read credentials — those are added automatically).

If the request cannot become a checkable task — it is a question of taste, money,
relationships, or needs the Owner's decision — return {"blocked": "<the exact question
the Owner must answer>"} instead of a spec."""

DRAFT_PROMPT = """You are the intake lane of the {dept_name} department. You turn a
request into a precise, checkable task spec. You do not do the task.

## The request
{request}

## Workdir for this task's outputs
{workdir}

{department}

## Environment facts
- Ubuntu VM, Python 3.14 with PyYAML, git 2.53, node, ffmpeg, pdftoppm, headless Chrome
  under ~/.cache/puppeteer. No pip installs allowed.
- Company scaffold: /home/ubuntu/aaryas-life (agents/, departments/, bin/, state/).
- Live club website repo (reference only, never edited by a task unless the request
  explicitly says so): /home/ubuntu/clubsite-git
- You may explore the filesystem READ-ONLY (read, list, glob, grep tools) to find real
  context_sources and to make acceptance commands accurate. Never open credential
  files, .env files, or anything under ~/.config or ~/.ssh.

## Spec format
{schema}

## Instructions
1. Explore just enough to ground the spec in real paths.
2. Prefer this department's own tools as acceptance commands where they fit — they
   are listed above with their usage. Their gates are also added automatically to
   matching deliverables, so do not duplicate those exact checks.
3. Reply with ONLY the JSON object. No prose before or after it."""

CHECKABILITY_PROMPT = """You are auditing a draft task spec before any work starts.
The question is not whether the task is worthwhile. It is whether the spec's checks
would catch a fake or lazy result.

## The original request
{request}

## The draft spec
```json
{spec}
```

## Find
- Acceptance commands that would pass even if the real work were not done (for
  example only testing that a file exists, or grepping for a word the builder could
  simply write).
- Deliverables whose min_bytes is unrealistically low.
- Parts of the request that no deliverable or check covers.
- context_sources that look invented or irrelevant.
- Anything that would require sending, deploying, spending, or touching credentials.

Reply with ONLY a JSON object:
{{"verdict": "APPROVE" or "REVISE",
  "findings": [{{"severity": "critical|high|medium|low", "field": "...",
                 "problem": "...", "fix": "the exact replacement value or command"}}]}}"""

REPAIR_PROMPT = """Your previous draft spec needs correcting before it can be used.

## The original request
{request}

## Your previous draft
```json
{spec}
```

## What must be fixed
{problems}

Apply every fix. Keep everything that was already right. Reply with ONLY the corrected
JSON object."""


def fetch_issue(issue_id: str) -> tuple[str, str]:
    proc = subprocess.run(["bash", "-lc", f"paperclipai issue get {issue_id} --json"],
                          capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(f"could not read issue {issue_id}: "
                           f"{util.redact(proc.stderr[-300:])}")
    data = json.loads(proc.stdout)
    title = data.get("title") or ""
    body = data.get("description") or ""
    return title, f"Board issue {data.get('identifier', issue_id)}: {title}\n\n{body}"


def _normalise(draft: dict, workdir: Path, request: str, profile=None,
               depth: int | None = None) -> dict:
    """Engine-side corrections a model should not be trusted to get right."""
    out = dict(draft)
    out["title"] = str(out.get("title", "")).strip()[:120]
    out.setdefault("id", util.slugify(out["title"] or request[:40]))
    banned = list(out.get("banned_paths") or [])
    for path in ALWAYS_BANNED:
        if path not in banned:
            banned.append(path)
    out["banned_paths"] = banned
    authorized = list(out.get("authorized_paths") or [])
    if str(workdir) not in authorized:
        authorized.insert(0, str(workdir))
    out["authorized_paths"] = authorized
    sources = []
    for src in out.get("context_sources") or []:
        if Path(str(src)).exists():
            sources.append(str(src))
    out["context_sources"] = sources
    if profile is not None:
        out["department"] = profile.department
    if depth is not None:
        out["depth"] = int(depth)
    out["drafted_from"] = request[:2000]
    return out


def _outside_workdir(draft: dict, workdir: Path) -> list[str]:
    bad = []
    for d in draft.get("deliverables") or []:
        path = str(d.get("path", ""))
        if not path.startswith(str(workdir)):
            bad.append(path)
    return bad


def draft_spec(request: str, lane_pool: list, health: dict, timeout_sec: int,
               slug_hint: str | None = None, workdir: Path | None = None,
               profile=None, depth: int | None = None) -> dict:
    """Draft, attack, repair, validate. Returns a dict with the spec or a block reason.

    `profile` is a departments.Profile. When given, the drafter writes in that
    department's terms, its work root becomes the default workdir, its tools become the
    preferred acceptance commands, and the spec is tagged so the engine loads the kit.
    """
    slug = util.slugify(slug_hint or request[:48])
    if workdir is None:
        workdir = (Path(profile.work_root) / slug) if profile is not None else WORK_ROOT / slug
    workdir = Path(workdir)
    log_dir = (Path(profile.work_root) if profile is not None else WORK_ROOT) / "_drafts" / slug
    log_dir.mkdir(parents=True, exist_ok=True)

    drafters = lanes_mod.pick(lane_pool, health, "plan", count=1)
    if not drafters:
        raise RuntimeError("no live lane available to draft a spec")
    drafter = drafters[0]

    dept_block = profile.brief_section() if profile is not None else ""
    if profile is not None and profile.acceptance_templates:
        dept_block += ("\n### Automatic gates for this department\n" + "\n".join(
            f"- on deliverables matching `{t.applies_to}`: `{profile.subst(t.cmd)}`"
            for t in profile.acceptance_templates))
    prompt = DRAFT_PROMPT.format(
        request=request, workdir=workdir, schema=SCHEMA_GUIDE,
        dept_name=profile.name if profile is not None else "Engineering",
        department=util.clip(dept_block, 12000))
    res = lanes_mod.invoke(drafter, prompt, log_dir, timeout_sec,
                           title=f"draft-{slug}", mode="ro")
    util.write_text(log_dir / "draft.v1.reply.md", res.text or "")
    draft = _parse_json_reply(res.text)
    if not draft:
        raise RuntimeError(f"drafter {drafter.id} returned no usable JSON ({res.verdict})")
    if draft.get("blocked"):
        return {"blocked": str(draft["blocked"]), "lane": drafter.id}

    history = [{"stage": "draft", "lane": drafter.id, "verdict": res.verdict,
                "elapsed_sec": res.elapsed_sec}]

    # Checkability red team from a different family.
    critics = lanes_mod.pick(lane_pool, health, "redteam", count=1,
                             exclude_families={drafter.family})
    problems: list[str] = []
    if critics:
        crit_prompt = CHECKABILITY_PROMPT.format(request=request,
                                                 spec=json.dumps(draft, indent=2)[:9000])
        crit = lanes_mod.invoke(critics[0], crit_prompt, log_dir, timeout_sec,
                                title=f"draft-check-{slug}", mode="ro")
        util.write_text(log_dir / "checkability.reply.md", crit.text or "")
        verdict = _parse_json_reply(crit.text) or {}
        history.append({"stage": "checkability", "lane": critics[0].id,
                        "verdict": verdict.get("verdict"), "elapsed_sec": crit.elapsed_sec})
        for f in verdict.get("findings") or []:
            if str(f.get("severity", "")).lower() in ("critical", "high"):
                problems.append(f"- [{f.get('severity')}] {f.get('field')}: "
                                f"{f.get('problem')} -> {f.get('fix')}")

    outside = _outside_workdir(draft, workdir)
    if outside:
        problems.append(f"- [critical] deliverables: these paths are outside the workdir "
                        f"{workdir}: {', '.join(outside)}. Move them inside it.")

    candidate = _normalise(draft, workdir, request, profile, depth)
    try:
        spec_mod.from_dict(candidate)
    except spec_mod.SpecError as exc:
        problems.append(f"- [critical] intake gate rejected the spec: {exc}")

    if problems:
        rep_prompt = REPAIR_PROMPT.format(request=request,
                                          spec=json.dumps(draft, indent=2)[:9000],
                                          problems="\n".join(problems)[:5000])
        rep = lanes_mod.invoke(drafter, rep_prompt, log_dir, timeout_sec,
                               title=f"draft-repair-{slug}", mode="ro")
        util.write_text(log_dir / "draft.v2.reply.md", rep.text or "")
        repaired = _parse_json_reply(rep.text)
        history.append({"stage": "repair", "lane": drafter.id, "verdict": rep.verdict,
                        "fixed": len(problems), "elapsed_sec": rep.elapsed_sec})
        if repaired and not repaired.get("blocked"):
            candidate = _normalise(repaired, workdir, request, profile, depth)

    # Final judge: the engine's own intake gate. A draft it would refuse is never saved
    # as runnable.
    still_outside = _outside_workdir(candidate, workdir)
    try:
        spec_mod.from_dict(candidate)
        if still_outside:
            raise spec_mod.SpecError("deliverables outside workdir: " + ", ".join(still_outside))
    except spec_mod.SpecError as exc:
        return {"rejected": str(exc), "candidate": candidate, "history": history,
                "log_dir": str(log_dir)}

    candidate["draft_history"] = history
    return {"spec": candidate, "history": history, "log_dir": str(log_dir),
            "workdir": str(workdir)}


def save_spec(spec: dict, specs_dir: Path) -> Path:
    specs_dir.mkdir(parents=True, exist_ok=True)
    path = specs_dir / f"{spec['id']}.yaml"
    body = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100)
    util.write_text(path, body)
    return path
