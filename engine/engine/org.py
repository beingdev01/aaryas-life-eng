"""CEO routing layer: one task in, a department chain out, receipts verified.

The organisation's rule is that a task reaches the CEO, the CEO decides which department
owns it and which agent inside that department is best placed, the work is dispatched on
Paperclip where the agents execute it, and the CEO verifies receipts on disk before the
chain is called done. This module is that decision process, made deterministic and
auditable instead of vibes-based.

Routing is rule-scored first and only asks a model lane when two departments are within
a whisker of each other, because a routing decision has to be reproducible: the same
task must reach the same department tomorrow, and a lane cannot be blamed for a coin
flip it was never asked to settle.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from . import departments as dept_mod
from . import guard
from . import util

COMPANY_ID = util.COMPANY_ID
ORG_ROOT = util.HOME / "state" / "org"
MAX_SUPPORTS = 2          # charter: max 3 handoffs per chain, this task plus two
TIE_MARGIN = 0.35         # below this, the top two departments are a genuine toss-up

STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are",
    "be", "this", "that", "it", "as", "at", "by", "from", "we", "you", "your", "my",
    "please", "make", "get", "put", "can", "do", "does", "should", "need", "want",
    "have", "has", "will", "not", "but", "if", "then", "them", "they", "their", "there",
    "into", "about", "after", "before", "when", "who", "what", "how", "all", "any",
}

KIND_TERMS = {
    "memo": ["memo", "report", "findings", "survey", "comparison", "analysis", "options"],
    "code": ["code", "module", "function", "script", "build", "fix", "refactor", "test"],
    "design": ["design", "poster", "visual", "layout", "graphic", "asset", "render",
               "video", "invitation", "certificate"],
    "drafts": ["draft", "message", "email", "note", "reply", "announcement", "follow-up"],
    "tracker": ["tracker", "deadline", "pipeline", "status", "application", "prospect"],
    "checklist": ["checklist", "runbook", "plan", "steps", "sheet"],
    "report": ["report", "audit", "review", "summary", "receipt"],
    "mixed": ["work", "task"],
}

# Per-field weights. What the agent actually says it does (focus) and what it is
# forbidden to do (never) are stronger signals than the marketing text in a mission.
FIELD_WEIGHTS = {"routes": 8.0, "focus": 4.0, "may": 3.0, "output_kind": 2.5,
                 "skills": 2.0, "runbook": 1.5, "constraints": 1.2, "mission": 1.0}


def tokenize(text: str) -> list:
    words = re.split(r"[^a-z0-9]+", (text or "").lower())
    out = []
    for w in words:
        if len(w) < 3 or w in STOP:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 4:
                w = w[: -len(suffix)]
                break
        out.append(w)
    return out


class RoutingError(RuntimeError):
    pass


class Org:
    def __init__(self, departments_root: Path | str, company_id: str = COMPANY_ID):
        self.root = Path(departments_root)
        self.company_id = company_id
        self._profiles: dict[str, dept_mod.Profile] = {}
        self._broken: dict[str, str] = {}
        self._roster: dict[str, dict] = {}
        self._signals: dict[str, dict] = {}

    # ---- kits ----

    def profiles(self) -> dict:
        if not self._profiles and not self._broken:
            for path in sorted(self.root.glob("*/profile.yaml")):
                try:
                    prof = dept_mod.load(path.parent)
                    self._profiles[prof.department] = prof
                except (dept_mod.ProfileError, OSError, KeyError, TypeError) as exc:
                    self._broken[path.parent.name] = str(exc)
        return self._profiles

    def kit_problems(self) -> dict:
        self.profiles()
        return dict(self._broken)

    def signals(self, dept: str) -> dict:
        """Term weights for one department, harvested from its own kit."""
        if dept in self._signals:
            return self._signals[dept]
        prof = self.profiles()[dept]
        terms: dict[str, float] = {}

        def add(words, weight):
            # Kits are hand-authored YAML: a field documented as a list of strings can
            # still contain a mapping. Route on its text, do not crash on it.
            joined = " ".join(w if isinstance(w, str)
                              else json.dumps(w, default=str) for w in words)
            for tok in tokenize(joined):
                terms[tok] = max(terms.get(tok, 0.0), weight)

        raw = prof.raw or {}
        routes = raw.get("routes") or {}
        if isinstance(routes, dict):
            add([str(x) for x in (routes.get("include") or [])], FIELD_WEIGHTS["routes"])
        add([str(a.get("focus", "")) for a in prof.agents if isinstance(a, dict)],
            FIELD_WEIGHTS["focus"])
        add(prof.may, FIELD_WEIGHTS["may"])
        add(KIND_TERMS.get(prof.output_kind, []), FIELD_WEIGHTS["output_kind"])
        add([Path(s).stem.replace("-", " ") for s in prof.skills], FIELD_WEIGHTS["skills"])
        runbook = prof.dir / "runbooks" / f"{prof.department}.md"
        if runbook.exists():
            heads = re.findall(r"^##\s+(.+)$", runbook.read_text(errors="replace"), re.M)
            add(heads, FIELD_WEIGHTS["runbook"])
        add(prof.constraints, FIELD_WEIGHTS["constraints"])
        add([prof.mission], FIELD_WEIGHTS["mission"])

        self._signals[dept] = {"terms": terms, "scale": max(1.0, len(terms) ** 0.5)}
        return self._signals[dept]

    # ---- classification ----

    def classify(self, text: str) -> list:
        toks = set(tokenize(text))
        if not toks:
            raise RoutingError("the task has no words I can route on")
        scored = []
        for dept in self.profiles():
            sig = self.signals(dept)
            hits = [(t, w) for t, w in sig["terms"].items() if t in toks]
            raw = sum(w for _, w in hits) / sig["scale"]
            scored.append({"department": dept, "score": round(raw, 3),
                           "matched": sorted(hits, key=lambda h: -h[1])[:6]})
        scored.sort(key=lambda s: -s["score"])
        return scored

    def plan(self, text: str, department: str | None = None,
             depth: int | None = None) -> dict:
        """Decide the chain: owning department, best agent, support hops, verifier."""
        table = self.classify(text)
        if department:
            chosen = next((s for s in table if s["department"] == department), None)
            if not chosen:
                raise RoutingError(f"no kit for department '{department}' under {self.root}")
            rationale = [f"department pinned by the caller: {department}"]
        else:
            top = table[0]
            second = table[1] if len(table) > 1 else {"department": None, "score": 0.0}
            margin = round(top["score"] - second["score"], 3)
            if top["score"] <= 0:
                raise RoutingError(
                    "no department's kit claims this task; it needs a new department or "
                    "an owner decision, not a guess")
            chosen = top
            rationale = [f"{top['department']} scored {top['score']} on "
                         f"{', '.join(t for t, _ in top['matched'][:4]) or 'mission terms'}",
                         f"runner-up {second['department']} at {second['score']} "
                         f"(margin {margin})"]
            if margin < TIE_MARGIN:
                rationale.append("margin below the tie threshold: routed to the top "
                                 "score, escalate if the work clearly spans both")

        prof = self.profiles()[chosen["department"]]
        agent = self.pick_agent(prof, text)
        supports = self.supports_for(prof, text)
        workdir = util.HOME / "organisation-rebuild" / "work" / "org" / util.slugify(text[:48])
        return {
            "task": text.strip(),
            "department": prof.department,
            "output_kind": prof.output_kind,
            "web": bool(prof.web),
            "confidence": chosen["score"],
            "alternates": [{"department": s["department"], "score": s["score"]}
                           for s in self.classify(text)[:4]],
            "agent": agent,
            "depth": int(depth or prof.agent_depth(agent.get("name"))),
            "supports": supports,
            "verifier": "CEO",
            "workdir": str(workdir),
            "rationale": rationale,
            "constraints": list(prof.constraints),
            "escalate_when": list(prof.escalate_when),
            "never": list(prof.never),
        }

    def pick_agent(self, prof, text: str) -> dict:
        """Within a department, the agent whose declared focus matches best."""
        toks = set(tokenize(text))
        best, best_hits = None, -1
        for entry in prof.agents:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            focus = set(tokenize(str(entry.get("focus", ""))))
            hits = len(focus & toks)
            if hits > best_hits:
                best, best_hits = entry, hits
        entry = best or (prof.agents[0] if prof.agents else {})
        name = str(entry.get("name") or "")
        return {"name": name, "id": self.agent_id(name),
                "depth": int(entry.get("depth", prof.default_depth)),
                "focus": str(entry.get("focus", "")),
                "match_strength": max(0, best_hits)}

    def supports_for(self, prof, text: str) -> list:
        """Extra departments this task touches, read from the kit's own hands_to."""
        toks = set(tokenize(text))
        out = []
        for hop in prof.hands_to or []:
            if not isinstance(hop, dict):
                continue
            when = str(hop.get("when", ""))
            hits = sorted(set(tokenize(when)) & toks)
            if len(hits) >= 2:
                target = str(hop.get("to", "")).strip().lower()
                tp = self.profiles().get(target)
                out.append({"department": target,
                            "agent": (self.pick_agent(tp, text) if tp else None),
                            "reason": when, "matched": hits})
        out.sort(key=lambda h: -len(h["matched"]))
        return out[:MAX_SUPPORTS]

    # ---- Paperclip roster ----

    def roster(self, force: bool = False) -> dict:
        cache = ORG_ROOT / "roster.json"
        if not force and cache.exists():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if time.time() - float(data.get("at", 0)) < 600:
                    self._roster = data.get("agents", {})
                    return self._roster
            except (ValueError, OSError, TypeError):
                pass
        proc = self._cli("agent", "list", "--company-id", self.company_id)
        agents = {}
        if proc.returncode == 0:
            for m in re.finditer(r"id=(\S+)\s+name=(\S+)\s+status=(\S+)", proc.stdout):
                agents[m.group(2)] = {"id": m.group(1), "status": m.group(3)}
        ORG_ROOT.mkdir(parents=True, exist_ok=True)
        util.write_json(cache, {"at": time.time(), "agents": agents})
        self._roster = agents
        return agents

    def agent_id(self, name: str) -> str:
        return (self.roster().get(name) or {}).get("id", "")

    # ---- dispatch ----

    def chain_description(self, plan: dict) -> str:
        lines = ["## CEO routing decision", f"**Task:** {plan['task'][:600]}", "",
                 f"**Owning department:** {plan['department']} "
                 f"(confidence {plan['confidence']})",
                 f"**Best agent:** {plan['agent']['name'] or '(none)'}",
                 f"**Depth:** {plan['depth']}  **Output kind:** {plan['output_kind']}  "
                 f"**Web needed:** {plan['web']}", "", "### Why"]
        lines += [f"- {r}" for r in plan["rationale"]]
        if plan["supports"]:
            lines += ["", "### Support hops (max 3 handoffs per chain)"]
            for s in plan["supports"]:
                who = (s.get("agent") or {}).get("name", "?")
                lines.append(f"- {s['department']} ({who}) because: {s['reason']}")
        else:
            lines += ["", "### Support hops", "- none: no other department's routing "
                      "terms matched this task"]
        lines += ["", f"**Verifier:** {plan['verifier']} - receipts are checked on disk "
                  "before this chain is called done", "", "### Department constraints"]
        lines += [f"- {c}" for c in plan["constraints"][:6]]
        lines += ["", "### Must never happen", *[f"- {n}" for n in plan["never"][:6]]]
        return "\n".join(lines)

    def child_task(self, plan: dict, hop: dict) -> str:
        return (f"Handoff from the CEO routing layer for: {plan['task'][:400]}\n\n"
                f"Why you have this: {hop['reason']}\n"
                f"Matched on: {', '.join(hop['matched'])}\n\n"
                f"Do only this part and leave a receipt file on disk, then end with "
                f"RESULT: DONE naming the exact path.")

    def dispatch(self, plan: dict, dry_run: bool = True) -> dict:
        """Create the parent issue and one child per hop on Paperclip."""
        title = guard.sanitize_title(f"[org] {plan['task'][:70]}")
        description = self.chain_description(plan)
        result = {"plan": plan, "dry_run": dry_run, "parent": None, "children": []}
        if dry_run:
            result["would_create"] = [{"title": title, "assignee": None}]
            for hop in plan["supports"]:
                who = (hop.get("agent") or {}).get("id", "")
                result["would_create"].append(
                    {"title": guard.sanitize_title(f"[org] {hop['department']}: "
                                                   f"{hop['reason'][:40]}"),
                     "assignee": who})
            return result

        proc = self._cli("issue", "create", "--company-id", self.company_id,
                         "--title", title, "--description", description,
                         "--status", "todo", "--priority", "high")
        parent = self._issue_id(proc.stdout)
        if proc.returncode != 0 or not parent:
            raise RoutingError(f"could not create the parent issue: "
                               f"{proc.stdout[-300:]}{proc.stderr[-300:]}")
        result["parent"] = parent
        owner = plan["agent"].get("id", "")
        if owner:
            payload = {"title": guard.sanitize_title(
                f"[org] {plan['department']} deliverable: {plan['task'][:40]}"),
                "description": self.chain_description(plan), "priority": "high",
                "assigneeAgentId": owner, "status": "todo"}
            kid = self._child(parent, payload)
            if kid:
                result["children"].append({"department": plan["department"],
                                           "agent": plan["agent"]["name"], "issue": kid})
        for hop in plan["supports"]:
            who = (hop.get("agent") or {}).get("id", "")
            if not who:
                continue
            payload = {"title": guard.sanitize_title(
                f"[org] {hop['department']}: {hop['reason'][:40]}"),
                "description": self.child_task(plan, hop), "priority": "medium",
                "assigneeAgentId": who, "status": "todo"}
            kid = self._child(parent, payload)
            if kid:
                result["children"].append({"department": hop["department"],
                                           "agent": (hop.get("agent") or {}).get("name"),
                                           "issue": kid})
        util.write_json(ORG_ROOT / f"{parent}.json", {
            "at": time.time(), "parent": parent, "plan_task": plan["task"],
            "department": plan["department"], "children": result["children"]})
        return result

    def _child(self, parent: str, payload: dict) -> str:
        proc = self._cli("issue", "child:create", parent,
                         "--payload-json", json.dumps(payload))
        return self._issue_id(proc.stdout) if proc.returncode == 0 else ""

    @staticmethod
    def _issue_id(stdout: str) -> str:
        m = re.search(r"\bid[=\s:]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                      r"[0-9a-f]{4}-[0-9a-f]{12})", stdout)
        if m:
            return m.group(1)
        m = re.search(r"\b([A-Z]{2,10}-\d+)\b", stdout)
        return m.group(1) if m else ""

    # ---- verification ----

    def status(self, issue: str) -> dict:
        proc = self._cli("issue", "get", issue, "--company-id", self.company_id)
        if proc.returncode != 0:
            return {"issue": issue, "ok": False, "detail": proc.stderr[-200:]}
        out = proc.stdout
        status = (re.search(r"\bstatus[=\s:]+(\w+)", out) or [None, "unknown"])[1]
        return {"issue": issue, "ok": True, "status": status, "detail": out[:400]}

    def verify(self, dispatch_result: dict, minimum_bytes: int = 120) -> dict:
        """Receipts or it did not happen: every child must point at a real file."""
        checks, problems = [], []
        for kid in dispatch_result.get("children", []) or []:
            st = self.status(kid["issue"])
            paths = re.findall(r"(/[^\s'\"]+\.(?:md|py|json|png|mp4|html|csv|txt))",
                               st.get("detail", ""))
            found = [p for p in paths if Path(p).is_file()
                     and Path(p).stat().st_size >= minimum_bytes]
            checks.append({"issue": kid["issue"], "department": kid["department"],
                           "status": st.get("status"), "receipts": found})
            if st.get("status") not in ("done", "completed", "closed"):
                problems.append(f"{kid['issue']} ({kid['department']}) is "
                                f"{st.get('status')}, not done")
            if not found:
                problems.append(f"{kid['issue']} ({kid['department']}) names no file on "
                                f"disk - a heartbeat is not a receipt")
        return {"verified": not problems, "checks": checks, "problems": problems}

    # ---- cli plumbing ----

    @staticmethod
    def _cli(*args) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "-lc", "paperclipai " + " ".join(
            f"'{a.replace(chr(39), chr(39) + chr(39) * 2 + chr(39))}'" for a in args)],
            capture_output=True, text=True, timeout=120)


def summary(dispatch_result: dict) -> str:
    plan = dispatch_result["plan"]
    lines = [f"task      : {plan['task'][:90]}",
             f"department: {plan['department']} (confidence {plan['confidence']})",
             f"agent     : {plan['agent']['name'] or '(unmapped)'} "
             f"@ depth {plan['depth']}",
             f"supports  : {', '.join(s['department'] for s in plan['supports']) or 'none'}",
             f"dry run   : {dispatch_result['dry_run']}"]
    if dispatch_result.get("parent"):
        lines.append(f"parent    : {dispatch_result['parent']}")
    for kid in dispatch_result.get("children", []) or []:
        lines.append(f"  child   : {kid['issue']} -> {kid['department']} "
                     f"({kid['agent']})")
    return "\n".join(lines)
