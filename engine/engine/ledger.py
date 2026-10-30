"""Run ledger: the audit trail that makes a zero-output run impossible to miss.

Every run gets a directory. Every lane call, gate result and stage transition is
appended to ledger.jsonl with its exit code, elapsed time and artifact paths. Raw
prompts and raw replies are stored on disk, so any claim in a report can be traced
back to the exact text that produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import util


@dataclass
class Receipt:
    """A receipt is a file on disk with a path, a size and a gate verdict.

    The charter's rule is "receipts or it didn't happen". Here that is mechanical:
    a stage cannot be marked done unless its declared artifacts exist and are
    non-trivial, so a succeeded run with nothing on disk fails instead of passing.
    """
    path: str
    bytes: int
    exists: bool
    min_bytes: int = 1

    @property
    def ok(self) -> bool:
        return self.exists and self.bytes >= self.min_bytes


class Ledger:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        for sub in ("lanes", "context", "parts", "review", "delivery", "gates"):
            (self.dir / sub).mkdir(exist_ok=True)
        self.path = self.dir / "ledger.jsonl"

    def event(self, kind: str, **fields) -> dict:
        rec = {"at": util.utc_now(), "kind": kind, **fields}
        with self.path.open("a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec

    def events(self, kind: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if kind is None or rec.get("kind") == kind:
                out.append(rec)
        return out

    # ---- lane call persistence ----

    def record_lane_call(self, stage: str, slug: str, prompt: str, result) -> dict:
        """Persist prompt, reply and raw event stream verbatim, then log the metadata."""
        # Path.with_suffix would treat ".<lane_id>" as a suffix and drop it, so the
        # stem is built by string concatenation.
        stem = str(self.dir / "lanes" / f"{stage}.{slug}.{result.lane_id}")
        prompt_path = Path(stem + ".prompt.md")
        reply_path = Path(stem + ".reply.md")
        p_bytes = util.write_text(prompt_path, prompt)
        r_bytes = util.write_text(reply_path, result.text or "")
        if getattr(result, "raw_events", ""):
            util.write_text(Path(stem + ".events.jsonl"), result.raw_events)
        if result.stderr_tail or getattr(result, "error_signals", ""):
            util.write_text(Path(stem + ".stderr.txt"),
                            f"{result.stderr_tail}\n--- error events ---\n"
                            f"{getattr(result, 'error_signals', '')}")
        return self.event(
            "lane_call", stage=stage, slug=slug, lane=result.lane_id,
            model=result.model, verdict=result.verdict, exit_code=result.exit_code,
            elapsed_sec=result.elapsed_sec, tools=result.tools,
            tool_errors=getattr(result, "tool_errors", 0),
            cost=getattr(result, "cost", 0.0), steps=getattr(result, "steps", 0),
            ended_by=getattr(result, "ended_by", ""), mode=getattr(result, "mode", ""),
            slot_wait_sec=getattr(result, "slot_wait_sec", 0.0),
            sensitive=getattr(result, "sensitive", []),
            model_keys=getattr(result, "model_keys", []),
            reply_bytes=r_bytes, prompt_bytes=p_bytes,
            prompt_path=str(prompt_path), reply_path=str(reply_path),
        )

    # ---- stage state, so a run can resume instead of restarting ----

    def stage_done(self, stage: str, **fields) -> dict:
        return self.event("stage_done", stage=stage, **fields)

    def is_stage_done(self, stage: str) -> bool:
        return any(e.get("stage") == stage for e in self.events("stage_done"))

    def stage_result(self, stage: str) -> dict | None:
        for rec in reversed(self.events("stage_done")):
            if rec.get("stage") == stage:
                return rec
        return None

    # ---- receipts ----

    def check_receipts(self, declared: list[dict]) -> tuple[bool, list[Receipt]]:
        receipts = []
        for item in declared:
            path = Path(item["path"])
            min_bytes = int(item.get("min_bytes", 1))
            exists = path.exists() and path.is_file()
            size = path.stat().st_size if exists else 0
            receipts.append(Receipt(str(path), size, exists, min_bytes))
        return all(r.ok for r in receipts), receipts

    def sensitive_access(self) -> list[dict]:
        """Every tool call that touched a credential-looking path, completed or not."""
        hits = []
        for call in self.events("lane_call"):
            for hit in call.get("sensitive") or []:
                hits.append({"stage": call.get("stage"), "slug": call.get("slug"),
                             "lane": call.get("lane"), **hit})
        return hits

    def summary(self) -> dict:
        calls = self.events("lane_call")
        gates = self.events("gate")
        by_verdict: dict[str, int] = {}
        for call in calls:
            v = call.get("verdict", "?")
            by_verdict[v] = by_verdict.get(v, 0) + 1
        return {
            "lane_calls": len(calls),
            "lane_seconds": round(sum(c.get("elapsed_sec", 0) for c in calls), 1),
            "total_cost": round(sum(float(c.get("cost") or 0) for c in calls), 6),
            "sensitive_access": self.sensitive_access(),
            "verdicts": by_verdict,
            "gates_run": len(gates),
            "gates_passed": sum(1 for g in gates if g.get("passed")),
            "stages_done": [e.get("stage") for e in self.events("stage_done")],
        }
