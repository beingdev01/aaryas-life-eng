"""Shared helpers: paths, redaction, atomic writes, timing."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import unicodedata
from pathlib import Path

HOME = Path(os.environ.get("ENG_HOME", "/home/ubuntu/aaryas-life"))
PIPELINE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ.get("ENG_RUNS", PIPELINE_DIR / "runs"))
LANES_FILE = Path(os.environ.get("ENG_LANES", PIPELINE_DIR / "lanes.yaml"))

COMPANY_ID = os.environ.get("ENG_COMPANY_ID", "469f7950-25cf-4366-8a82-1469c40e278f")

_SECRET_PATTERNS = [
    # Order matters. Auth headers consume the rest of the line first, otherwise the
    # generic key=value rule below matches only the scheme word ("Bearer") and leaves
    # the token itself in the clear.
    (re.compile(r'((?:proxy-)?authorization\s*[=:]\s*)[^\n\r]+', re.I), r'\1[REDACTED]'),
    (re.compile(r'\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}'), r'\1 [REDACTED]'),
    (re.compile(
        r'((?:api[_-]?key|access[_-]?key|secret|token|passw(?:or)?d|'
        r'dispatch[_-]?key|private[_-]?key|DATABASE_URL|DB_URL|PGPASSWORD|cookie)'
        r'[A-Za-z0-9_]*["\']?\s*[=:]\s*["\']?)([^\s"\',}]{6,})', re.I), r'\1[REDACTED]'),
    (re.compile(r'\b(sk-|sk_|pk_|rk_|ghp_|gho_|ghs_|github_pat_|xox[abprs]-|nvapi-|'
                r'pcp_|AKIA|AIza|eyJ)[A-Za-z0-9_\-.]{8,}'), r'\1[REDACTED]'),
    (re.compile(r'((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:/\s]+:)'
                r'[^@\s]+@', re.I), r'\1[REDACTED]@'),
]


def redact(text: str) -> str:
    """Strip anything that looks like a credential. Applied to every stored artifact."""
    if not text:
        return text
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ist_now() -> str:
    ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    return _dt.datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")


def slugify(text: str, maxlen: int = 48) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:maxlen].rstrip("-")) or "task"


def write_text(path: Path, content: str, do_redact: bool = True) -> int:
    """Atomic write. Returns bytes written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if do_redact:
        content = redact(content)
    data = content.encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return len(data)


def write_json(path: Path, obj) -> int:
    return write_text(path, json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                      do_redact=True)


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def clip(text: str, limit: int) -> str:
    """Trim to a byte-ish budget, keeping head and tail so structure survives."""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = limit - head - 40
    return f"{text[:head]}\n\n... [{len(text) - limit} chars elided] ...\n\n{text[-tail:]}"


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n / 1.0:.1f}{unit}"
        n /= 1024.0
    return f"{n}B"
