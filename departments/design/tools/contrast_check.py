#!/usr/bin/env python3
"""contrast_check.py - WCAG 2.x contrast gate for text colour pairs.

Two ways to use it:

  contrast_check.py 0f2a4a f7f4ec              one pair: text colour, background
  contrast_check.py '#7a6114' '#f7f4ec' e6c574 101f3d   several pairs
  contrast_check.py work/invite-build/index.html  every text pair found in the file

Colours on the command line may be written with or without '#'. Quote them if you
keep the '#', because an unquoted #... is a comment in bash.

Given an .html/.htm file, the tool builds the element tree, reads <style> blocks,
style="" attributes and linked local stylesheets, and runs a small cascade (tag,
.class, #id, :root, descendant and child selectors; specificity, source order,
!important, inline styles; inherited color, fill, font-size, font-weight, opacity and
custom properties). Every element that holds visible text is checked: its colour
against the nearest painted background behind it (its own, or an ancestor's; every
gradient stop, worst case wins). Gradient text (background-clip: text) is checked
stop by stop. Elements with display:none, aria-hidden="true" or hidden are skipped,
as decorative ornaments should be. Selectors with states, siblings, attributes or
pseudo-elements are not modelled and are skipped rather than guessed.

Given a bare .css file there is no DOM, so each rule's colour is paired with its own
background, or with the html/body/:root background (or --page-bg).

Large text (WCAG: >= 24px, or >= 18.66px and bold) is held to 3:1, other text to
4.5:1. Per-rule overrides, written as CSS comments inside the rule:
  /* contrast: ignore */       decorative element, not text (say why in the spec)
  /* contrast: large */        display type that is large even if the size is set elsewhere
  /* contrast: bg #101f3d */   the colour this text really sits on (text over a photo
                               or an absolutely positioned panel: give the worst area)

Exit codes: 0 every pair passes; 1 at least one pair is below its threshold;
2 bad input (unreadable file, odd number of colours, nothing to check).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

AA_NORMAL = 4.5
AA_LARGE = 3.0

NAMED = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0",
    "maroon": "#800000", "navy": "#000080", "gold": "#ffd700", "ivory": "#fffff0",
    "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080", "teal": "#008080",
    "beige": "#f5f5dc", "cream": "#fffdd0", "whitesmoke": "#f5f5f5",
    "darkgray": "#a9a9a9", "darkgrey": "#a9a9a9", "lightgray": "#d3d3d3",
    "lightgrey": "#d3d3d3", "dimgray": "#696969", "dimgrey": "#696969",
}
SKIP_VALUES = {"inherit", "initial", "unset", "currentcolor", "transparent", "none",
               "revert", "auto"}
PAGE_SELECTORS = {"html", "body", ":root", "html,body", "body,html"}

COLOUR_TOKEN = re.compile(
    r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{4}\b|#[0-9a-fA-F]{3}\b"
    r"|rgba?\([^)]*\)|\b(?:" + "|".join(sorted(NAMED, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)


class ContrastError(ValueError):
    """Bad input: a colour that cannot be parsed or a file that cannot be read."""


# ---------------------------------------------------------------- colour maths

def parse_colour(text: str, allow_bare_hex: bool = False) -> tuple:
    """Return (r, g, b, a) with r/g/b in 0-255 and a in 0-1."""
    raw = text.strip()
    low = raw.lower()
    if low in NAMED:
        low = NAMED[low]
    if allow_bare_hex and re.fullmatch(r"[0-9a-f]{3,8}", low) and len(low) in (3, 4, 6, 8):
        low = "#" + low
    if low.startswith("#"):
        h = low[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8) or not re.fullmatch(r"[0-9a-f]+", h):
            raise ContrastError(f"not a hex colour: {raw}")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (float(r), float(g), float(b), a)
    m = re.fullmatch(r"rgba?\((.*)\)", low)
    if m:
        body = m.group(1).replace("/", " ").replace(",", " ")
        parts = body.split()
        if len(parts) not in (3, 4):
            raise ContrastError(f"cannot read rgb() colour: {raw}")
        chans = []
        for p in parts[:3]:
            chans.append(float(p[:-1]) * 2.55 if p.endswith("%") else float(p))
        alpha = 1.0
        if len(parts) == 4:
            p = parts[3]
            alpha = float(p[:-1]) / 100 if p.endswith("%") else float(p)
        return (chans[0], chans[1], chans[2], max(0.0, min(1.0, alpha)))
    raise ContrastError(f"unsupported colour: {raw}")


def composite(top: tuple, bottom: tuple) -> tuple:
    """Alpha-composite `top` over an opaque `bottom`. Returns an opaque colour."""
    a = top[3]
    return tuple(top[i] * a + bottom[i] * (1 - a) for i in range(3)) + (1.0,)


def relative_luminance(c: tuple) -> float:
    def lin(v: float) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def contrast_ratio(fg: tuple, bg: tuple) -> float:
    """WCAG 2.x contrast ratio. fg is composited over bg if it has alpha."""
    bg_o = bg if bg[3] >= 1 else composite(bg, (255.0, 255.0, 255.0, 1.0))
    fg_o = composite(fg, bg_o) if fg[3] < 1 else fg
    l1, l2 = relative_luminance(fg_o), relative_luminance(bg_o)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def to_hex(c: tuple) -> str:
    return "#" + "".join(f"{int(round(max(0, min(255, v)))):02x}" for v in c[:3])


# ---------------------------------------------------------------- CSS reading

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
NON_RENDERED = {"head", "title", "script", "style", "template", "noscript", "meta", "link"}
SVG_TEXT = {"text", "tspan", "textpath"}
FONT_KEYWORDS = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18,
                 "x-large": 24, "xx-large": 32, "xxx-large": 48}


class Node:
    __slots__ = ("tag", "attrs", "parent", "children", "text")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs or {}, parent
        self.children, self.text = [], ""

    @property
    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def label(self):
        out = self.tag
        if self.attrs.get("id"):
            out += "#" + self.attrs["id"]
        if self.attrs.get("class"):
            out += "." + ".".join(self.attrs["class"].split())
        snippet = " ".join(self.text.split())[:32]
        return f'{out} "{snippet}"' if snippet else out


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.cur = self.root
        self.css: list[str] = []
        self.links: list[str] = []
        self._raw = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        node = Node(tag, a, self.cur)
        self.cur.children.append(node)
        if tag == "link" and "stylesheet" in a.get("rel", "").lower() and a.get("href"):
            self.links.append(a["href"])
        if tag in ("style", "script"):
            self._raw = tag
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        if tag == self._raw:
            self._raw = None
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        if self._raw == "style":
            self.css.append(data)
        elif self._raw is None:
            self.cur.text += data


def _prepare(css: str) -> str:
    css = re.sub(r"/\*\s*contrast:\s*([^*]*?)\s*\*/",
                 lambda m: " @@contrast:" + m.group(1).strip().replace(";", " ") + "@@ ", css)
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    css = re.sub(r"url\([^)]*\)", "url()", css)
    return css


def _declarations(body: str) -> tuple[dict, list]:
    directives = re.findall(r"@@contrast:([^@]*)@@", body)
    body = re.sub(r"@@contrast:[^@]*@@", " ", body)
    decls = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        name = name.strip().lower()
        important = bool(re.search(r"!\s*important\s*$", value, re.I))
        value = re.sub(r"\s*!\s*important\s*$", "", value.strip(), flags=re.I)
        if name:
            decls[name] = (value, important)
    return decls, [d.strip().lower() for d in directives]


def parse_rules(css: str) -> list[dict]:
    rules = []
    for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", _prepare(css)):
        selector_part = m.group(1)
        decls, directives = _declarations(m.group(2))
        directives += [d.strip().lower() for d in re.findall(r"@@contrast:([^@]*)@@",
                                                             selector_part)]
        selector = re.sub(r"@@contrast:[^@]*@@", " ", selector_part)
        selector = " ".join(selector.split())
        if selector.startswith("@") and not selector.startswith("@@"):
            continue  # @font-face, @page and similar carry no text colour
        if re.fullmatch(r"(?:[\d.]+%|from|to)(?:\s*,\s*(?:[\d.]+%|from|to))*", selector):
            continue  # keyframe steps are motion states, not resting text
        rules.append({"selector": selector, "decls": decls, "directives": directives})
    return rules


def resolve_vars(value: str, variables: dict, depth: int = 0) -> str:
    if depth > 12 or "var(" not in value:
        return value

    def repl(m):
        name, fallback = m.group(1), m.group(2)
        if name in variables:
            return resolve_vars(variables[name], variables, depth + 1)
        return fallback.strip() if fallback else "UNRESOLVED"

    out = re.sub(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)", repl, value)
    return resolve_vars(out, variables, depth + 1)


def colours_in(value: str) -> list[tuple]:
    found = []
    for tok in COLOUR_TOKEN.findall(value):
        try:
            found.append(parse_colour(tok))
        except (ContrastError, ValueError):
            continue
    return found


def font_px(value: str | None, parent_px: float = 16.0) -> float | None:
    if not value:
        return None
    v = value.strip().lower()
    if v in FONT_KEYWORDS:
        return float(FONT_KEYWORDS[v])
    if v == "smaller":
        return parent_px / 1.2
    if v == "larger":
        return parent_px * 1.2
    m = re.fullmatch(r"([\d.]+)\s*(px|pt|rem|em|%)", v)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    return {"px": n, "pt": n * 4 / 3, "rem": n * 16, "em": n * parent_px,
            "%": n * parent_px / 100}[unit]


def is_bold(weight: str) -> bool:
    w = (weight or "").strip().lower()
    if w in ("bold", "bolder"):
        return True
    return w.isdigit() and int(w) >= 700


def large_text(px: float | None, weight: str) -> bool:
    return px is not None and (px >= 24 or (px >= 18.66 and is_bold(weight)))


# ---------------------------------------------------------------- selectors

_COMPOUND = re.compile(r"^(\*|[a-zA-Z][\w-]*)?((?:[.#][\w-]+|:root)*)$")


def parse_selector(sel: str):
    """Selector -> list of (combinator, tag, ids, classes, is_root), or None if the
    selector uses features this checker does not model (states, siblings, attributes,
    pseudo-elements). Unmodelled rules are skipped rather than guessed."""
    sel = re.sub(r"\s*>\s*", " > ", sel.strip())
    if not sel or re.search(r"[+~\[]|::|:(?!root\b)", sel):
        return None
    parts, comb = [], " "
    for tok in sel.split():
        if tok == ">":
            comb = ">"
            continue
        m = _COMPOUND.match(tok)
        if not m:
            return None
        tag = (m.group(1) or "*").lower()
        rest = m.group(2) or ""
        ids = set(re.findall(r"#([\w-]+)", rest))
        classes = set(re.findall(r"\.([\w-]+)", rest))
        parts.append((comb, tag, ids, classes, ":root" in rest))
        comb = " "
    return parts or None


def specificity(parts) -> tuple:
    ids = sum(len(p[2]) for p in parts)
    cls = sum(len(p[3]) + (1 if p[4] else 0) for p in parts)
    tags = sum(1 for p in parts if p[1] != "*")
    return (ids, cls, tags)


def _compound_match(node: Node, part) -> bool:
    _comb, tag, ids, classes, is_root = part
    if tag != "*" and node.tag != tag:
        return False
    if is_root and node.tag != "html":
        return False
    if ids and node.attrs.get("id") not in ids:
        return False
    return classes <= node.classes


def matches(node: Node, parts) -> bool:
    if not _compound_match(node, parts[-1]):
        return False
    if len(parts) == 1:
        return True
    comb = parts[-1][0]
    anc = node.parent
    while anc is not None and anc.tag != "#document":
        if matches(anc, parts[:-1]):
            return True
        if comb == ">":
            return False
        anc = anc.parent
    return False


# ---------------------------------------------------------------- cascade

def _cascade(node: Node, compiled: list) -> tuple[dict, list]:
    best: dict[str, tuple] = {}
    directives: list[str] = []
    for order, (parts_list, decls, dirs) in enumerate(compiled):
        hit = None
        for parts in parts_list:
            if matches(node, parts):
                spec = specificity(parts)
                hit = spec if hit is None or spec > hit else hit
        if hit is None:
            continue
        directives += dirs
        for prop, (value, important) in decls.items():
            key = (1 if important else 0, 0) + hit + (order,)
            if prop not in best or key >= best[prop][1]:
                best[prop] = (value, key)
    style = node.attrs.get("style")
    if style:
        decls, dirs = _declarations(_prepare(style))
        directives += dirs
        for prop, (value, important) in decls.items():
            key = (1 if important else 0, 1, 0, 0, 0, 10 ** 9)
            if prop not in best or key >= best[prop][1]:
                best[prop] = (value, key)
    return {k: v[0] for k, v in best.items()}, directives


def _bg_layers(own: dict, variables: dict) -> list[tuple]:
    text = " ".join(resolve_vars(own[k], variables)
                    for k in ("background-color", "background", "background-image")
                    if k in own)
    return [c for c in colours_in(text) if c[3] > 0]


def _flatten(layers: list[tuple], under: list[tuple]) -> list[tuple]:
    out = []
    for top in layers:
        for low in under:
            out.append(composite(top, low) if top[3] < 1 else top)
    uniq = []
    for c in out:
        if c not in uniq:
            uniq.append(c)
    return uniq[:12]


def checks_from_html(path: Path, page_bg: str | None = None, force_large: bool = False,
                     minimum: float | None = None) -> list[dict]:
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        raise ContrastError(f"cannot read {path}: {exc.strerror}") from exc
    tree = _TreeBuilder()
    tree.feed(text)
    sheets = list(tree.css)
    for href in tree.links:
        if re.match(r"^[a-z]+://", href, re.I) or href.startswith("//"):
            continue  # remote stylesheets are never fetched
        local = (path.parent / href.split("?")[0]).resolve()
        if local.is_file():
            sheets.append(local.read_text(errors="replace"))
    compiled = []
    for css in sheets:
        for rule in parse_rules(css):
            parts_list = [p for p in (parse_selector(s) for s in rule["selector"].split(","))
                          if p]
            if parts_list:
                compiled.append((parts_list, rule["decls"], rule["directives"]))

    base = parse_colour(page_bg, allow_bare_hex=True) if page_bg else (255.0, 255.0, 255.0, 1.0)
    if base[3] < 1:
        base = composite(base, (255.0, 255.0, 255.0, 1.0))
    checks, seen = [], set()

    def walk(node: Node, inh: dict):
        own, dirs = _cascade(node, compiled)
        variables = dict(inh["vars"])
        for k, v in own.items():
            if k.startswith("--"):
                variables[k] = v

        def val(prop):
            return resolve_vars(own[prop], variables).strip() if prop in own else None

        if node.tag in NON_RENDERED or "ignore" in dirs:
            return
        if (val("display") or "") == "none" or node.attrs.get("aria-hidden") == "true" \
                or "hidden" in node.attrs:
            return
        state = dict(inh)
        state["vars"] = variables
        colour = val("color")
        if colour and colour.lower() not in SKIP_VALUES and "UNRESOLVED" not in colour:
            try:
                state["color"] = parse_colour(colour)
            except ContrastError:
                pass
        fill = val("fill") or node.attrs.get("fill")
        if fill and fill.lower() not in SKIP_VALUES and "UNRESOLVED" not in fill:
            try:
                state["fill"] = parse_colour(fill)
            except ContrastError:
                pass
        px = font_px(val("font-size"), inh["px"])
        if px is not None:
            state["px"] = px
        if val("font-weight"):
            state["weight"] = val("font-weight")
        try:
            op = val("opacity")
            if op is not None:
                state["opacity"] = inh["opacity"] * (float(op[:-1]) / 100 if op.endswith("%")
                                                     else float(op))
        except ValueError:
            pass
        if state["opacity"] <= 0.01:
            return
        if "large" in dirs:
            state["large"] = True
        layers = _bg_layers(own, variables)
        clip_text = any("text" in (val(k) or "").lower()
                        for k in ("background-clip", "-webkit-background-clip"))
        behind = inh["bg"]
        for d in dirs:
            m = re.match(r"bg\s+(\S+)", d)
            if m:
                behind = [parse_colour(m.group(1), allow_bare_hex=True)]
                state["bg"] = behind
        if layers and not clip_text:
            state["bg"] = _flatten(layers, behind)

        content = " ".join(node.text.split())
        if content:
            if clip_text and layers:
                fgs = layers
            elif node.tag in SVG_TEXT:
                fgs = [state["fill"]]
            else:
                fgs = [state["color"]]
            large = force_large or state["large"] or large_text(state["px"], state["weight"])
            threshold = minimum if minimum is not None else (AA_LARGE if large else AA_NORMAL)
            for fg in fgs:
                for bg in state["bg"]:
                    fg_eff = (fg[0], fg[1], fg[2], fg[3] * state["opacity"])
                    ratio = contrast_ratio(fg_eff, bg)
                    flat = to_hex(composite(fg_eff, bg))
                    key = (node.label(), flat, to_hex(bg))
                    if key in seen:
                        continue
                    seen.add(key)
                    checks.append({"label": node.label(), "fg": flat, "bg": to_hex(bg),
                                   "ratio": round(ratio, 2), "threshold": threshold,
                                   "large": large, "ok": ratio >= threshold})
        for child in node.children:
            walk(child, state)

    start = {"vars": {}, "color": (0.0, 0.0, 0.0, 1.0), "fill": (0.0, 0.0, 0.0, 1.0),
             "px": 16.0, "weight": "400", "opacity": 1.0, "large": False, "bg": [base]}
    for child in tree.root.children:
        walk(child, start)
    return checks


def checks_from_css(path: Path, page_bg: str | None = None, force_large: bool = False,
                    minimum: float | None = None) -> list[dict]:
    """A bare stylesheet has no DOM: pair each rule's colour with its own background,
    or with the html/body/:root background (or --page-bg)."""
    try:
        rules = parse_rules(path.read_text(errors="replace"))
    except OSError as exc:
        raise ContrastError(f"cannot read {path}: {exc.strerror}") from exc
    variables = {}
    for r in rules:
        for k, (v, _imp) in r["decls"].items():
            if k.startswith("--"):
                variables[k] = v
    page = parse_colour(page_bg, allow_bare_hex=True) if page_bg else None
    if page is None:
        for r in rules:
            if r["selector"].replace(" ", "").lower() in PAGE_SELECTORS:
                cols = _bg_layers({k: v for k, (v, _i) in r["decls"].items()}, variables)
                if cols:
                    page = cols[0]
    page = page or (255.0, 255.0, 255.0, 1.0)
    if page[3] < 1:
        page = composite(page, (255.0, 255.0, 255.0, 1.0))
    checks = []
    for r in rules:
        d = {k: v for k, (v, _i) in r["decls"].items()}
        dirs = r["directives"]
        if "ignore" in dirs:
            continue
        clip_text = any("text" in d.get(k, "").lower()
                        for k in ("background-clip", "-webkit-background-clip"))
        layers = _bg_layers(d, variables)
        if clip_text:
            if not layers:
                continue
            fgs, bgs = layers, [page]
        else:
            colour = resolve_vars(d.get("color", ""), variables).strip()
            if not colour or colour.lower() in SKIP_VALUES or "UNRESOLVED" in colour:
                continue
            try:
                fgs = [parse_colour(colour)]
            except ContrastError:
                continue
            bgs = _flatten(layers, [page]) if layers else [page]
        for directive in dirs:
            m = re.match(r"bg\s+(\S+)", directive)
            if m:
                bgs = [parse_colour(m.group(1), allow_bare_hex=True)]
        px = font_px(resolve_vars(d.get("font-size", ""), variables))
        large = force_large or "large" in dirs or large_text(px, d.get("font-weight", ""))
        threshold = minimum if minimum is not None else (AA_LARGE if large else AA_NORMAL)
        for fg in fgs:
            for bg in bgs:
                ratio = contrast_ratio(fg, bg)
                checks.append({"label": r["selector"] or "(rule)",
                               "fg": to_hex(composite(fg, bg)), "bg": to_hex(bg),
                               "ratio": round(ratio, 2), "threshold": threshold,
                               "large": large, "ok": ratio >= threshold})
    return checks


def checks_from_file(path: Path, page_bg: str | None = None, force_large: bool = False,
                     minimum: float | None = None) -> list[dict]:
    if path.suffix.lower() == ".css":
        return checks_from_css(path, page_bg, force_large, minimum)
    return checks_from_html(path, page_bg, force_large, minimum)


def checks_from_pairs(tokens: list[str], force_large: bool = False,
                      minimum: float | None = None) -> list[dict]:
    if len(tokens) % 2:
        raise ContrastError("colours must come in pairs: TEXT BACKGROUND")
    threshold = minimum if minimum is not None else (AA_LARGE if force_large else AA_NORMAL)
    checks = []
    for i in range(0, len(tokens), 2):
        fg = parse_colour(tokens[i], allow_bare_hex=True)
        bg = parse_colour(tokens[i + 1], allow_bare_hex=True)
        ratio = contrast_ratio(fg, bg)
        checks.append({"label": f"pair {i // 2 + 1}", "fg": to_hex(fg), "bg": to_hex(bg),
                       "ratio": round(ratio, 2), "threshold": threshold,
                       "large": force_large, "ok": ratio >= threshold})
    return checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="contrast_check.py",
        description="WCAG 2.x contrast gate. Fails if any text pair is below 4.5:1 "
                    "(3:1 for large text or with --large).",
        epilog="Examples:  contrast_check.py 0f2a4a f7f4ec   |   "
               "contrast_check.py index.html --page-bg 101f3d")
    ap.add_argument("inputs", nargs="+",
                    help="colour pairs (TEXT BACKGROUND ...) and/or .html/.css files")
    ap.add_argument("--large", action="store_true",
                    help="treat every pair as large text (3:1 threshold)")
    ap.add_argument("--min", type=float, default=None,
                    help="custom minimum ratio for every pair (overrides 4.5 / 3)")
    ap.add_argument("--page-bg", default=None,
                    help="page background for rules without their own background")
    ap.add_argument("--json", action="store_true", help="print results as JSON")
    ap.add_argument("--all", action="store_true",
                    help="print every pair, not just the worst pair per element")
    args = ap.parse_args(argv)

    checks, colour_tokens, files = [], [], []
    for item in args.inputs:
        p = Path(item)
        if p.suffix.lower() in (".html", ".htm", ".css") or p.is_file():
            files.append(p)
        else:
            colour_tokens.append(item)
    try:
        if colour_tokens:
            checks += checks_from_pairs(colour_tokens, args.large, args.min)
        for f in files:
            if not f.is_file():
                raise ContrastError(f"no such file: {f}")
            found = checks_from_file(f, args.page_bg, args.large, args.min)
            if not found:
                raise ContrastError(f"no text colour declarations found in {f}; "
                                    "nothing was checked")
            for c in found:
                c["source"] = str(f)
            checks += found
    except ContrastError as exc:
        print(f"contrast_check: {exc}", file=sys.stderr)
        return 2

    failed = [c for c in checks if not c["ok"]]
    if args.json:
        print(json.dumps({"checks": checks, "failed": len(failed)}, indent=2))
    else:
        shown = checks
        if not args.all:
            worst: dict = {}
            counts: dict = {}
            for c in checks:
                key = (c.get("source"), c["label"])
                counts[key] = counts.get(key, 0) + 1
                if key not in worst or c["ratio"] < worst[key]["ratio"]:
                    worst[key] = c
            shown = list(worst.values())
        for c in shown:
            mark = "PASS" if c["ok"] else "FAIL"
            size = "large" if c["large"] else "normal"
            n = 1 if args.all else counts[(c.get("source"), c["label"])]
            more = f"  (worst of {n})" if n > 1 else ""
            print(f"{mark}  {c['ratio']:>5.2f}:1 (need {c['threshold']}:1, {size})  "
                  f"{c['fg']} on {c['bg']}  {c['label']}{more}")
        print(f"{len(checks) - len(failed)} of {len(checks)} pairs pass WCAG AA")
    if failed:
        worst = min(failed, key=lambda c: c["ratio"])
        print(f"contrast_check: {len(failed)} of {len(checks)} text pairs below AA "
              f"(worst {worst['ratio']}:1 {worst['fg']} on {worst['bg']} at "
              f"{worst['label']})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
