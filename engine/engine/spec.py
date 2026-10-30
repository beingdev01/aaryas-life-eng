"""Task spec: the frozen brief, and the intake gate that refuses vague work.

The charter already says a vague goal must come back BLOCKED rather than guessed at.
This module is where that becomes enforceable: a spec without a machine-checkable
acceptance condition cannot enter the pipeline, so "done" is never a model's opinion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import util

DEPTH_PROFILES = {
    1: dict(recon_slices=1, sample_k=1, review_rounds=0, redteam=False, fix_rounds=1),
    2: dict(recon_slices=2, sample_k=1, review_rounds=1, redteam=False, fix_rounds=1),
    3: dict(recon_slices=3, sample_k=1, review_rounds=1, redteam=True,  fix_rounds=2),
    4: dict(recon_slices=4, sample_k=2, review_rounds=2, redteam=True,  fix_rounds=2),
    5: dict(recon_slices=6, sample_k=3, review_rounds=2, redteam=True,  fix_rounds=2),
}


class SpecError(ValueError):
    pass


@dataclass
class Acceptance:
    """A machine-checked condition. The engine runs this itself."""
    cmd: str
    expect_exit: int = 0
    expect_stdout: str | None = None   # substring that must appear
    forbid_stdout: str | None = None   # substring that must not appear
    cwd: str | None = None
    timeout_sec: int = 300
    name: str = ""


@dataclass
class Deliverable:
    path: str
    min_bytes: int = 1
    description: str = ""


@dataclass
class TaskSpec:
    id: str
    title: str
    goal: str
    depth: int = 3
    acceptance: list = field(default_factory=list)
    deliverables: list = field(default_factory=list)
    context_sources: list = field(default_factory=list)
    context_questions: list = field(default_factory=list)
    authorized_paths: list = field(default_factory=list)
    banned_paths: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    parts: list = field(default_factory=list)       # optional pre-frozen parts
    board_issue: str | None = None
    max_parallel: int | None = None
    department: str | None = None
    web: bool = False
    dept: object = None                             # departments.Profile when set
    raw: dict = field(default_factory=dict)

    @property
    def profile(self) -> dict:
        """Depth settings (recon slices, sampling K, review rounds, ...)."""
        return DEPTH_PROFILES[self.depth]


DEFAULT_CONSTRAINTS = [
    "Never read, print, or log any credential, API key, token, password, or raw database URL.",
    "Never send an email, message, or public post. Never submit a form or application.",
    "Never deploy, restart, or modify a running service.",
    "Never write outside the workdir and authorized paths given to you.",
    "Never claim a file was written without writing it. Every claim must be checkable on disk.",
]


def load(path: str | Path) -> TaskSpec:
    path = Path(path)
    if not path.exists():
        raise SpecError(f"spec not found: {path}")
    text = path.read_text()
    data = yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else __import__("json").loads(text)
    if not isinstance(data, dict):
        raise SpecError("spec must be a mapping")
    return from_dict(data)


def from_dict(data: dict) -> TaskSpec:
    missing = [k for k in ("title", "goal") if not str(data.get(k, "")).strip()]
    if missing:
        raise SpecError(f"spec missing required field(s): {', '.join(missing)}")

    acceptance = [Acceptance(
        cmd=a["cmd"], expect_exit=int(a.get("expect_exit", 0)),
        expect_stdout=a.get("expect_stdout"), forbid_stdout=a.get("forbid_stdout"),
        cwd=a.get("cwd"), timeout_sec=int(a.get("timeout_sec", 300)),
        name=a.get("name") or f"check{i + 1}",
    ) for i, a in enumerate(data.get("acceptance", []) or []) if a.get("cmd")]

    deliverables = [Deliverable(
        path=str(d["path"]), min_bytes=int(d.get("min_bytes", 1)),
        description=d.get("description", ""),
    ) for d in data.get("deliverables", []) or [] if d.get("path")]

    # The intake gate. Without one of these, "done" would be a model's self-report.
    if not acceptance and not deliverables:
        raise SpecError(
            "spec has neither 'acceptance' commands nor 'deliverables'. The engine "
            "refuses work whose completion cannot be checked mechanically. Add at "
            "least one deliverable path or one acceptance command."
        )

    depth = int(data.get("depth", 3))
    if depth not in DEPTH_PROFILES:
        raise SpecError(f"depth must be one of {sorted(DEPTH_PROFILES)}, got {depth}")

    # A department kit, when named, contributes its constraints, its own tools as
    # engine-run gates on matching deliverables, its web policy, and the brief block.
    dept_profile = None
    department = data.get("department")
    if department:
        from . import departments as dept_mod
        try:
            dept_profile = dept_mod.find(str(department))
        except (dept_mod.ProfileError, OSError) as exc:
            raise SpecError(f"department '{department}' could not be loaded: {exc}") from exc
        existing = {a.name for a in acceptance}
        for chk in dept_profile.acceptance_for(
                [{"path": d.path} for d in deliverables]):
            if chk["name"] not in existing:
                acceptance.append(Acceptance(cmd=chk["cmd"], name=chk["name"],
                                             expect_exit=0, timeout_sec=300))

    spec = TaskSpec(
        id=util.slugify(data.get("id") or data["title"]),
        title=str(data["title"]).strip(),
        goal=str(data["goal"]).strip(),
        depth=depth,
        acceptance=acceptance,
        deliverables=deliverables,
        context_sources=list(data.get("context_sources", []) or []),
        context_questions=list(data.get("context_questions", []) or []),
        authorized_paths=list(data.get("authorized_paths", []) or []),
        banned_paths=list(data.get("banned_paths", []) or []),
        constraints=(DEFAULT_CONSTRAINTS + list(data.get("constraints", []) or [])
                     + (list(dept_profile.constraints) if dept_profile else [])),
        parts=list(data.get("parts", []) or []),
        board_issue=data.get("board_issue"),
        max_parallel=data.get("max_parallel"),
        department=str(department) if department else None,
        web=bool(dept_profile.web) if dept_profile else bool(data.get("web", False)),
        dept=dept_profile,
        raw=data,
    )

    if len(spec.goal) < 40:
        raise SpecError(
            "goal is too thin to plan against (under 40 characters). State what "
            "outcome is wanted and how it will be judged."
        )
    return spec


def to_brief(spec: TaskSpec) -> str:
    """The frozen brief text injected into every lane prompt for this task."""
    lines = [f"# Task: {spec.title}", "", "## Goal", spec.goal, ""]
    if spec.dept is not None:
        lines += [spec.dept.brief_section(), ""]
    if spec.deliverables:
        lines += ["## Required deliverables (must exist on disk)"]
        lines += [f"- `{d.path}` (min {d.min_bytes} bytes)"
                  + (f" — {d.description}" if d.description else "")
                  for d in spec.deliverables]
        lines.append("")
    if spec.acceptance:
        lines += ["## Acceptance checks (the engine runs these itself, not you)"]
        lines += [f"- {a.name}: `{a.cmd}` (expect exit {a.expect_exit})"
                  for a in spec.acceptance]
        lines.append("")
    if spec.authorized_paths:
        lines += ["## Authorized paths", *[f"- {p}" for p in spec.authorized_paths], ""]
    if spec.banned_paths:
        lines += ["## Banned paths (never touch)", *[f"- {p}" for p in spec.banned_paths], ""]
    lines += ["## Hard constraints", *[f"- {c}" for c in spec.constraints], ""]
    return "\n".join(lines)
