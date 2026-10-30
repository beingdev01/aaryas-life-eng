"""Department profiles: how one shared engine becomes nine specialised departments.

A department is not a different program. It is a profile the engine loads:

- what the department is for and what it may never do,
- the skills (procedural knowledge) injected into every lane prompt for its tasks,
- the tools it owns (stdlib Python scripts with tests) that lanes may call,
- acceptance templates, so the department's own tools become engine-run gates,
- a lane policy (for example, research may browse the web; nobody else may).

The engine stays the single execution substrate. The profile makes a research task
come out as a cited memo, a design task as a rendered preview, an outreach task as an
unsent draft — each checked by that department's own tools, not by a model's opinion.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import util

DEPARTMENTS_ROOT = Path(os.environ.get(
    "ENG_DEPARTMENTS", str(util.HOME / "departments")))

OUTPUT_KINDS = {"memo", "code", "design", "drafts", "tracker", "checklist", "report", "mixed"}
REQUIRED = ("department", "name", "mission", "agents", "output_kind", "work_root",
            "may", "never", "skills")
SKILL_BUDGET = 9000          # chars of skill text injected into one prompt
MIN_SKILL_BYTES = 400

# What a department tool may never touch. `\.env\b` matches ".env" files but not
# os.environ, which an earlier substring check wrongly rejected.
FORBIDDEN_IN_TOOLS = (
    ("~/.config or /.config/ paths", r"\.config/"),
    (".env files", r"\.env\b"),
    ("~/.ssh", r"/\.ssh\b"),
    ("smtplib", r"\bsmtplib\b"),
    ("sendmail", r"\bsendmail\b"),
)


class ProfileError(ValueError):
    pass


@dataclass
class Tool:
    path: str
    usage: str
    purpose: str


@dataclass
class AcceptanceTemplate:
    name: str
    cmd: str
    applies_to: str = "*"


@dataclass
class Profile:
    department: str
    name: str
    mission: str
    agents: list
    output_kind: str
    work_root: str
    may: list
    never: list
    skills: list
    dir: Path
    constraints: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    acceptance_templates: list = field(default_factory=list)
    web: bool = False
    escalate_when: list = field(default_factory=list)
    hands_to: list = field(default_factory=list)
    default_depth: int = 3
    raw: dict = field(default_factory=dict)

    def subst(self, text: str, **extra) -> str:
        out = text.replace("{dept}", str(self.dir)).replace("{work_root}", self.work_root)
        for key, val in extra.items():
            out = out.replace("{" + key + "}", str(val))
        return out

    def agent_depth(self, agent_name: str | None) -> int:
        for agent in self.agents:
            if isinstance(agent, dict) and agent.get("name") == agent_name:
                return int(agent.get("depth", self.default_depth))
        return self.default_depth

    def skill_text(self, budget: int = SKILL_BUDGET) -> str:
        chunks, used = [], 0
        for rel in self.skills:
            path = self.dir / rel
            try:
                body = path.read_text(errors="replace").strip()
            except OSError:
                continue
            room = budget - used
            if room <= 200:
                chunks.append(f"(further skills omitted for length: {rel} ...)")
                break
            body = util.clip(body, room)
            chunks.append(f"### Skill: {rel}\n{body}")
            used += len(body)
        return "\n\n".join(chunks)

    def brief_section(self) -> str:
        """The department block injected into every lane prompt for this department."""
        lines = [f"## Department: {self.name}", self.mission.strip(), "",
                 "### This department may", *[f"- {m}" for m in self.may], "",
                 "### This department must never", *[f"- {n}" for n in self.never], ""]
        if self.tools:
            lines += ["### Department tools you may run (read their --help first)"]
            for tool in self.tools:
                lines.append(f"- `{self.subst(tool.usage)}` — {tool.purpose}")
            lines.append("")
        skills = self.skill_text()
        if skills:
            lines += ["### Department skills (follow these)", skills, ""]
        return "\n".join(lines)

    def acceptance_for(self, deliverables: list) -> list[dict]:
        """Expand templates against the spec's deliverables into concrete checks."""
        checks = []
        for tpl in self.acceptance_templates:
            for d in deliverables:
                path = d["path"] if isinstance(d, dict) else str(d)
                if fnmatch.fnmatch(Path(path).name, tpl.applies_to):
                    checks.append({
                        "name": f"dept:{tpl.name}:{Path(path).name}",
                        "cmd": self.subst(tpl.cmd, deliverable=path),
                        "expect_exit": 0,
                    })
        return checks


def load(dept_dir: Path) -> Profile:
    dept_dir = Path(dept_dir)
    path = dept_dir / "profile.yaml"
    if not path.exists():
        raise ProfileError(f"no profile.yaml in {dept_dir}")
    data = yaml.safe_load(path.read_text()) or {}
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise ProfileError(f"{path}: missing required field(s): {', '.join(missing)}")
    if data["output_kind"] not in OUTPUT_KINDS:
        raise ProfileError(f"{path}: output_kind must be one of {sorted(OUTPUT_KINDS)}")

    tools = [Tool(t["path"], t.get("usage", t["path"]), t.get("purpose", ""))
             for t in data.get("tools") or [] if t.get("path")]
    templates = [AcceptanceTemplate(t["name"], t["cmd"], t.get("applies_to", "*"))
                 for t in data.get("acceptance_templates") or []
                 if t.get("name") and t.get("cmd")]
    lane_policy = data.get("lane_policy") or {}

    return Profile(
        department=str(data["department"]), name=str(data["name"]),
        mission=str(data["mission"]), agents=list(data["agents"]),
        output_kind=data["output_kind"], work_root=str(data["work_root"]),
        may=list(data["may"]), never=list(data["never"]), skills=list(data["skills"]),
        dir=dept_dir.resolve(), constraints=list(data.get("constraints") or []),
        tools=tools, acceptance_templates=templates, web=bool(lane_policy.get("web")),
        escalate_when=list(data.get("escalate_when") or []),
        hands_to=list(data.get("hands_to") or []),
        default_depth=int(data.get("default_depth", 3)), raw=data,
    )


def find(department: str, root: Path | None = None) -> Profile:
    root = Path(root or DEPARTMENTS_ROOT)
    return load(root / department)


def for_agent(agent_name: str, root: Path | None = None) -> Profile | None:
    """Which department does a Paperclip agent sit in?"""
    root = Path(root or DEPARTMENTS_ROOT)
    if not root.is_dir():
        return None
    for prof_path in sorted(root.glob("*/profile.yaml")):
        try:
            prof = load(prof_path.parent)
        except ProfileError:
            continue
        for agent in prof.agents:
            name = agent.get("name") if isinstance(agent, dict) else str(agent)
            if name == agent_name:
                return prof
    return None


def validate(dept_dir: Path, run_tool_tests: bool = True) -> list[str]:
    """Return a list of problems. Empty list means the department kit is sound."""
    problems: list[str] = []
    dept_dir = Path(dept_dir)
    try:
        prof = load(dept_dir)
    except ProfileError as exc:
        return [str(exc)]

    if prof.department != dept_dir.name:
        problems.append(f"department '{prof.department}' does not match directory "
                        f"name '{dept_dir.name}'")

    for rel in ("CHARTER.md", f"runbooks/{prof.department}.md"):
        p = dept_dir / rel
        if not p.exists():
            problems.append(f"missing {rel}")
        elif p.stat().st_size < 1200:
            problems.append(f"{rel} is only {p.stat().st_size} bytes; too thin to be usable")

    if len(prof.skills) < 2:
        problems.append("a department needs at least 2 skills")
    for rel in prof.skills:
        p = dept_dir / rel
        if not p.exists():
            problems.append(f"skill missing: {rel}")
        elif p.stat().st_size < MIN_SKILL_BYTES:
            problems.append(f"skill {rel} is only {p.stat().st_size} bytes")

    for agent in prof.agents:
        if not isinstance(agent, dict) or not agent.get("name"):
            problems.append(f"agent entry must be a mapping with a name: {agent!r}")
        elif not 1 <= int(agent.get("depth", prof.default_depth)) <= 5:
            problems.append(f"agent {agent['name']} depth must be 1-5")

    tool_dirs = set()
    for tool in prof.tools:
        p = dept_dir / tool.path
        if not p.exists():
            problems.append(f"tool missing: {tool.path}")
            continue
        try:
            subprocess.run(["python3", "-m", "py_compile", str(p)], check=True,
                           capture_output=True, timeout=60)
        except subprocess.CalledProcessError as exc:
            problems.append(f"tool {tool.path} does not compile: "
                            f"{exc.stderr.decode(errors='replace')[-300:]}")
        test = p.parent / f"test_{p.stem}.py"
        if not test.exists():
            problems.append(f"tool {tool.path} has no test file test_{p.stem}.py")
        tool_dirs.add(p.parent)
        body = p.read_text(errors="replace")
        for label, pattern in FORBIDDEN_IN_TOOLS:
            if re.search(pattern, body):
                problems.append(f"tool {tool.path} references forbidden {label}")

    if run_tool_tests:
        for tdir in sorted(tool_dirs):
            proc = subprocess.run(["python3", "-m", "unittest", "discover", "-s", str(tdir),
                                   "-p", "test_*.py"],
                                  capture_output=True, text=True, timeout=300, cwd=str(tdir))
            if proc.returncode != 0:
                problems.append(f"tool tests failed in {tdir}: {proc.stderr[-600:]}")

    for tpl in prof.acceptance_templates:
        if "{deliverable}" not in tpl.cmd:
            problems.append(f"acceptance template {tpl.name} never references {{deliverable}}")

    return problems
