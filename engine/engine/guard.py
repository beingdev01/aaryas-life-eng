"""Free-lane guard. A hard precondition, not a guideline.

Owner rule, 2026-10-30, absolute: no paid model, tier, or credit-spending call, ever.
Not as a fallback, not for a hard part, not via an "auto" or "cheapest model" selector.

A rule written in a charter gets ignored by the next run. This module makes the rule a
precondition that fails the run instead, and it also closes the silent paid paths that
were found on this VM:

- `qoder-runner.sh:61` switches to paid Qwen3.8-Max when an issue title contains
  `[max]`, `heavy`, `complex`, or `architecture` during off-peak hours. Titles emitted
  by the engine are therefore sanitised.
- OpenCode calls paid `gpt-5.4-nano` to generate a session title unless `--title` is
  passed, so passing it is mandatory in `lanes.invoke`.
- A "cheapest platform model" selector is a paid path whenever the cheapest model is
  not free, so `auto`-style identifiers are rejected outright.
"""

from __future__ import annotations

import re

# A model is acceptable only if its identifier proves the free tier.
FREE_SUFFIXES = (":free", "-free")
FREE_EXACT_SEGMENTS = ("/free",)

# Identifiers that are paid, or that resolve to an unknown tier at call time.
DENY_SUBSTRINGS = (
    "max", "ultimate", "premium", "turbo-pro", "-pro", "_pro",
    "gpt-5", "gpt-4", "o3-", "o4-", "claude", "gemini", "grok",
    "sonnet", "opus", "haiku",
    "auto",          # "cheapest platform model" is a paid path when nothing free is cheapest
)

# Reasoning-effort variants are free on a free model, except this one: the brief warns
# that `max` triggers tier escalation in the Paperclip runners.
DENY_VARIANTS = ("max",)

# Keywords that trigger paid model selection downstream. Never emit them in a title.
TRIGGER_WORDS = ("[max]", "max", "heavy", "complex", "architecture")


class PaidModelRefused(RuntimeError):
    """Raised instead of ever issuing a call that might spend credits."""


def is_free_model(model: str) -> tuple[bool, str]:
    m = (model or "").strip().lower()
    if not m:
        return False, "empty model identifier"

    for bad in DENY_SUBSTRINGS:
        if bad in m:
            # ":free" wins only when the deny hit is the literal free marker itself.
            if bad == "-pro" and m.endswith(("-free", ":free")):
                continue
            return False, f"identifier contains {bad!r}, which is not a proven free tier"

    if m.endswith(FREE_SUFFIXES) or any(m.endswith(s) for s in FREE_EXACT_SEGMENTS):
        return True, "identifier ends with a free-tier marker"

    return False, ("identifier carries no free-tier marker (expected a ':free' or "
                   "'-free' suffix). Unverified tiers are refused rather than tried.")


def check_variant(variant: str | None) -> tuple[bool, str]:
    if not variant:
        return True, "no variant"
    v = variant.strip().lower()
    if v in DENY_VARIANTS:
        return False, f"variant {v!r} can escalate tier"
    return True, "variant allowed"


def sanitize_title(title: str) -> str:
    """Strip downstream paid-escalation triggers from any title the engine emits."""
    out = title or "eng"
    out = out.replace("[max]", "").replace("[MAX]", "")
    for word in ("heavy", "complex", "architecture", "max"):
        out = re.sub(rf"\b{word}\b", {"heavy": "large", "complex": "multi-part",
                                      "architecture": "structure",
                                      "max": "full"}[word], out, flags=re.I)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:60] or "eng"


def is_free_lane(lane, refresh: bool = True) -> tuple[bool, str]:
    """The lane-level decision. Identifier proof for most CLIs; a verified offer for qodercli.

    qodercli is held to a narrower rule than the identifier check: one exact model, read
    only, and only while its offer page is verified open (see offers.py). Every other
    qodercli model — Auto, Ultimate, Qwen3.8-Max and the rest — is refused outright.
    """
    if lane.cli == "qodercli":
        from . import offers
        key = f"qodercli:{lane.model}"
        if key not in offers.OFFERS:
            return False, (f"qodercli model {lane.model!r} has no verified free offer; only "
                           f"offer-verified models may run on qodercli")
        ok, why = offers.is_open(key, refresh=refresh)
        return ok, why
    return is_free_model(lane.model)


def audit_lanes(lanes: list, refresh: bool = True) -> dict:
    """Classify every lane. Enabled + not provably free is a hard stop."""
    verdicts, violations = [], []
    for lane in lanes:
        free, why = is_free_lane(lane, refresh=refresh) if lane.enabled else is_free_lane(
            lane, refresh=False)
        var_ok, var_why = check_variant(getattr(lane, "variant", None))
        entry = {"lane": lane.id, "model": lane.model, "enabled": lane.enabled,
                 "free": free, "reason": why, "variant_ok": var_ok,
                 "variant_reason": var_why}
        verdicts.append(entry)
        if lane.enabled and not (free and var_ok):
            violations.append(entry)
    return {"verdicts": verdicts, "violations": violations,
            "enabled_free": sum(1 for v in verdicts if v["enabled"] and v["free"]),
            "enabled_total": sum(1 for v in verdicts if v["enabled"])}


def enforce(lanes: list) -> dict:
    """Call before any dispatch. Raises rather than risking a paid call.

    A lane that fails its check is refused. If it is an offer lane whose offer could
    not be verified, the run proceeds without it rather than failing: losing one lane
    is acceptable, spending is not.
    """
    audit = audit_lanes(lanes)
    hard = [v for v in audit["violations"]
            if not str(v.get("reason", "")).startswith(("offer ", "no verified"))]
    if hard:
        detail = "; ".join(f"{v['lane']} ({v['model']}): {v['reason']}" for v in hard)
        raise PaidModelRefused(
            "refusing to start: enabled lane(s) are not provably free — " + detail
            + ". Disable the lane or replace the model with a verified free identifier."
        )
    for v in audit["violations"]:
        for lane in lanes:
            if lane.id == v["lane"]:
                lane.enabled = False
                lane.notes = f"auto-disabled this run: {v['reason']}"
    if sum(1 for ln in lanes if ln.enabled) == 0:
        raise PaidModelRefused("refusing to start: no enabled free lane in the pool")
    return audit
