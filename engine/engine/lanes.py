"""Lane pool: health probing, bounded invocation, and VM-wide resource control.

Facts from live runs on 2026-10-30 that shape this module:

1. A quota-exhausted lane does not error, it HANGS, and even healthy lanes often keep
   running after they have finished. So output is streamed: the final `step_finish`
   with reason "stop" ends the call, a long silence ends the call, and a hard timeout
   is the last resort. The whole process group is always reaped.
2. A dead lane can look healthy, so health is probed per run, and a lane that gets
   rate-limited mid-run is cooled down and routed around for the rest of the run.
3. Both CLIs emit the same event stream. `text` parts are the model's words; tool
   output (which includes the contents of files the lane read) is never mistaken for
   them. `step_finish` carries a `cost` field, checked on every call as runtime proof
   that nothing was billed.
4. Without `--auto`, any command outside the workdir is auto-rejected and the run
   aborts. With `--auto` plus a project-level permission file, explicit denies hold in
   both CLIs (verified live). So every call runs with `--auto` and a mode-specific
   permission file: read-only lanes cannot write or run shell; builder lanes can build
   but cannot sudo, restart services, push, or reach Paperclip.
5. Several engine runs can be active at once (one per Paperclip seat). A VM-wide
   semaphore caps total lane processes so the server's live services are never starved.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import guard, offers, util

CLI_PATHS = {
    "kilo": os.path.expanduser("~/.local/bin/kilo"),
    "opencode": os.path.expanduser("~/.opencode/bin/opencode"),
    "qodercli": os.path.expanduser("~/.local/bin/qodercli"),
}

# CLIs whose lanes cannot fetch a web page at all, whatever the department asks for.
CLI_WITHOUT_WEB = ("qodercli",)

PROBE_PROMPT = "Reply with the single word OK and nothing else."
PROBE_TOKEN = "OK"

STOP_GRACE_SEC = 8           # after the final "stop" event, wait this long, then end
DEFAULT_IDLE_SEC = 300       # no event for this long means the lane is hung
COOLDOWN_SEC = 600           # a rate-limited lane is avoided for this long

SLOTS_DIR = Path(os.environ.get("ENG_SLOTS_DIR", str(util.HOME / "state" / "lane-slots")))
HEALTH_CACHE = Path(os.environ.get("ENG_HEALTH_CACHE", str(util.HOME / "state" / "lane-health")))
DEFAULT_GLOBAL_SLOTS = int(os.environ.get("ENG_GLOBAL_SLOTS", "4"))
MIN_FREE_MB = int(os.environ.get("ENG_MIN_FREE_MB", "900"))
SLOT_WAIT_SEC = int(os.environ.get("ENG_SLOT_WAIT_SEC", "1800"))

_ERROR_SIGNATURES = (
    ("quota", ("free usage limit reached", "usage limit reached", "quota exceeded")),
    ("no_funds", ("insufficient account funds", "insufficient funds", "payment required")),
    ("rate_limited", ("rate limit", "ratelimit", "too many requests", "status code 429")),
    ("auth", ("not logged in", "unauthorized", "forbidden", "invalid api key")),
    ("no_model", ("unknown model", "model not found", "invalid model")),
)

READ_ONLY_DENY = "deny"

# Lanes run as the same Unix user as everything else, so a read tool could reach a
# credential file. Every tool input is scanned against these; any hit fails the run.
SENSITIVE_PATTERNS = [re.compile(p) for p in (
    r"/\.config/", r"/\.ssh(/|\b)", r"\.env\b", r"nvidia-nim", r"dispatch\.env",
    r"/proc/[^/\s]+/environ", r"/\.local/share/(kilo|opencode)/", r"\bauth\.json\b",
    r"/\.qoder(/|\b)", r"/\.paperclip/", r"id_(rsa|ed25519)", r"\.pem\b",
)]
BUILDER_BASH_DENY = [
    "sudo *", "su *", "doas *", "systemctl *", "service *", "caddy *", "xray *",
    "git push*", "git reset --hard*", "git clean*", "git checkout -- *",
    "ssh *", "scp *", "rsync *", "sftp *",
    "crontab *", "at *", "paperclipai *", "kill *", "pkill *", "killall *",
    "reboot*", "shutdown*", "halt*", "mkfs*", "dd *",
    "rm -rf /*", "rm -rf ~*", "rm -rf $HOME*", "chown *", "chmod -R *",
    "docker *", "npm publish*", "pip install*", "pip3 install*",
    "mail *", "sendmail *", "mutt *",
]


# ------------------------------------------------------------- paid-cost breaker

class _CostBreaker:
    """Trips on the first call that reports a non-zero cost, then refuses all calls."""

    def __init__(self):
        self._lock = threading.Lock()
        self.tripped_by: dict | None = None

    def record(self, lane_id: str, model: str, cost: float) -> None:
        if cost and cost > 0:
            with self._lock:
                if self.tripped_by is None:
                    self.tripped_by = {"lane": lane_id, "model": model, "cost": cost,
                                       "at": util.utc_now()}

    @property
    def tripped(self) -> bool:
        return self.tripped_by is not None

    def reset(self) -> None:
        with self._lock:
            self.tripped_by = None


COST_BREAKER = _CostBreaker()


# --------------------------------------------------------------- lane cooldowns

_COOLDOWN: dict[str, float] = {}
_COOLDOWN_LOCK = threading.Lock()


def cool_down(lane_id: str, seconds: int = COOLDOWN_SEC) -> None:
    with _COOLDOWN_LOCK:
        _COOLDOWN[lane_id] = time.monotonic() + seconds


def is_cooling(lane_id: str) -> bool:
    with _COOLDOWN_LOCK:
        until = _COOLDOWN.get(lane_id)
    return bool(until and until > time.monotonic())


def reset_cooldowns() -> None:
    with _COOLDOWN_LOCK:
        _COOLDOWN.clear()


# ---------------------------------------------------------------- child reaping

_LIVE_GROUPS: set[int] = set()
_LIVE_LOCK = threading.Lock()


def _track(pgid: int) -> None:
    with _LIVE_LOCK:
        _LIVE_GROUPS.add(pgid)


def _untrack(pgid: int) -> None:
    with _LIVE_LOCK:
        _LIVE_GROUPS.discard(pgid)


def reap_all_children() -> int:
    """Kill every lane process group this engine started. Safe to call repeatedly."""
    with _LIVE_LOCK:
        groups = list(_LIVE_GROUPS)
        _LIVE_GROUPS.clear()
    for pgid in groups:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                break
            time.sleep(0.5)
    return len(groups)


def _kill_group(pgid: int) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(1.5)


# ------------------------------------------------------ VM-wide lane semaphore

def mem_available_mb() -> int:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 1 << 20


class LaneSlot:
    """A flock-based counting semaphore shared by every engine process on the VM.

    Locks are held on open file descriptors, so a crashed engine releases its slots
    automatically. A slot is only taken when enough memory is free, because each lane
    process holds roughly 470 MB and this VM also runs production services.
    """

    def __init__(self, slots: int = DEFAULT_GLOBAL_SLOTS, wait_sec: int = SLOT_WAIT_SEC):
        self.slots = max(1, slots)
        self.wait_sec = wait_sec
        self.fd: int | None = None
        self.index: int | None = None
        self.waited_sec = 0.0

    def __enter__(self):
        SLOTS_DIR.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        while True:
            if mem_available_mb() >= MIN_FREE_MB:
                for i in range(self.slots):
                    path = SLOTS_DIR / f"slot-{i}.lock"
                    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o664)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        os.close(fd)
                        continue
                    os.ftruncate(fd, 0)
                    os.write(fd, f"{os.getpid()} {util.utc_now()}\n".encode())
                    self.fd, self.index = fd, i
                    self.waited_sec = round(time.monotonic() - started, 1)
                    return self
            if time.monotonic() - started > self.wait_sec:
                raise TimeoutError(f"no free lane slot within {self.wait_sec}s "
                                   f"({self.slots} slots, {mem_available_mb()} MB free)")
            time.sleep(2)

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                os.ftruncate(self.fd, 0)   # clear the holder so the file never looks stale
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
            self.fd = None
        return False


def slots_in_use(slots: int = DEFAULT_GLOBAL_SLOTS) -> int:
    used = 0
    SLOTS_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(slots):
        fd = os.open(SLOTS_DIR / f"slot-{i}.lock", os.O_RDWR | os.O_CREAT, 0o664)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            used += 1
        finally:
            os.close(fd)
    return used


# ------------------------------------------------------------------- data types

@dataclass
class Lane:
    id: str
    cli: str
    model: str
    family: str
    roles: list = field(default_factory=list)
    enabled: bool = True
    notes: str = ""
    variant: str | None = None
    readonly: bool = False
    # Can this lane actually open a web page? Set per lane in lanes.yaml (`web: false`),
    # defaulted by CLI: qodercli runs under --permission-mode dont_ask, which refuses
    # WebFetch (verified live 2026-10-31), so a qodercli lane can never be a source
    # lane. Routing a research source slice to a lane that cannot fetch produces
    # confidently invented URLs, which is the one thing research must never do.
    web: bool = True

    def supports(self, role: str) -> bool:
        return role in self.roles


BUILDER_ROLES = {"build", "fix", "integrate"}


@dataclass
class LaneResult:
    lane_id: str
    model: str
    verdict: str      # ok | empty | quota | no_funds | rate_limited | auth | no_model
                      # | hang | error | refused_paid | refused_mode | paid_cost_detected
                      # | unexpected_model | no_slot
    exit_code: int
    elapsed_sec: float
    text: str = ""
    tools: dict = field(default_factory=dict)
    tool_errors: int = 0
    cost: float = 0.0
    steps: int = 0
    ended_by: str = ""    # exit | stop_event | idle | timeout
    slot_wait_sec: float = 0.0
    mode: str = "ro"
    sensitive: list = field(default_factory=list)
    model_keys: list = field(default_factory=list)
    stderr_tail: str = ""
    error_signals: str = ""
    raw_events: str = ""
    cmd: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict == "ok"


# --------------------------------------------------------------- stream parsing

def _event_facts(ev: dict) -> dict:
    etype = ev.get("type")
    part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
    facts = {"type": etype, "text": None, "tool": None, "tool_error": False,
             "cost": 0.0, "stop": False, "error": None, "sensitive": None}
    if etype == "text":
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            facts["text"] = text
    elif etype == "tool_use":
        if isinstance(part.get("tool"), str):
            facts["tool"] = part["tool"]
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        facts["tool_error"] = state.get("status") == "error"
        inp = state.get("input") if isinstance(state.get("input"), dict) else {}
        blob = " ".join(str(v) for v in inp.values() if isinstance(v, (str, int, float)))
        if blob and any(p.search(blob) for p in SENSITIVE_PATTERNS):
            facts["sensitive"] = {"tool": part.get("tool"),
                                  "status": state.get("status"),
                                  "input": util.redact(blob)[:200]}
    elif etype == "step_finish":
        for holder in (part, ev):
            val = holder.get("cost")
            if isinstance(val, (int, float)):
                facts["cost"] = float(val)
                break
        facts["stop"] = part.get("reason") == "stop"
    elif etype == "error":
        facts["error"] = json.dumps(ev.get("error", part or ev))[:600]
    if etype != "error" and ev.get("error"):
        facts["error"] = json.dumps(ev.get("error"))[:600]
    return facts


def parse_events(stdout: str) -> dict:
    """Split the event stream into the model's words, tool activity, errors and cost."""
    texts, errors = [], []
    sensitive: list[dict] = []
    tools: dict[str, int] = {}
    tool_errors = steps = parsed = 0
    cost = 0.0
    stopped = False
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        parsed += 1
        f = _event_facts(ev)
        if f["text"]:
            texts.append(f["text"])
        if f["tool"]:
            tools[f["tool"]] = tools.get(f["tool"], 0) + 1
        if f["sensitive"]:
            sensitive.append(f["sensitive"])
        tool_errors += int(f["tool_error"])
        if f["type"] == "step_finish":
            steps += 1
            cost += f["cost"]
            stopped = stopped or f["stop"]
        if f["error"]:
            errors.append(f["error"])

    seen, unique = set(), []
    for chunk in texts:
        chunk = chunk.strip()
        if chunk not in seen:
            seen.add(chunk)
            unique.append(chunk)
    return {"text": "\n\n".join(unique), "tools": tools, "tool_errors": tool_errors,
            "errors": errors, "cost": cost, "steps": steps, "parsed": parsed,
            "stopped": stopped, "sensitive": sensitive}


def parse_qoder_events(stdout: str) -> dict:
    """qodercli emits stream-json in a different shape, with real billing fields.

    The `result` event carries total_credits, total_cost_usd and a modelUsage map keyed
    by the model actually served. That map is the strongest free-proof available: it
    shows what ran, not what was asked for.
    """
    texts: list[str] = []
    tools: dict[str, int] = {}
    errors: list[str] = []
    sensitive: list[dict] = []
    calls: dict[str, dict] = {}
    cost = 0.0
    model_keys: list[str] = []
    parsed = 0
    denied = 0

    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        parsed += 1
        etype = ev.get("type")
        if etype == "system" and ev.get("subtype") == "permission_denied":
            denied += 1
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        content = msg.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                kind = item.get("type")
                if kind == "text" and str(item.get("text", "")).strip():
                    texts.append(item["text"])
                elif kind == "tool_use":
                    name = str(item.get("name") or "?")
                    tools[name] = tools.get(name, 0) + 1
                    inp = item.get("input") if isinstance(item.get("input"), dict) else {}
                    blob = " ".join(str(v) for v in inp.values()
                                    if isinstance(v, (str, int, float)))
                    if blob and any(p.search(blob) for p in SENSITIVE_PATTERNS):
                        calls[str(item.get("id"))] = {
                            "tool": name, "status": "unknown",
                            "input": util.redact(blob)[:200]}
                elif kind == "tool_result":
                    if item.get("is_error"):
                        errors.append(str(item.get("content"))[:300])
                    cid = str(item.get("tool_use_id"))
                    if cid in calls:
                        calls[cid]["status"] = "denied" if item.get("is_error") else "completed"
        elif etype == "result":
            for field_name in ("total_credits", "total_cost_usd"):
                val = ev.get(field_name)
                if isinstance(val, (int, float)):
                    cost += float(val)
            usage = ev.get("modelUsage")
            if isinstance(usage, dict):
                model_keys = sorted(usage.keys())
                for entry in usage.values():
                    if isinstance(entry, dict):
                        for k in ("credits", "costUSD"):
                            v = entry.get(k)
                            if isinstance(v, (int, float)):
                                cost += float(v)
            if ev.get("is_error"):
                errors.append(str(ev.get("result"))[:300])
            elif str(ev.get("result", "")).strip() and not texts:
                texts.append(str(ev["result"]))

    sensitive = list(calls.values())
    seen, unique = set(), []
    for chunk in texts:
        chunk = chunk.strip()
        if chunk not in seen:
            seen.add(chunk)
            unique.append(chunk)
    return {"text": "\n\n".join(unique), "tools": tools, "tool_errors": denied,
            "errors": errors, "cost": cost, "steps": parsed, "parsed": parsed,
            "stopped": True, "sensitive": sensitive, "model_keys": model_keys}


def classify(rc: int, text: str, errors: list, stderr: str) -> str:
    """Verdict from exit status and error channels only — never from tool output."""
    signals = ("\n".join(errors) + "\n" + (stderr or "")).lower()

    def signature() -> str | None:
        for verdict, needles in _ERROR_SIGNATURES:
            if any(n in signals for n in needles):
                return verdict
        return None

    if rc == 0 and text.strip():
        return "ok"
    if rc == 124:
        return signature() or "hang"
    if rc != 0:
        return signature() or "error"
    return signature() or "empty"


# ------------------------------------------------------------ permission files

def permission_config(mode: str, web: bool) -> dict:
    if mode == "rw":
        return {"permission": {"edit": "allow",
                               "webfetch": "allow" if web else "deny",
                               "bash": {pattern: "deny" for pattern in BUILDER_BASH_DENY}}}
    return {"permission": {"edit": READ_ONLY_DENY, "bash": READ_ONLY_DENY,
                           "webfetch": "allow" if web else "deny"}}


def write_permission_files(workdir: Path, mode: str, web: bool) -> None:
    body = json.dumps(permission_config(mode, web), indent=2)
    for name in ("opencode.json", "kilo.json"):
        (Path(workdir) / name).write_text(body)


# ------------------------------------------------------------------ lane config

def load_lanes(path: Path | None = None) -> tuple[list[Lane], dict]:
    path = Path(path or util.LANES_FILE)
    data = yaml.safe_load(path.read_text()) or {}
    defaults = data.get("defaults", {}) or {}
    lanes = []
    for raw in data.get("lanes", []) or []:
        lanes.append(Lane(
            id=raw["id"], cli=raw["cli"], model=raw["model"],
            family=raw.get("family", "unknown"), roles=list(raw.get("roles", [])),
            enabled=bool(raw.get("enabled", True)), notes=raw.get("notes", ""),
            variant=raw.get("variant"), readonly=bool(raw.get("readonly", False)),
            web=bool(raw.get("web", raw["cli"] not in CLI_WITHOUT_WEB)),
        ))
    return lanes, defaults


def build_command(lane: Lane, exe: str, prompt: str, workdir: Path, mode: str,
                  title: str, nice: int, variant: str | None = None) -> list[str]:
    """The CLI-specific argv. qodercli has a different interface from the two forks."""
    if lane.cli == "qodercli":
        # dont_ask cannot grant approval, so every write and every read outside the
        # workdir is refused (verified live). stream-json exposes tool calls, so the
        # credential tripwire sees them the same way it does for the other CLIs.
        return ["nice", "-n", str(nice), exe, "-p", prompt, "-m", lane.model,
                "-w", str(workdir), "-o", "stream-json",
                "--permission-mode", "dont_ask",
                "--disallowed-tools", "Read(/home/ubuntu/.config/**)",
                "Read(/home/ubuntu/.ssh/**)", "Read(/home/ubuntu/.qoder/**)",
                "Read(/home/ubuntu/.paperclip/**)"]
    cmd = ["nice", "-n", str(nice), exe, "run", "--format", "json",
           # --title avoids OpenCode's paid gpt-5.4-nano title call; sanitised because
           # older runners escalate tier on certain title keywords.
           "--title", guard.sanitize_title(title),
           "--dir", str(workdir), "-m", lane.model, "--auto"]
    eff_variant = variant or lane.variant
    if eff_variant:
        cmd += ["--variant", eff_variant]
    cmd.append(prompt)
    return cmd


# -------------------------------------------------------------------- invocation

def invoke(lane: Lane, prompt: str, workdir: Path, timeout_sec: int,
           title: str = "eng", mode: str = "ro", web: bool = False, nice: int = 19,
           variant: str | None = None, idle_sec: int = DEFAULT_IDLE_SEC,
           global_slots: int = DEFAULT_GLOBAL_SLOTS, auto: bool | None = None) -> LaneResult:
    """Run one lane. Bounded, reaped, never spends, never raises on model failure.

    `auto` is accepted for backwards compatibility: True means mode="rw".
    """
    if auto is True:
        mode = "rw"
    if COST_BREAKER.tripped:
        return LaneResult(lane.id, lane.model, "refused_paid", 125, 0.0, mode=mode,
                          stderr_tail=("cost breaker tripped earlier in this run: "
                                       + json.dumps(COST_BREAKER.tripped_by)))
    free, why = guard.is_free_lane(lane)
    var_ok, var_why = guard.check_variant(variant or lane.variant)
    if not free or not var_ok:
        return LaneResult(lane.id, lane.model, "refused_paid", 125, 0.0, mode=mode,
                          stderr_tail=f"refused: {why if not free else var_why}")
    if lane.readonly and mode != "ro":
        return LaneResult(lane.id, lane.model, "refused_mode", 125, 0.0, mode=mode,
                          stderr_tail=f"lane {lane.id} is read-only and cannot take a "
                                      f"{mode!r} stage")
    exe = CLI_PATHS.get(lane.cli)
    if not exe or not os.path.exists(exe):
        return LaneResult(lane.id, lane.model, "error", 127, 0.0, mode=mode,
                          stderr_tail=f"cli not found: {lane.cli}")

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if lane.cli != "qodercli":
        write_permission_files(workdir, mode, web)

    cmd = build_command(lane, exe, prompt, workdir, mode, title, nice, variant)

    env = dict(os.environ)
    env["PATH"] = (f"{os.path.expanduser('~/.local/bin')}:"
                   f"{os.path.expanduser('~/.opencode/bin')}:{env.get('PATH', '')}")
    for secret_var in ("PAPERCLIP_API_KEY", "PAPERCLIP_AGENT_JWT", "NVIDIA_NIM_API_KEY"):
        env.pop(secret_var, None)   # lanes never inherit platform credentials

    try:
        slot = LaneSlot(global_slots).__enter__()
    except TimeoutError as exc:
        return LaneResult(lane.id, lane.model, "no_slot", 75, 0.0, mode=mode,
                          stderr_tail=str(exc))

    started = time.monotonic()
    lines: list[str] = []
    state = {"last": time.monotonic(), "stopped": False, "stop_at": None}
    stderr_file = tempfile.TemporaryFile(mode="w+", errors="replace")
    ended_by = "exit"
    try:
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(workdir), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=stderr_file, text=True, errors="replace",
                start_new_session=True)
        except OSError as exc:
            return LaneResult(lane.id, lane.model, "error", 126, 0.0, mode=mode,
                              stderr_tail=str(exc))
        pgid = proc.pid
        _track(pgid)

        def reader():
            for line in proc.stdout:
                lines.append(line)
                state["last"] = time.monotonic()
                s = line.strip()
                if s.startswith("{") and '"step_finish"' in s:
                    try:
                        if _event_facts(json.loads(s))["stop"]:
                            state["stopped"] = True
                            state["stop_at"] = time.monotonic()
                    except ValueError:
                        pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        try:
            while proc.poll() is None:
                now = time.monotonic()
                if state["stopped"] and now - state["last"] >= STOP_GRACE_SEC:
                    ended_by = "stop_event"
                    break
                if now - state["last"] >= idle_sec:
                    ended_by = "idle"
                    break
                if now - started >= timeout_sec:
                    ended_by = "timeout"
                    break
                time.sleep(0.5)
        finally:
            if proc.poll() is None:
                _kill_group(pgid)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            t.join(timeout=10)
            _untrack(pgid)
            if proc.stdout:
                proc.stdout.close()
        stderr_file.seek(0)
        stderr = stderr_file.read()
    finally:
        stderr_file.close()
        slot.__exit__(None, None, None)

    elapsed = time.monotonic() - started
    stdout = "".join(lines)
    if ended_by == "stop_event":
        rc = 0
    elif ended_by in ("idle", "timeout"):
        rc = 124
    else:
        rc = proc.returncode if proc.returncode is not None else -1

    if lane.cli == "qodercli":
        ev = parse_qoder_events(stdout)
        expected = offers.runtime_model_keys(f"qodercli:{lane.model}")
        if ev["model_keys"] and expected and not set(ev["model_keys"]) <= expected:
            ev["errors"].append(
                f"unexpected model served: {ev['model_keys']} not within {sorted(expected)}")
    else:
        ev = parse_events(stdout)
        ev["model_keys"] = []
    text = ev["text"] if ev["parsed"] else stdout.strip()
    verdict = classify(rc, text, ev["errors"], stderr)

    COST_BREAKER.record(lane.id, lane.model, ev["cost"])
    if ev["cost"] > 0:
        verdict = "paid_cost_detected"
    elif lane.cli == "qodercli" and ev["model_keys"]:
        expected = offers.runtime_model_keys(f"qodercli:{lane.model}")
        if expected and not set(ev["model_keys"]) <= expected:
            verdict = "unexpected_model"
            COST_BREAKER.record(lane.id, lane.model, 0.0000001)
    if verdict in ("rate_limited", "quota"):
        cool_down(lane.id)

    return LaneResult(
        lane_id=lane.id, model=lane.model, verdict=verdict, exit_code=rc,
        elapsed_sec=round(elapsed, 1), text=util.redact(text), tools=ev["tools"],
        tool_errors=ev["tool_errors"], cost=ev["cost"], steps=ev["steps"],
        ended_by=ended_by, slot_wait_sec=slot.waited_sec, mode=mode,
        sensitive=ev.get("sensitive", []), model_keys=ev.get("model_keys", []),
        stderr_tail=util.redact(stderr[-1200:] if stderr else ""),
        error_signals=util.redact("\n".join(ev["errors"])[:1500]),
        raw_events=util.redact(util.clip(stdout, 120000)),
        cmd=" ".join(cmd[:-1]) + " <prompt>",
    )


# ------------------------------------------------------------------------ probe

def probe(lanes: list[Lane], timeout_sec: int = 90, max_parallel: int = 3,
          workdir: Path | None = None, cache_sec: int = 900) -> dict:
    """Probe every enabled lane with a trivial prompt. Returns a health report.

    Results are cached for a short window, keyed by the exact set of lanes. Probing 20
    lanes costs minutes when several are quota-dead, and a staged rollout runs many
    times in a row, so re-probing every time would dominate the run.
    """
    targets = [ln for ln in lanes if ln.enabled]
    signature = hashlib.sha256(
        "|".join(sorted(f"{ln.cli}:{ln.model}" for ln in targets)).encode()).hexdigest()[:16]
    cache_path = HEALTH_CACHE / f"{signature}.json"
    if cache_sec > 0:
        cached = util.read_json(cache_path)
        if cached and (time.time() - float(cached.get("cached_at", 0))) < cache_sec:
            # Honour cooldowns even on a cache hit. If every live lane is cooling, the
            # honest answer is "nothing available right now", not an immediate re-probe
            # of a lane we just backed off from.
            live_now = [i for i in cached.get("live", []) if not is_cooling(i)]
            return {**cached, "from_cache": True, "live": live_now,
                    "cooling": [i for i in cached.get("live", []) if is_cooling(i)],
                    "cache_age_sec": round(time.time() - float(cached["cached_at"]), 1)}

    workdir = Path(workdir or "/tmp/eng-probe")
    workdir.mkdir(parents=True, exist_ok=True)

    def one(lane: Lane) -> LaneResult:
        res = invoke(lane, PROBE_PROMPT, workdir / lane.id, timeout_sec, title="probe",
                     mode="ro", idle_sec=min(timeout_sec, 75))
        if res.verdict == "ok" and PROBE_TOKEN not in res.text.upper():
            res.verdict = "empty"
        return res

    with ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
        results = list(pool.map(one, targets))

    report = {
        "probed_at": util.utc_now(),
        "probed_at_ist": util.ist_now(),
        "cached_at": time.time(),
        "from_cache": False,
        "live": [r.lane_id for r in results if r.ok],
        "dead": {r.lane_id: r.verdict for r in results if not r.ok},
        "total_cost": sum(r.cost for r in results),
        "results": [{k: v for k, v in asdict(r).items() if k != "raw_events"}
                    for r in results],
        "disabled": {ln.id: ln.notes for ln in lanes if not ln.enabled},
    }
    if report["live"]:
        util.write_json(cache_path, report)
    return report


# ------------------------------------------------------------------------- pick

_ROTATION: dict[str, int] = {}
_ROTATION_LOCK = threading.Lock()

# Filled by pick(needs_web=True) when it had to fall back to lanes that cannot browse.
WEB_FALLBACK: list[str] = []


def web_fallback_used() -> list[str]:
    """Lanes used for a web task despite not being able to fetch, since the last pick."""
    with _ROTATION_LOCK:
        return list(WEB_FALLBACK)


def _rotate(role: str, n: int) -> int:
    with _ROTATION_LOCK:
        i = _ROTATION.get(role, 0)
        _ROTATION[role] = i + 1
    return i % n if n else 0


def pick(lanes: list[Lane], health: dict, role: str, count: int = 1,
         exclude_families: set | None = None,
         exclude_lanes: set | None = None,
         needs_web: bool = False) -> list[Lane]:
    """Choose live lanes for a role: diverse families, spread load, avoid cooling lanes.

    Family diversity makes independent review meaningful. Rotation spreads parallel
    parts across lanes, so one rate-limited lane cannot stall a whole build.

    `needs_web` is the research department's requirement: a lane sent to gather primary
    sources is only useful if it can open a web page. Web-capable lanes are preferred;
    only when no web-capable lane is eligible does the choice fall back, and
    `web_fallback_used()` then reports those lane ids so the caller records that the
    slice could not browse rather than trusting its text.
    """
    live = set(health.get("live", []))
    exclude_families = set(exclude_families or ())
    exclude_lanes = set(exclude_lanes or ())

    def eligible(require_role: bool, allow_cooling: bool, require_web: bool = False):
        return [ln for ln in lanes
                if ln.id in live and ln.id not in exclude_lanes
                and ln.family not in exclude_families
                and (ln.supports(role) or not require_role)
                and not (ln.readonly and role in BUILDER_ROLES)
                and (not require_web or ln.web)
                and (allow_cooling or not is_cooling(ln.id))]

    pool = (eligible(True, False, needs_web) or eligible(False, False, needs_web)
            or eligible(True, True, needs_web) or eligible(False, True, needs_web)
            or ([ln for ln in eligible(True, False) or eligible(False, False)
                 or eligible(True, True) or eligible(False, True)] if needs_web else []))
    if needs_web:
        with _ROTATION_LOCK:
            WEB_FALLBACK[:] = [ln.id for ln in pool if not ln.web]
    if not pool:
        return []

    start = _rotate(role, len(pool))
    ordered = pool[start:] + pool[:start]

    chosen, used_families = [], set()
    for lane in ordered:
        if lane.family not in used_families:
            chosen.append(lane)
            used_families.add(lane.family)
        if len(chosen) == count:
            return chosen
    for lane in ordered:
        if lane not in chosen:
            chosen.append(lane)
        if len(chosen) == count:
            break
    return chosen
