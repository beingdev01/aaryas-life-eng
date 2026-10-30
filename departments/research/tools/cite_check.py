#!/usr/bin/env python3
"""cite_check: fail a research memo whose claims cannot be traced to a source.

Rules (each one is a gate failure):
  1. The memo has a Sources (or References) section with at least one entry, and every
     entry carries a locator: a URL, a DOI, or a file path.
  2. Inside a Findings / Claims / Evidence / Facts section, every paragraph, bullet and
     table data row carries either a citation or an INFERENCE marker.
       citation  = a URL, a [n] reference that resolves to a numbered source, or path:line
       marker    = the word INFERENCE, "Inference:", "(inference)", or the unit sits under
                   a label or sub-heading that says Inference(s)
  3. Every [n] reference anywhere in the memo resolves to a numbered source.
  4. No malformed URLs anywhere outside fenced code (http//x, https:/x, https:// with
     no host, a host with no dot, an empty markdown link target).

Exit codes: 0 clean, 1 problems found (one line per problem on stdout, a one-line
summary on stderr), 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
TABLE_ROW = re.compile(r"^\s*\|")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
COMMENT = re.compile(r"^\s*<!--.*-->\s*$")

SOURCES_TITLE = re.compile(r"^(sources|references|bibliography)\b", re.I)
CLAIMS_TITLE = re.compile(r"^(key\s+)?(findings|claims|evidence|facts)\b", re.I)

# A label line ("**Inferences:**") governs the list under it. It must be recognised even
# when the writer put no blank line above it: glued to the previous bullet, it used to be
# swallowed into that bullet's text, so the label never applied and every inference under
# it was reported as an uncited claim.
LABEL_LINE = re.compile(
    r"^\s*[*_]{0,3}\s*(facts?|evidence|inferences?|reasoning)\s*[:\uFF1A]\s*[*_]{0,3}\s*$",
    re.I)

URL = re.compile(r"https?://[^\s<>\"'`]+")
URL_CANDIDATE = re.compile(r"(?i)\bh?tt?ps?(?::/+|/{2,})[^\s<>\"'`]*")
HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
REF = re.compile(r"\[(\d+(?:\s*[,\u2013-]\s*\d+)*)\](?!\()")
PATH_LINE = re.compile(
    r"(?<![\w/])(?:~|\.{1,2})?/?(?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z][A-Za-z0-9]{0,7}:\d+(?:-\d+)?\b")
DOI = re.compile(r"\b(?:doi:\s*|DOI:\s*)?10\.\d{4,9}/\S+")
FILE_PATH = re.compile(r"(?:^|\s|`)(?:~|\.{1,2})?/[\w.-]+(?:/[\w.-]+)+")
INFERENCE = re.compile(
    r"\bINFERENCE\b|(?i:\binference\s*[:)\]\u2014-])|(?i:[(\[]\s*inference)")
EMPTY_LINK = re.compile(r"\]\(\s*\)")
TRAIL = ".,;:!?*_)]>'\"`"


def norm_title(text: str) -> str:
    text = re.sub(r"[*_`]", "", text).strip()
    text = re.sub(r"^(?:\d+[.)]?\s*)+", "", text)
    return text.strip()


def code_mask(lines: list[str]) -> list[bool]:
    """True for every line inside (or opening/closing) a fenced code block."""
    mask, inside = [], False
    for line in lines:
        if FENCE.match(line):
            mask.append(True)
            inside = not inside
            continue
        mask.append(inside)
    return mask


def sections(lines: list[str], mask: list[bool]) -> list[dict]:
    heads = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        m = HEADING.match(line)
        if m:
            heads.append({"level": len(m.group(1)), "title": norm_title(m.group(2)),
                          "start": i})
    for k, h in enumerate(heads):
        end = len(lines)
        for later in heads[k + 1:]:
            if later["level"] <= h["level"]:
                end = later["start"]
                break
        h["end"] = end
    return heads


def strip_inline_code(text: str) -> str:
    """Remove inline code spans, so that `arr[0]` is not read as a citation."""
    return re.sub(r"`[^`]*`", " ", text)


def unquote_code(text: str) -> str:
    """Keep inline code content but drop the backticks (paths often sit in code)."""
    return text.replace("`", " ")


def clean_url(raw: str) -> str:
    url = raw
    while url and url[-1] in TRAIL:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def url_problem(url: str) -> str | None:
    m = re.match(r"^(https?)://([^/?#\s]*)(.*)$", url, re.I)
    if not m:
        return "not of the form http(s)://host/..."
    hostport = m.group(2)
    if "@" in hostport:
        hostport = hostport.rsplit("@", 1)[1]
    host, _, port = hostport.partition(":")
    if port and not (port.isdigit() and 0 < int(port) < 65536):
        return f"bad port '{port}'"
    if not host:
        return "no host"
    if host == "localhost" or IPV4.match(host):
        return None
    labels = host.split(".")
    if len(labels) < 2:
        return f"host '{host}' has no dot"
    if not all(HOST_LABEL.match(lab) for lab in labels):
        return f"host '{host}' has an invalid label"
    if not re.match(r"^(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]+)$", labels[-1]):
        return f"host '{host}' has no valid top-level domain"
    return None


def expand_refs(group: str) -> list[int]:
    out = []
    for part in re.split(r"\s*,\s*", group):
        rng = re.split(r"\s*[\u2013-]\s*", part)
        if len(rng) == 2 and rng[0].isdigit() and rng[1].isdigit():
            a, b = int(rng[0]), int(rng[1])
            if a <= b and b - a <= 50:
                out.extend(range(a, b + 1))
                continue
        if part.strip().isdigit():
            out.append(int(part.strip()))
    return out


def has_locator(text: str) -> bool:
    return bool(URL.search(text) or DOI.search(text) or PATH_LINE.search(text)
                or FILE_PATH.search(text))


def parse_sources(lines: list[str], sec: dict, mask: list[bool]):
    """Return (ids -> (line_no, text), unnumbered entries, problems)."""
    ids: dict[int, tuple[int, str]] = {}
    entries: list[tuple[int, str, int | None]] = []
    problems: list[tuple[int, str]] = []
    for i in range(sec["start"] + 1, sec["end"]):
        if mask[i]:
            continue
        line = lines[i]
        if not line.strip() or HEADING.match(line) or RULE.match(line) or COMMENT.match(line):
            continue
        if re.match(r"^\s*RESULT:", line):
            break
        m = (re.match(r"^\s*(?:[-*+]\s*)?\[(\d+)\]:?\s*(.*)$", line)
             or re.match(r"^\s*(\d+)[.)]\s+(.*)$", line))
        if m:
            entries.append((i, m.group(2), int(m.group(1))))
            continue
        if BULLET.match(line):
            entries.append((i, BULLET.sub("", line, count=1), None))
            continue
        if entries and (line.startswith((" ", "\t"))):
            ln, text, num = entries[-1]
            entries[-1] = (ln, text + " " + line.strip(), num)
            continue
        entries.append((i, line.strip(), None))
    for ln, text, num in entries:
        label_only = text.rstrip().endswith(":") and not has_locator(text)
        if num is None and label_only:
            continue
        if not has_locator(text):
            name = f"source [{num}]" if num is not None else "source entry"
            problems.append((ln + 1, f"{name} has no URL, DOI or file path: "
                                     f"'{text.strip()[:70]}'"))
        if num is not None:
            if num in ids:
                problems.append((ln + 1, f"source [{num}] is defined twice "
                                         f"(first on line {ids[num][0]})"))
            else:
                ids[num] = (ln + 1, text)
    return ids, entries, problems


def claim_units(lines: list[str], sec: dict, mask: list[bool]):
    """Yield (line_no, text, under_inference_label) for each claim unit."""
    units: list[tuple[int, str, bool]] = []
    cur: list = []
    mode_inference = False
    in_scope = 0          # units seen since the last label or sub-heading
    i = sec["start"] + 1

    def flush():
        # A label ("**Inferences:**") covers the list that follows it. A plain paragraph
        # after that list ends the label's scope, so one label cannot launder a whole
        # section of uncited prose.
        nonlocal cur, mode_inference, in_scope
        if not cur:
            return
        ln, text = cur[0], " ".join(cur[1]).strip()
        cur = []
        if not text:
            return
        bare = re.sub(r"[*_`]", "", BULLET.sub("", text, count=1)).strip()
        if bare.endswith(":") and len(bare) <= 100 and not has_locator(bare):
            mode_inference = bool(re.search(r"(?i)inferen", bare))
            in_scope = 0
            return
        if not BULLET.match(text) and in_scope > 0:
            mode_inference = False
        in_scope += 1
        units.append((ln, text, mode_inference))

    while i < sec["end"]:
        line = lines[i]
        if mask[i]:
            flush()
            i += 1
            continue
        h = HEADING.match(line)
        if h:
            flush()
            mode_inference = bool(re.search(r"(?i)inferen", h.group(2)))
            in_scope = 0
            i += 1
            continue
        if not line.strip() or RULE.match(line):
            flush()
            i += 1
            continue
        if COMMENT.match(line):
            i += 1
            continue
        if TABLE_ROW.match(line):
            flush()
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if TABLE_SEP.match(line) or TABLE_SEP.match(nxt):
                i += 1
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if any(cells):
                in_scope += 1
                units.append((i + 1, line.strip(), mode_inference))
            i += 1
            continue
        if LABEL_LINE.match(line):
            flush()
            mode_inference = bool(re.search(r"(?i)inferen", line))
            in_scope = 0
            i += 1
            continue
        if BULLET.match(line):
            flush()
            cur = [i + 1, [line.strip()]]
            i += 1
            continue
        if cur:
            cur[1].append(line.strip())
        else:
            cur = [i + 1, [line.strip()]]
        i += 1
    flush()
    return units


def check_text(text: str) -> dict:
    lines = text.splitlines()
    mask = code_mask(lines)
    secs = sections(lines, mask)
    problems: list[tuple[int, str]] = []

    src_secs = [s for s in secs if SOURCES_TITLE.match(s["title"])]
    ids: dict = {}
    entries: list = []
    if not src_secs:
        problems.append((0, "no Sources section (add '## Sources' listing every source)"))
    else:
        for s in src_secs:
            sid, sentries, sprob = parse_sources(lines, s, mask)
            for k, v in sid.items():
                if k in ids:
                    problems.append((v[0], f"source [{k}] is defined twice"))
                ids.setdefault(k, v)
            entries.extend(sentries)
            problems.extend(sprob)
        if not entries:
            problems.append((src_secs[0]["start"] + 1, "Sources section is empty"))

    in_sources = [False] * len(lines)
    for s in src_secs:
        for k in range(s["start"], s["end"]):
            in_sources[k] = True

    # Every [n] outside Sources must resolve.
    for i, line in enumerate(lines):
        if mask[i] or in_sources[i]:
            continue
        for m in REF.finditer(strip_inline_code(line)):
            for n in expand_refs(m.group(1)):
                if n not in ids:
                    problems.append((i + 1, f"[{n}] is cited but not listed in Sources"))

    # Malformed URLs anywhere outside code.
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        if EMPTY_LINK.search(line):
            problems.append((i + 1, "markdown link with an empty target '()'"))
        for m in URL_CANDIDATE.finditer(line):
            raw = clean_url(m.group(0))
            if not raw:
                continue
            why = url_problem(raw)
            if why:
                problems.append((i + 1, f"malformed URL '{raw[:80]}': {why}"))

    claims_checked = cited = inferred = 0
    claim_secs = [s for s in secs if CLAIMS_TITLE.match(s["title"])]
    seen_lines = set()
    for s in claim_secs:
        for ln, unit, under_label in claim_units(lines, s, mask):
            if ln in seen_lines:
                continue
            seen_lines.add(ln)
            claims_checked += 1
            refs_ok = any(n in ids for m in REF.finditer(strip_inline_code(unit))
                          for n in expand_refs(m.group(1)))
            if URL.search(unit) or PATH_LINE.search(unquote_code(unit)) or refs_ok:
                cited += 1
            elif under_label or INFERENCE.search(unit):
                inferred += 1
            else:
                problems.append((ln, "claim has no citation (URL, [n], path:line) and no "
                                     f"INFERENCE marker: '{unit[:70]}'"))

    used = set()
    for i, line in enumerate(lines):
        if not mask[i] and not in_sources[i]:
            for m in REF.finditer(strip_inline_code(line)):
                used.update(expand_refs(m.group(1)))
    unused = sorted(set(ids) - used)

    problems.sort(key=lambda p: p[0])
    return {"problems": problems, "claims": claims_checked, "cited": cited,
            "inference": inferred, "sources": len(entries), "unused_sources": unused,
            "has_claims_section": bool(claim_secs)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="cite_check.py",
        description="Fail a research memo whose claims are not cited or marked INFERENCE, "
                    "whose [n] references do not resolve, whose URLs are malformed, or "
                    "which has no Sources section.")
    parser.add_argument("memo", help="path to the memo (markdown)")
    parser.add_argument("--quiet", action="store_true", help="print only the verdict line")
    args = parser.parse_args(argv)

    path = Path(args.memo)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cite_check: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return 2

    res = check_text(text)
    if res["problems"]:
        if not args.quiet:
            for ln, msg in res["problems"]:
                print(f"{path}:{ln}: {msg}" if ln else f"{path}: {msg}")
        first_ln, first = res["problems"][0]
        print(f"cite_check: FAIL {path}: {len(res['problems'])} problem(s); first: "
              f"{'line ' + str(first_ln) + ': ' if first_ln else ''}{first}", file=sys.stderr)
        return 1
    note = ""
    if not res["has_claims_section"]:
        note = " (no Findings/Claims section found; only sources and URLs checked)"
    if res["unused_sources"] and not args.quiet:
        print(f"note: sources never cited in the text: "
              f"{', '.join('[' + str(n) + ']' for n in res['unused_sources'])}")
    print(f"cite_check: OK {path}: {res['claims']} claim(s) checked, {res['cited']} cited, "
          f"{res['inference']} marked inference, {res['sources']} source(s){note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
