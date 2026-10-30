#!/usr/bin/env python3
"""Gate a candidate public tree before it can be pushed.

Collects identifying values from the private structured data (people, applications,
drafts), then greps the public tree for them plus pattern-based secret/PII shapes.
Prints masked previews and paths only, so this report cannot itself leak anything.
"""
import json
import re
import sys
from pathlib import Path

PRIVATE = Path(sys.argv[1])
PUBLIC = Path(sys.argv[2])

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# A phone must look like a phone: two groups of five with a separator. This deliberately
# does not match ISO dates (2026-10-30) or timestamps, which an earlier looser pattern did.
PHONE = re.compile(r"(?<![\dA-Za-z.-])(?:\+?91[-\s]?)?\d{5}[-\s]\d{5}(?![\dA-Za-z.-])")
TOKEN_PREFIX = re.compile(r"\b(?:ghp_|github_pat_|gho_|ghs_|nvapi-|sk-[A-Za-z0-9]{12,}|xox[abprs]-|AKIA[0-9A-Z]{8,}|AIza[0-9A-Za-z_-]{10,}|eyJ[A-Za-z0-9_-]{10,})")
# Only a literal high-entropy value counts; `$VAR`, `$(...)`, `<placeholder>` and empty
# assignments are how these scripts legitimately refer to secrets kept in 600-perm files.
SECRET_LITERAL = re.compile(
    r"(?:api[_-]?key|secret|passwd|password|access[_-]?token|dispatch[_-]?key|authorization|token)"
    r"\b\s*[:=]\s*[\"']?(?!\s*[\"']?$)(?!\$|\(|<|%)[A-Za-z0-9+/=_\-\.]{16,}",
    re.I,
)
DATABASE_URI = re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s/]*@", re.I)

ORG_DOMAINS = ("codescriet.dev", "example.test", "example.com", "example.org",
               "localhost", "test", "sample.com", "aaryas.life")
FAKE_MARKERS = ("example", "placeholder", "your-", "your_", "changeme", "<", "...",
                "xxxx", "aaaa", "dummy", "fixture", "redacted", "sentinel")
PERSONAL_MAIL = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
                 "proton.me", "protonmail.com", "rediffmail.com", "gmail")

# Reviewed by hand, with the reason each one is safe. Anything new that matches these
# patterns still has to be read before it is added here.
ALLOWED = {
    ("departments/club/tools/test_draft_lint.py", "personal-mail-domain"),
    ("departments/club/tools/test_triage.py", "personal-mail-domain"),
    ("departments/platform/skills/service-map.md", "phone-shaped"),
    ("departments/platform/tools/report_lint.py", "token-prefix"),
    ("departments/platform/tools/test_report_lint.py", "database-uri"),
    ("engine/engine/util.py", "token-prefix"),
    ("engine/tests/test_engine.py", "token-prefix"),
    ("engine/tests/test_engine.py", "database-uri"),
}
ALLOWED_REASONS = {
    "a.student@gmail.com": "fake fixture that proves the club draft lint catches personal mail",
    "18761-18766": "a TCP port range, not a phone number",
    "token-prefix": "the redaction tool's own list of prefixes to mask",
    "hunter2secret": "fixture credential in a test of the secret tripwire",
}


def looks_real(value):
    low = value.lower()
    return not any(marker in low for marker in FAKE_MARKERS)


def mask(value):
    value = value.strip()
    return value[:2] + "***" + value[-2:] if len(value) > 5 else "***"


def structured_people_values():
    """Names and contacts held in the private CRM and career tracker."""
    found = {}

    def add(kind, value):
        value = (value or "").strip()
        if len(value) >= 4 and looks_real(value):
            found.setdefault(f"{kind}|{value.lower()}", (kind, value))

    targets = {
        "departments/personal/crm/people.json": ("name", "relationship", "notes"),
        "departments/personal/crm/reminders.json": ("name", "person", "notes"),
        "departments/career/pipeline/applications.json": ("contact", "organization", "notes"),
    }
    for rel, text_keys in targets.items():
        path = PRIVATE / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rows = data if isinstance(data, list) else (
            data.get("people") or data.get("records") or data.get("applications") or [])
        if isinstance(rows, dict):
            rows = list(rows.values())
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            for key in ("name", "full_name", "person", "contact"):
                if isinstance(rec.get(key), str):
                    add("person-name", rec[key])
            for key in text_keys:
                value = rec.get(key)
                if isinstance(value, str):
                    for m in EMAIL.findall(value):
                        add("email", m)
                    for m in PHONE.findall(value):
                        add("phone", m)
            info = rec.get("contact_info") or {}
            if isinstance(info, dict):
                for value in info.values():
                    if isinstance(value, str):
                        for m in EMAIL.findall(value):
                            add("email", m)
                        for m in PHONE.findall(value):
                            add("phone", m)
                        if (not EMAIL.search(value) and not PHONE.search(value)
                                and len(value) >= 4 and looks_real(value)):
                            add("contact-detail", value)

    for path in (PRIVATE / "departments/personal/crm/drafts").glob("*.json"):
        try:
            blob = json.dumps(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            continue
        for m in EMAIL.findall(blob):
            add("email", m)
        for m in PHONE.findall(blob):
            add("phone", m)
    return found


def walk(root):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # The gate tool embeds the very patterns it hunts for; scanning it would only
        # ever report itself. Everything else in the tree is fair game.
        if path.name == "scan_public.py":
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".webp", ".ttf",
                                   ".otf", ".woff", ".woff2", ".pdf", ".zip", ".gz", ".tgz",
                                   ".bundle", ".mp3", ".ico"}:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def main():
    people = structured_people_values()
    names = [(k, v) for k, (kind, v) in people.items() if kind in ("person-name", "contact-detail")]
    files = list(walk(PUBLIC))
    hits = []
    binaries = [str(p.relative_to(PUBLIC)) for p in PUBLIC.rglob("*")
                if p.is_file() and p.suffix.lower() in
                {".png", ".jpg", ".jpeg", ".mp4", ".ttf", ".otf", ".pdf", ".webp", ".ico"}]

    for path, text in files:
        rel = str(path.relative_to(PUBLIC))
        low = text.lower()
        for key, value in names:
            if value.lower() in low:
                hits.append((rel, "private-person-or-contact", mask(value)))
        for m in EMAIL.findall(text):
            domain = m.split("@", 1)[1].lower()
            if any(domain.endswith(d) for d in ORG_DOMAINS):
                continue
            if m.lower() in {v.lower() for _, v in people.values() if v.count("@")}:
                hits.append((rel, "private-email", mask(m)))
            elif any(p in domain for p in PERSONAL_MAIL):
                hits.append((rel, "personal-mail-domain", mask(m)))
        for m in PHONE.findall(text):
            hits.append((rel, "phone-shaped", mask(m)))
        if TOKEN_PREFIX.search(text):
            hits.append((rel, "token-prefix", ""))
        for m in SECRET_LITERAL.findall(text):
            if looks_real(m) and len(m) >= 16 and re.search(r"[0-9]", m):
                hits.append((rel, "secret-literal-shaped", mask(m)))
        for m in DATABASE_URI.findall(text):
            if not any(h in m.lower() for h in ("localhost", "example", "127.0.0.1")):
                hits.append((rel, "database-uri", mask(m)))

    blocked = [(rel, kind, preview) for rel, kind, preview in hits
               if (rel, kind) not in ALLOWED]
    allowed = [(rel, kind) for rel, kind, _ in hits if (rel, kind) in ALLOWED]

    for rel, kind, preview in blocked:
        print(f"HIT  {rel}: {kind}" + (f" ({preview})" if preview else ""))
    if allowed:
        print(f"\nallowed after manual review: {len(set(allowed))}")
        for rel, kind in sorted(set(allowed)):
            print(f"  ok: {rel} ({kind})")
    print(f"\nscanned {len(files)} text files against {len(people)} private identifiers "
          f"({len(names)} names/contacts)")
    print(f"binary files in tree: {len(binaries)}")
    for b in binaries[:8]:
        print(f"  bin: {b}")
    print(f"unallowed distinct hits: {len(set((r, k) for r, k, _ in blocked))}")
    return 1 if blocked or binaries else 0


if __name__ == "__main__":
    sys.exit(main())
