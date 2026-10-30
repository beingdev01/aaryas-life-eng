#!/usr/bin/env python3
"""design_spec_lint.py - refuse a DESIGN_SPEC.md that Lane B cannot build from.

Lane A (analyze) writes DESIGN_SPEC.md; Lane B builds from it and nothing else. A
vague spec is how invitations went wrong before, so this lint is the gate between
the two lanes.

  design_spec_lint.py work/aarambh-invite-spec/DESIGN_SPEC.md

Sections are `##` (or deeper) headings, matched by keyword:
  concept            the idea in at most 6 lines
  palette / colour   2+ exact #RRGGBB values, at most --max-colours distinct, and at
                     least one "#RRGGBB on #RRGGBB" text pair; every such pair anywhere
                     in the spec must pass WCAG AA (4.5:1, or 3:1 on a line that says
                     "large")
  typography / type  family plus at least one size in px, pt or rem
  layering           3+ ordered layers (numbered list, bullets, or an a > b > c chain)
  movement / motion  timings in seconds and a closing hold, or the word "static"
  audio / sound      direction that mentions fades, or says silent / no audio
  do not reuse       at least one item
Brand rules checked anywhere in the text (negated mentions such as "no blinking"
are fine): no blinking; the crest is the official CCSU PNG, never generated or
redrawn; no Code.SCRIET branding on an Aarambh invitation. Leftover template text
([fill: ...], TODO, TBD, lorem) fails.

Exit codes: 0 spec is buildable; 1 one or more problems; 2 file unreadable.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contrast_check  # noqa: E402

SECTION_KEYS = [
    ("do_not_reuse", r"do\s*n[o']?t\s*re-?use|must\s*not\s*be\s*re-?used|never\s*re-?use"
                     r"|not\s*to\s*be\s*re-?used|do-not-reuse"),
    ("palette", r"palette|colou?r"),
    ("typography", r"typograph|\btype\b|\bfonts?\b"),
    ("layering", r"layer"),
    ("movement", r"movement|motion|animation"),
    ("audio", r"audio|sound|music"),
    ("concept", r"concept|idea"),
]
REQUIRED = ["concept", "palette", "typography", "layering", "movement", "audio",
            "do_not_reuse"]
LABELS = {"concept": "concept", "palette": "palette (exact hex)", "typography": "typography",
          "layering": "layering order", "movement": "movement arc",
          "audio": "audio direction", "do_not_reuse": "do-not-reuse"}
HEX6 = re.compile(r"#[0-9a-fA-F]{6}\b")
HEX_SHORT = re.compile(r"#[0-9a-fA-F]{3}\b(?![0-9a-fA-F])")
PAIR = re.compile(r"(#[0-9a-fA-F]{6})\b\s+on\s+(#[0-9a-fA-F]{6})\b", re.I)
NEGATION = re.compile(r"\b(no|not|never|without|avoid|zero|nothing|don'?t|do not|must not|"
                      r"forbidden|banned|reject(?:ed)?)\b[^.\n]{0,40}$", re.I)
PLACEHOLDER = re.compile(r"\[fill[^\]]*\]|\bTODO\b|\bTBD\b|\blorem\b|\bipsum\b"
                         r"|<[a-z]+(?: [a-z]+)+>", re.I)


def split_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    lines = text.splitlines()
    heads = []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,6})\s+(.*\S)\s*$", line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    for n, (i, level, title) in enumerate(heads):
        end = len(lines)
        for j, lvl, _t in heads[n + 1:]:
            if lvl <= level:
                end = j
                break
        key = next((k for k, pat in SECTION_KEYS if re.search(pat, title, re.I)), None)
        if key and key not in sections:
            sections[key] = "\n".join(lines[i + 1:end]).strip()
    return sections


def positive_mentions(text: str, word: str, exclude: str = "") -> list[str]:
    """Lines where `word` appears without a negation shortly before it."""
    hits = []
    for line in text.splitlines():
        if exclude and line.strip() and line.strip() in exclude:
            continue
        for m in re.finditer(word, line, re.I):
            if not NEGATION.search(line[:m.start()]):
                hits.append(line.strip())
                break
    return hits


def lint(text: str, max_colours: int = 6) -> list[str]:
    problems = []
    sections = split_sections(text)
    for key in REQUIRED:
        body = sections.get(key)
        if body is None:
            problems.append(f"missing section: {LABELS[key]}")
        elif len(re.sub(r"\s+", " ", body)) < 30:
            problems.append(f"section '{LABELS[key]}' is too thin to build from")

    concept = sections.get("concept")
    if concept:
        lines = [ln for ln in concept.splitlines() if ln.strip()]
        if len(lines) > 6:
            problems.append(f"concept runs {len(lines)} lines; say it in 3 (max 6)")

    palette = sections.get("palette")
    if palette is not None:
        hexes = {h.lower() for h in HEX6.findall(palette)}
        if len(hexes) < 2:
            problems.append("palette needs at least 2 exact #RRGGBB values")
        if len(hexes) > max_colours:
            problems.append(f"palette has {len(hexes)} distinct colours (max {max_colours}); "
                            "the house rule is 2-3 colours plus neutrals")
        if HEX_SHORT.search(palette):
            problems.append("palette uses shorthand hex; write every colour as #RRGGBB")
        if not PAIR.search(palette):
            problems.append("palette states no text pair ('#RRGGBB on #RRGGBB'), so "
                            "contrast cannot be checked")
    for line in text.splitlines():
        for fg, bg in PAIR.findall(line):
            ratio = contrast_check.contrast_ratio(contrast_check.parse_colour(fg),
                                                  contrast_check.parse_colour(bg))
            need = 3.0 if re.search(r"\blarge\b", line, re.I) else 4.5
            if ratio < need:
                problems.append(f"{fg} on {bg} is {ratio:.2f}:1, below the {need}:1 "
                                "AA minimum")

    typo = sections.get("typography")
    if typo is not None and not re.search(r"\d+(\.\d+)?\s*(px|pt|rem)\b", typo, re.I):
        problems.append("typography gives no size (px, pt or rem)")

    layering = sections.get("layering")
    if layering is not None:
        items = [ln for ln in layering.splitlines()
                 if re.match(r"^\s*(\d+[.)]|[-*])\s+\S", ln)]
        chain = max((len(re.split(r"\s(?:>|->|→)\s", ln)) for ln in layering.splitlines()),
                    default=1)
        if len(items) < 3 and chain < 3:
            problems.append("layering order lists fewer than 3 layers in order")

    movement = sections.get("movement")
    if movement is not None and not re.search(r"\bstatic\b", movement, re.I):
        if not re.search(r"\d+(\.\d+)?\s*(s|sec|secs|seconds|ms)\b", movement, re.I):
            problems.append("movement arc has no timings in seconds")
        if not re.search(r"\bhold|\bheld\b", movement, re.I):
            problems.append("movement arc does not say how long the closing frame is held")

    audio = sections.get("audio")
    if audio is not None and not re.search(r"fade|silent|no audio|no music", audio, re.I):
        problems.append("audio direction says nothing about fades (or that it is silent)")

    dnr = sections.get("do_not_reuse")
    if dnr is not None and not re.search(r"^\s*(\d+[.)]|[-*])\s+\S", dnr, re.M):
        problems.append("do-not-reuse section has no listed items")

    dnr_text = dnr or ""
    for hit in positive_mentions(text, r"\bblink", exclude=dnr_text):
        problems.append(f"blinking is banned: '{hit[:80]}'")
    if re.search(r"\bcrest\b", text, re.I):
        if not re.search(r"\bofficial\b", text, re.I):
            problems.append("the crest is mentioned but never as the official CCSU PNG")
        for line in text.splitlines():
            if line.strip() and line.strip() in dnr_text:
                continue  # naming a rejected crest in do-not-reuse is the point
            if re.search(r"\bcrest\b", line, re.I):
                m = re.search(r"\b(generat\w*|redraw\w*|re-draw\w*|recreat\w*|illustrat\w*|"
                              r"trac(?:e|ed|ing)|ai[- ]made|ai[- ]generated|halo|glow)\b",
                              line, re.I)
                if m and not NEGATION.search(line[:m.start()]):
                    problems.append(f"crest must be the untouched official PNG: "
                                    f"'{line.strip()[:80]}'")
    if re.search(r"\baarambh\b|आरम्भ|आरंभ", text, re.I):
        for hit in positive_mentions(text, r"code\.?scriet", exclude=dnr_text):
            problems.append(f"no Code.SCRIET branding on an Aarambh invitation: "
                            f"'{hit[:80]}'")

    for m in PLACEHOLDER.finditer(text):
        problems.append(f"leftover template text: '{m.group(0)[:40]}'")
        break
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="design_spec_lint.py",
        description="Gate a DESIGN_SPEC.md: concept, exact hex palette with AA text pairs, "
                    "typography, layering order, movement arc, audio, do-not-reuse.")
    ap.add_argument("spec")
    ap.add_argument("--max-colours", type=int, default=6,
                    help="most distinct #RRGGBB values allowed in the palette (default 6)")
    args = ap.parse_args(argv)
    try:
        text = Path(args.spec).read_text(errors="replace")
    except OSError as exc:
        print(f"design_spec_lint: cannot read {args.spec}: {exc.strerror}", file=sys.stderr)
        return 2
    problems = lint(text, args.max_colours)
    sections = split_sections(text)
    for key in REQUIRED:
        print(f"{'found  ' if key in sections else 'MISSING'}  {LABELS[key]}")
    for p in problems:
        print(f"FAIL  {p}")
    if problems:
        print(f"design_spec_lint: {args.spec}: {len(problems)} problem(s), first: "
              f"{problems[0]}", file=sys.stderr)
        return 1
    print(f"PASS  {args.spec} is buildable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
