#!/usr/bin/env python3
"""Flag weak engine task specs before they are run.

The engine's intake gate (engine/spec.py) rejects a spec with no title, a goal under
40 characters, a depth outside 1-5, or neither deliverables nor acceptance. It does not
catch a spec that passes intake but cannot tell real work from fake work. This lint
does. Error-level findings:

- no acceptance commands at all (deliverables alone only prove a file exists);
- an acceptance command that only tests existence (test -f, [ -e ], ls, stat, cat,
  wc, echo) or can never fail (`|| true`, a trailing `; echo ok`);
- an acceptance entry or deliverable with no cmd/path (the engine drops it silently);
- a code or document deliverable with min_bytes missing or below 200;
- a relative deliverable path, or one outside authorized_paths or inside banned_paths;
- an authorized path inside a tripwire-protected root (agents/, bin/, the ssh
  directory, the engine's own code), which would fail the run the moment a lane wrote there;
- a context source pointing at credentials;
- banned words in the title (max, heavy, complex, architecture) - the old
  qoder runner matches them and switches to a paid tier;
- depth outside 1-5 or not an integer; a goal under 40 characters.

Warnings cover what is risky but sometimes legitimate. Exit 0 when there are no
errors (warnings allowed unless --strict), 1 on errors, 2 if the file cannot be
read or parsed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

import yaml

KNOWN_KEYS = {"id", "title", "goal", "depth", "acceptance", "deliverables", "context_sources",
              "context_questions", "authorized_paths", "banned_paths", "constraints", "parts",
              "board_issue", "max_parallel", "department", "agent"}
ACCEPT_KEYS = {"cmd", "expect_exit", "expect_stdout", "forbid_stdout", "cwd", "timeout_sec", "name"}
CODE_DOC_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".go",
                ".rs", ".java", ".c", ".h", ".cpp", ".rb", ".php", ".sql", ".prisma", ".css",
                ".scss", ".html", ".svg", ".md", ".txt", ".rst", ".yaml", ".yml", ".json",
                ".toml", ".ini", ".cfg", ".vue", ".svelte"}
MIN_CODE_BYTES = 200

HOME = "/home/ubuntu"
COMPANY = f"{HOME}/aaryas-life"
PIPELINE = f"{COMPANY}/organisation-rebuild/departments/engineering/pipeline"
TRIPWIRE = [f"{COMPANY}/agents", f"{COMPANY}/bin", f"{HOME}/." + "ssh",
            f"{PIPELINE}/engine", f"{PIPELINE}/lanes.yaml", f"{HOME}/." + "config"]
TOO_BROAD = {"/", "/home", HOME, COMPANY, "/tmp", "/etc", "/var"}
SUGGESTED_BANNED = [f"{HOME}/clubsite", f"{HOME}/clubsite-git", f"{COMPANY}/agents",
                    f"{COMPANY}/bin", f"{HOME}/." + "config", f"{HOME}/." + "ssh"]

TITLE_BANNED = re.compile(r"\[max\]|\bmax\b|heavy|complex|architecture", re.I)
# Credential locations, written so this file never contains the literal paths itself.
CRED_RE = re.compile(r"(?<![\\\w])\.(?:ssh|config)(?:/|\b)|(?<![\\\w-])\.(?:env)\b|\bid_(?:rsa|ed25519)\b"
                     r"|nvidia-nim\.(?:env)|\bcredentials?\.json\b", re.I)

TRIVIAL = {"test", "[", "[[", "ls", "stat", "file", "echo", "printf", "true", ":", "cat", "wc",
           "du", "head", "tail", "find", "exit", "readlink", "realpath", "basename", "dirname"}
NEUTRAL = {"cd", "pushd", "popd", "export", "set", "umask", "sleep", "]", "]]", "unset"}
OPS = {"&&", "||", ";", "|", "&", "|&", ";;"}
MASKING_SINKS = {"tee", "head", "tail", "cat", "sort", "uniq", "wc", "less", "more"}


class Findings:
    def __init__(self):
        self.items = []

    def error(self, where, msg):
        self.items.append(("ERROR", where, msg))

    def warn(self, where, msg):
        self.items.append(("WARN", where, msg))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]

    @property
    def warnings(self):
        return [i for i in self.items if i[0] == "WARN"]


def norm(path: str) -> str:
    text = str(path)
    if text.startswith("~"):
        text = HOME + text[1:]
    return os.path.normpath(text)


def under(path: str, root: str) -> bool:
    path, root = norm(path), norm(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


# ---------------------------------------------------------------- shell analysis

def segments(cmd: str):
    """Split a shell command into (operator_before, words) segments. None if unparseable."""
    lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        return None
    segs, cur, op = [], [], None
    for tok in tokens:
        if tok in OPS:
            segs.append((op, cur))
            cur, op = [], tok
        elif tok in ("(", ")", "{", "}"):
            continue
        else:
            cur.append(tok)
    segs.append((op, cur))
    return [(o, w) for o, w in segs if w or o]


def command_name(words: list) -> str:
    skip_next = False
    for w in words:
        if skip_next:
            skip_next = False
            continue
        if w == "!":
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):
            continue
        if re.fullmatch(r"\d*[<>]+&?\d*", w):
            skip_next = not re.fullmatch(r"\d*[<>]&\d+", w)
            continue
        return os.path.basename(w)
    return ""


def analyse_cmd(cmd: str, has_stdout_check: bool):
    """Return (problems, warnings) for one acceptance command."""
    problems, warns = [], []
    segs = segments(cmd)
    if segs is None:
        warns.append("could not parse the command (unbalanced quotes?)")
        return problems, warns
    names = [command_name(w) for _, w in segs]
    substantive = [n for n in names if n and n not in TRIVIAL and n not in NEUTRAL]
    if not substantive:
        problems.append("only tests existence or prints text (" + ", ".join(
            sorted({n for n in names if n})) + "); it passes on an empty or fake file. "
            "Put existence in deliverables with min_bytes and make this check run, "
            "compile, test or grep the content")
        return problems, warns
    errexit = bool(re.search(r"\bset\s+-[a-z]*e|\bset\s+-o\s+errexit", cmd))
    pipefail = bool(re.search(r"\bset\s+-o\s+pipefail", cmd))
    for i, (op, words) in enumerate(segs):
        if op == "||" and command_name(words) in ("true", ":") or (
                op == "||" and command_name(words) == "exit" and words[-1:] == ["0"]):
            problems.append("contains '|| true' (or '|| exit 0'), so it can never fail")
    # The exit status is the last pipeline's after the last ';'.
    last_seq = 0
    for i, (op, _) in enumerate(segs):
        if op in (";", "&"):
            last_seq = i
    tail = segs[last_seq:]
    tail_names = [command_name(w) for _, w in tail]
    if not errexit and last_seq > 0 and all(
            (not n) or n in TRIVIAL or n in NEUTRAL for n in tail_names) and not has_stdout_check:
        problems.append(f"ends in '; {' '.join(tail[0][1])}', so the exit code is that "
                        "command's and proves nothing; join with && instead")
    pipe_ops = [o for o, _ in tail[1:]]
    if pipe_ops and pipe_ops[-1] == "|" and tail_names[-1] in MASKING_SINKS \
            and not pipefail and not has_stdout_check:
        warns.append(f"pipes into {tail_names[-1]}, which masks the real exit code; add "
                     "'set -o pipefail;' or an expect_stdout")
    return problems, warns


COMPILE_RE = re.compile(r"py_compile|compileall|node\s+--check|bash\s+-n|sh\s+-n|tsc\b.*--noEmit")


def compile_only(cmd: str) -> bool:
    """True when every substantive step of the command only checks syntax."""
    segs = segments(cmd) or []
    steps = [w for _, w in segs if command_name(w) and command_name(w) not in TRIVIAL
             and command_name(w) not in NEUTRAL]
    return bool(steps) and all(COMPILE_RE.search(" ".join(w)) for w in steps)


# ---------------------------------------------------------------- checks

def check_title_goal(spec: dict, f: Findings):
    title = str(spec.get("title") or "").strip()
    goal = str(spec.get("goal") or "").strip()
    if not title:
        f.error("title", "missing; the engine refuses a spec without one")
    else:
        hits = sorted({m.group(0).lower() for m in TITLE_BANNED.finditer(title)})
        if hits:
            f.error("title", f"contains {', '.join(repr(h) for h in hits)}; the old qoder "
                    "runner matches these words and switches to a paid tier. Reword it "
                    "(say 'large', 'multi-part', 'design' instead)")
        if len(title) > 90:
            f.warn("title", f"{len(title)} characters; keep titles under 90")
    if not goal:
        f.error("goal", "missing; the engine refuses a spec without one")
    elif len(goal) < 40:
        f.error("goal", f"only {len(goal)} characters; the intake gate needs at least 40 "
                "and a planner needs the outcome and how it is judged")
    elif TITLE_BANNED.search(goal):
        f.warn("goal", "mentions max/heavy/complex/architecture; harmless to the engine, but "
               "the old runners match issue text too, so keep it out of board issues")


def check_depth(spec: dict, f: Findings):
    if "depth" not in spec:
        f.warn("depth", "not set; the engine defaults to 3. Choose 1-5 on purpose")
        return
    d = spec["depth"]
    if isinstance(d, bool) or not isinstance(d, int):
        f.error("depth", f"{d!r} is not an integer 1-5")
    elif not 1 <= d <= 5:
        f.error("depth", f"{d} is outside 1-5")


def check_paths(spec: dict, f: Findings):
    auth = [str(p) for p in spec.get("authorized_paths") or []]
    banned = [str(p) for p in spec.get("banned_paths") or []]
    for p in auth:
        if not norm(p).startswith("/"):
            f.error("authorized_paths", f"{p!r} is relative; use an absolute path")
        for t in TRIPWIRE:
            if under(p, t):
                f.error("authorized_paths", f"{p} is inside the protected root {t}; the "
                        "engine's tripwire fails any run that writes there")
            elif under(t, p):
                f.warn("authorized_paths", f"{p} contains the protected root {t}; a lane "
                       "writing there fails the whole run. Narrow the path")
        if norm(p) in TOO_BROAD:
            f.warn("authorized_paths", f"{p} is far too broad; authorize the task's own directory")
    if not banned:
        f.warn("banned_paths", "none listed; start from " + ", ".join(SUGGESTED_BANNED))
    for src in spec.get("context_sources") or []:
        if CRED_RE.search(str(src)):
            f.error("context_sources", f"{src} points at credentials; never feed them to a lane")
    return auth, banned


def check_deliverables(spec: dict, f: Findings, auth: list, banned: list):
    items = spec.get("deliverables") or []
    if not isinstance(items, list):
        f.error("deliverables", "must be a list of {path, min_bytes, description}")
        return
    for i, d in enumerate(items, 1):
        where = f"deliverables[{i}]"
        if not isinstance(d, dict) or not d.get("path"):
            f.error(where, "has no path; the engine drops it silently")
            continue
        path = str(d["path"])
        where = f"deliverable {path}"
        if not path.startswith("/") and not path.startswith("~"):
            f.error(where, "relative path; the gate resolves it against an unknown cwd. "
                    "Use an absolute path")
        ext = Path(path).suffix.lower()
        mb = d.get("min_bytes")
        if mb is None:
            if ext in CODE_DOC_EXT:
                f.error(where, f"min_bytes missing (the engine defaults to 1, so an empty "
                        f"stub passes); set a realistic size, at least {MIN_CODE_BYTES}")
            else:
                f.warn(where, "min_bytes missing; the engine defaults to 1 byte")
        elif not isinstance(mb, int) or isinstance(mb, bool):
            f.error(where, f"min_bytes {mb!r} is not an integer")
        elif ext in CODE_DOC_EXT and mb < MIN_CODE_BYTES:
            f.error(where, f"min_bytes {mb} is below {MIN_CODE_BYTES}; a stub or one-line "
                    "placeholder would pass")
        elif ext not in CODE_DOC_EXT and mb < MIN_CODE_BYTES:
            f.warn(where, f"min_bytes {mb} is small for a {ext or 'binary'} file")
        if auth and not any(under(path, a) for a in auth):
            f.error(where, "is outside every authorized path, so no lane may write it")
        for b in banned:
            if under(path, b):
                f.error(where, f"is inside banned path {b}")
        if not d.get("description"):
            f.warn(where, "no description; say what the file must contain")
    if items and not auth:
        f.warn("authorized_paths", "deliverables are listed but no authorized_paths; lanes "
               "get no explicit write scope")


def check_acceptance(spec: dict, f: Findings):
    items = spec.get("acceptance") or []
    if not isinstance(items, list):
        f.error("acceptance", "must be a list of {name, cmd, expect_exit, ...}")
        return
    real = [a for a in items if isinstance(a, dict) and a.get("cmd")]
    if not real:
        f.error("acceptance", "no acceptance commands; deliverables alone only prove a file "
                "exists. Add checks that compile, run tests, run the program and parse its "
                "output, or grep for required content")
    if real and all(compile_only(str(a["cmd"])) for a in real):
        f.warn("acceptance", "every check only compiles; a stub compiles too. Add a check "
               "that runs the tests or the program and inspects its output")
    for i, a in enumerate(items, 1):
        if not isinstance(a, dict) or not a.get("cmd"):
            f.error(f"acceptance[{i}]", "has no cmd; the engine drops it silently")
            continue
        name = a.get("name") or f"check{i}"
        where = f"acceptance {name}"
        extra = set(a) - ACCEPT_KEYS
        if extra:
            f.warn(where, f"unknown key(s) {', '.join(sorted(extra))}; the engine ignores them")
        if not isinstance(a["cmd"], str):
            f.error(where, f"cmd is a {type(a['cmd']).__name__}, not a string; YAML reads "
                    "an unquoted '[ ... ]' or '{ ... }' as a list or mapping. Quote the command")
            continue
        cmd = a["cmd"]
        has_stdout = bool(a.get("expect_stdout") or a.get("forbid_stdout"))
        problems, warns = analyse_cmd(cmd, has_stdout)
        for p in problems:
            f.error(where, p)
        for w in warns:
            f.warn(where, w)
        if CRED_RE.search(cmd) and not re.search(r"(^|[;&|]\s*)!\s*grep", cmd):
            f.warn(where, "references a credential location; checks must never read credentials")
        t = a.get("timeout_sec")
        if isinstance(t, int) and t > 1800:
            f.warn(where, f"timeout_sec {t} is over 30 minutes")
        ee = a.get("expect_exit", 0)
        if not isinstance(ee, int) or isinstance(ee, bool):
            f.error(where, f"expect_exit {ee!r} is not an integer")


def check_parts(spec: dict, f: Findings):
    parts = spec.get("parts") or []
    owners = {}
    for i, part in enumerate(parts, 1):
        if not isinstance(part, dict):
            f.error(f"parts[{i}]", "must be a mapping")
            continue
        pid = part.get("id") or f"part{i}"
        if not part.get("id"):
            f.error(f"parts[{i}]", "has no id")
        if not part.get("owns_files"):
            f.error(f"part {pid}", "owns no files; every part needs exclusive file ownership")
        for path in part.get("owns_files") or []:
            if path in owners:
                f.error(f"part {pid}", f"{path} is also owned by part {owners[path]}; "
                        "ownership must be exclusive")
            owners[path] = pid
        vc = part.get("verify_cmd")
        if vc and not isinstance(vc, str):
            f.error(f"part {pid}", "verify_cmd is not a string; quote the command")
        elif not vc:
            f.error(f"part {pid}", "has no verify_cmd; the gate cannot check it")
        else:
            problems, _ = analyse_cmd(str(vc), False)
            for p in problems:
                f.error(f"part {pid} verify_cmd", p)


def lint(spec, f: Findings) -> Findings:
    if not isinstance(spec, dict):
        f.error("spec", "is not a mapping")
        return f
    unknown = set(spec) - KNOWN_KEYS
    for k in sorted(unknown):
        close = [x for x in KNOWN_KEYS if x[:4] == k[:4]]
        f.warn(k, "unknown top-level key; the engine ignores it"
               + (f" (did you mean {close[0]}?)" if close else ""))
    check_title_goal(spec, f)
    check_depth(spec, f)
    auth, banned = check_paths(spec, f)
    check_deliverables(spec, f, auth, banned)
    check_acceptance(spec, f)
    check_parts(spec, f)
    if not (spec.get("acceptance") or spec.get("deliverables")):
        f.error("spec", "neither acceptance nor deliverables; the intake gate refuses it")
    return f


def load(path: Path):
    text = path.read_text()
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="spec_lint.py",
        description="Flag weak engine task specs (existence-only checks, tiny min_bytes, "
                    "no acceptance, paths outside scope, paid-trigger title words, bad depth).")
    p.add_argument("spec", help="task spec, .yaml or .json")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.add_argument("--json", action="store_true", help="print findings as JSON")
    args = p.parse_args(argv)
    path = Path(args.spec)
    try:
        spec = load(path)
    except OSError as exc:
        print(f"spec_lint: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    except (yaml.YAMLError, ValueError) as exc:
        print(f"spec_lint: {path} does not parse: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 2
    f = lint(spec, Findings())
    failing = f.errors + (f.warnings if args.strict else [])
    if args.json:
        print(json.dumps({"spec": str(path), "errors": len(f.errors), "warnings": len(f.warnings),
                          "findings": [{"level": l, "where": w, "message": m}
                                       for l, w, m in f.items]}, indent=2))
    else:
        for level, where, msg in f.items:
            print(f"{level:<5} {where}: {msg}")
        print(f"\n{path}: {len(f.errors)} error(s), {len(f.warnings)} warning(s)"
              + (" - OK" if not failing else ""))
    if failing:
        print(f"spec_lint: {len(failing)} blocking finding(s), first: "
              f"{failing[0][1]}: {failing[0][2][:160]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
