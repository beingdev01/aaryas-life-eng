"""Stages: recon, plan, red-team, build, review, integrate.

Depth here is structural. Each stage is small enough for a free model to finish
inside its limits, and each one is followed by a check the engine performs itself.
Quality comes from the number of verified passes and from independent lanes
disagreeing with each other, not from one long heroic run.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import lanes as lanes_mod
from . import util
from .spec import TaskSpec, to_brief

CONTEXT_BUDGET = 14000     # chars of context pack handed to any one lane
DIGEST_BUDGET = 2600       # chars per recon digest


# --------------------------------------------------------------------------- recon

def _slice_sources(sources: list, n: int) -> list[list[str]]:
    if not sources:
        return []
    buckets: list[list[str]] = [[] for _ in range(max(1, min(n, len(sources))))]
    for i, src in enumerate(sources):
        buckets[i % len(buckets)].append(str(src))
    return buckets


def _tree_outline(paths: list, max_lines: int = 70) -> str:
    """A cheap factual outline so the lane does not burn its window exploring."""
    out = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            try:
                out.append(f"{p}  ({p.stat().st_size}B)")
            except OSError:
                out.append(f"{p}  (unreadable)")
        elif p.is_dir():
            out.append(f"{p}/")
            kids = sorted(p.rglob("*"))
            for k in kids:
                if len(out) >= max_lines:
                    out.append(f"  ... {len(kids)} entries total under {p}")
                    return "\n".join(out)
                if ".git" in k.parts or "node_modules" in k.parts:
                    continue
                try:
                    out.append(f"  {k.relative_to(p)}"
                               + (f"  ({k.stat().st_size}B)" if k.is_file() else "/"))
                except (OSError, ValueError):
                    continue
        else:
            out.append(f"{p}  (MISSING)")
    return "\n".join(out[:max_lines])


RECON_PROMPT = """You are a reconnaissance lane. Your only job is to read and report facts.

{brief}

## Your assigned slice
{sources}

## Factual outline already gathered for you
```
{outline}
```

## Questions this task needs answered
{questions}

## Instructions
Read the files in your slice. Use `read` and `bash` (rg, sed -n, ls, wc) to inspect
them. Do NOT modify anything. Do NOT write any file.

Then reply with a digest under {budget} characters, in this exact shape:

### FACTS
- Concrete, checkable statements, each with `path:line` or a command output.

### RELEVANT
- The specific files, symbols, or config a builder will need, and why.

### CONSTRAINTS
- Anything that limits a solution: existing contracts, conventions, dependencies,
  permissions, things that would break.

### UNKNOWNS
- What you could not determine, and the exact command or file that would settle it.

Report only what you verified. If you did not read it, say so under UNKNOWNS.
Never invent a path, a line number, or an output."""


def run_recon(spec: TaskSpec, lane_pool: list, health: dict, ledger,
              max_parallel: int, timeout_sec: int) -> tuple[str, list]:
    """Parallel recon lanes, each on its own slice, merged into one context pack."""
    profile = spec.profile
    buckets = _slice_sources(spec.context_sources, profile["recon_slices"])
    brief = to_brief(spec)
    questions = "\n".join(f"- {q}" for q in spec.context_questions) or "- (none stated)"

    if not buckets:
        pack = f"{brief}\n## Context\nNo context sources were declared for this task.\n"
        util.write_text(ledger.dir / "context" / "CONTEXT_PACK.md", pack)
        ledger.stage_done("recon", slices=0, pack_bytes=len(pack))
        return pack, []

    chosen = lanes_mod.pick(lane_pool, health, "recon", count=len(buckets),
                            needs_web=spec.web)
    if not chosen:
        raise RuntimeError("no live lane available for recon")
    fell_back = set(lanes_mod.web_fallback_used()) if spec.web else set()
    if fell_back:
        ledger.event("warning", stage="recon",
                     message=("this department requires web sources but no live "
                              "web-capable recon lane was available; these slices "
                              "cannot fetch and their digests must be treated as "
                              "unverified"),
                     lanes=sorted(fell_back))

    jobs = []
    for i, bucket in enumerate(buckets):
        lane = chosen[i % len(chosen)]
        prompt = RECON_PROMPT.format(
            brief=brief, sources="\n".join(f"- {s}" for s in bucket),
            outline=util.clip(_tree_outline(bucket), 3000),
            questions=questions, budget=DIGEST_BUDGET,
        )
        jobs.append((f"slice{i + 1}", lane, prompt, bucket))

    def one(job):
        slug, lane, prompt, bucket = job
        res = lanes_mod.invoke(lane, prompt, ledger.dir / "context" / slug,
                               timeout_sec, title=f"recon-{slug}", mode="ro", web=spec.web)
        ledger.record_lane_call("recon", slug, prompt, res)
        return slug, lane, bucket, res

    results = []
    with ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
        results = list(pool.map(one, jobs))

    sections = [brief, "## Context pack", ""]
    digests = []
    for slug, lane, bucket, res in results:
        header = (f"### {slug} — lane {res.lane_id} ({res.model}) — "
                  f"{res.verdict}, {res.elapsed_sec}s\nSources: {', '.join(bucket)}")
        if res.ok and res.text.strip():
            body = util.clip(res.text.strip(), DIGEST_BUDGET)
            digests.append({"slice": slug, "lane": res.lane_id, "ok": True})
        else:
            body = (f"(no digest: {res.verdict}. A builder must treat this slice as "
                    f"unexamined.)")
            digests.append({"slice": slug, "lane": res.lane_id, "ok": False,
                            "verdict": res.verdict})
        sections += [header, "", body, ""]

    pack = util.clip("\n".join(sections), CONTEXT_BUDGET * 2)
    pack_bytes = util.write_text(ledger.dir / "context" / "CONTEXT_PACK.md", pack)
    ledger.stage_done("recon", slices=len(buckets),
                      ok_slices=sum(1 for d in digests if d["ok"]),
                      pack_bytes=pack_bytes, digests=digests)
    return pack, digests


# ---------------------------------------------------------------------------- plan

PLAN_PROMPT = """You are the planning lane. You decompose work; you do not build it.

{brief}

## Context pack (gathered by recon lanes — treat it as the known state)
{pack}

## Instructions
Produce a plan that several independent builders could execute in PARALLEL without
coordinating with each other. That constraint drives everything below.

Rules the plan must obey:
1. Every part must be completable by one worker in one sitting, with no dependency
   on another part's internals — only on its declared outputs.
2. No two parts may own the same file. File ownership must be exclusive.
3. Every part needs a frozen contract: exactly what it produces, at what path, and
   the command that proves it works.
4. If the task cannot be split, say so and produce a single part.
5. If the goal is too vague to plan, set "blocked" with the question you need answered.

Reply with ONLY a JSON object, no prose before or after, in this shape:

{{
  "summary": "two sentences on the approach",
  "risks": ["what is most likely to go wrong"],
  "blocked": null,
  "parts": [
    {{
      "id": "short-slug",
      "title": "what this part does",
      "owns_files": ["exact paths this part alone may write"],
      "depends_on": ["ids of parts whose outputs this needs, or empty"],
      "contract": "precise description of the expected output",
      "deliverables": [{{"path": "...", "min_bytes": 1}}],
      "verify_cmd": "a shell command that exits 0 only if this part succeeded",
      "difficulty": "low|medium|high",
      "notes": "anything the builder must not get wrong"
    }}
  ]
}}

## How to write verify_cmd so it actually runs
It is executed with `bash -lc`. Keep it simple and valid:
- Good: `cd <dir> && python3 -m unittest test_foo -v`
- Good: `cd <dir> && python3 -c "import solution; print(solution.f(2))"`
- Good: `cd <dir> && python3 check.py`  (ask the builder to write check.py)
- BAD: a `python3 -c` one-liner containing `for`, `while`, `try`, `if` or `def`
  separated by semicolons. That is a Python SyntaxError. Compound statements need
  real newlines, so put them in a file the builder writes, and run that file.
If a check needs loops or branches, have the part deliver a test file and run it with
unittest. A check that cannot parse is discarded and the part is judged without it."""

REDTEAM_PROMPT = """You are the red team. Attack this plan before anyone builds it.

{brief}

## Context pack
{pack}

## The proposed plan
```json
{plan}
```

## Instructions
Spec defects are the single largest cause of failed builds, so be specific and harsh.
Find:
- Parts that overlap on files, or hidden ordering dependencies declared as parallel.
- Contracts vague enough that two builders would produce incompatible output.
- verify_cmd values that would pass without the work actually being done.
- Missing parts: work the goal requires that no part covers.
- Anything that would breach the stated constraints.

Reply with ONLY a JSON object:

{{
  "verdict": "APPROVE" or "REVISE",
  "findings": [
    {{"severity": "critical|high|medium|low",
      "part": "part id or 'plan'",
      "problem": "what is wrong",
      "fix": "the concrete change to make"}}
  ]
}}"""


def _parse_json_reply(text: str) -> dict | None:
    """Models wrap JSON in prose or fences. Recover the object."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = []
    if fence:
        candidates.append(fence.group(1))
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None


def run_plan(spec: TaskSpec, lane_pool: list, health: dict, ledger,
             pack: str, timeout_sec: int) -> dict:
    """Plan, then red-team the plan, then revise once. Returns the plan dict."""
    brief = to_brief(spec)
    clipped_pack = util.clip(pack, CONTEXT_BUDGET)

    if spec.parts:      # caller froze the parts; skip planning entirely
        plan = {"summary": "Parts were frozen in the task spec.", "risks": [],
                "blocked": None, "parts": spec.parts, "source": "spec"}
        util.write_json(ledger.dir / "PLAN.json", plan)
        ledger.stage_done("plan", parts=len(plan["parts"]), source="spec")
        return plan

    planner = lanes_mod.pick(lane_pool, health, "plan", count=1, needs_web=spec.web)
    if not planner:
        raise RuntimeError("no live lane available for planning")
    planner = planner[0]

    prompt = PLAN_PROMPT.format(brief=brief, pack=clipped_pack)
    res = lanes_mod.invoke(planner, prompt, ledger.dir / "parts",
                           timeout_sec, title="plan", mode="ro", web=spec.web)
    ledger.record_lane_call("plan", "v1", prompt, res)
    plan = _parse_json_reply(res.text)
    if not plan:
        raise RuntimeError(f"planner {planner.id} returned no usable JSON "
                           f"(verdict={res.verdict}, {len(res.text)} chars)")

    if plan.get("blocked"):
        util.write_json(ledger.dir / "PLAN.json", plan)
        ledger.stage_done("plan", blocked=str(plan["blocked"])[:400])
        return plan

    # Red team, then one revision pass.
    if spec.profile["redteam"]:
        critic = lanes_mod.pick(lane_pool, health, "redteam", count=1,
                                exclude_families={planner.family})
        critic = critic[0] if critic else None
        if critic:
            rt_prompt = REDTEAM_PROMPT.format(
                brief=brief, pack=clipped_pack,
                plan=json.dumps(plan, indent=2)[:9000])
            rt = lanes_mod.invoke(critic, rt_prompt, ledger.dir / "parts",
                                  timeout_sec, title="redteam", mode="ro", web=spec.web)
            ledger.record_lane_call("plan", "redteam", rt_prompt, rt)
            critique = _parse_json_reply(rt.text) or {}
            util.write_json(ledger.dir / "PLAN_CRITIQUE.json", critique)

            serious = [f for f in critique.get("findings", [])
                       if str(f.get("severity", "")).lower() in ("critical", "high")]
            if critique.get("verdict") == "REVISE" and serious:
                rev_prompt = (
                    f"{prompt}\n\n## A red team reviewed your previous plan\n"
                    f"```json\n{json.dumps(plan, indent=2)[:6000]}\n```\n\n"
                    f"## Findings you must fix\n"
                    f"```json\n{json.dumps(serious, indent=2)[:4000]}\n```\n\n"
                    "Produce the corrected plan as a single JSON object, same shape. "
                    "Fix every finding. Do not restate the findings."
                )
                rev = lanes_mod.invoke(planner, rev_prompt, ledger.dir / "parts",
                                       timeout_sec, title="plan-v2", mode="ro", web=spec.web)
                ledger.record_lane_call("plan", "v2", rev_prompt, rev)
                revised = _parse_json_reply(rev.text)
                if revised and revised.get("parts"):
                    revised["revised_after_redteam"] = True
                    revised["addressed_findings"] = len(serious)
                    plan = revised

    parts = plan.get("parts") or []
    if not parts:
        raise RuntimeError("plan contains no parts")

    # Structural validation the engine enforces, whatever the model claimed.
    owners: dict[str, str] = {}
    conflicts = []
    for part in parts:
        for f in part.get("owns_files", []) or []:
            if f in owners and owners[f] != part.get("id"):
                conflicts.append(f"{f} claimed by both {owners[f]} and {part.get('id')}")
            owners[f] = part.get("id")
    plan["file_conflicts"] = conflicts
    util.write_json(ledger.dir / "PLAN.json", plan)
    ledger.stage_done("plan", parts=len(parts), conflicts=len(conflicts),
                      revised=bool(plan.get("revised_after_redteam")))
    return plan
