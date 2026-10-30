"""Time-limited free offers, verified rather than assumed.

Most free lanes prove their tier in the model identifier (`:free`, `-free`). Qoder's
Qwen3.8-Flash does not: it is free only because of an offer that "will announce the end
date on this page in advance". A name allowlist would therefore turn into a paid path
silently on the day the offer ends.

So the offer page itself is the gate. It is fetched at most every 24 hours; the lane is
allowed only while every required phrase is still on the page. Any change, any fetch
failure, or a stale check refuses the lane. It fails closed.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

from . import util

OFFERS = {
    "qodercli:Qwen3.8-Flash": {
        "url": "https://docs.qoder.com/events/flashoffer",
        "must_contain": ["Qwen3.8-Flash", "remains free", "0.0",
                         "We will announce the end date"],
        "runtime_model_keys": {"qfmodel"},
    },
}

STATE = Path(os.environ.get("ENG_OFFER_STATE", str(util.HOME / "state" / "free-offers")))
MAX_AGE_SEC = 24 * 3600


def _state_path(key: str) -> Path:
    return STATE / (re.sub(r"[^A-Za-z0-9.-]+", "_", key) + ".json")


def fetch_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 engctl-offer-check"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", "replace")
    return re.sub(r"<[^>]+>", " ", html)


def check(key: str, fetcher=fetch_text) -> dict:
    """Fetch the offer page now and record the verdict."""
    offer = OFFERS[key]
    result = {"key": key, "url": offer["url"], "checked_at": time.time(),
              "checked_at_utc": util.utc_now(), "ok": False, "missing": [], "error": None}
    try:
        text = fetcher(offer["url"])
    except Exception as exc:                                   # noqa: BLE001 - fail closed
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    else:
        result["missing"] = [p for p in offer["must_contain"] if p not in text]
        result["ok"] = not result["missing"]
    STATE.mkdir(parents=True, exist_ok=True)
    _state_path(key).write_text(json.dumps(result, indent=2))
    return result


def is_open(key: str, refresh: bool = True, fetcher=fetch_text) -> tuple[bool, str]:
    """True only if the offer was verified as still open within the last 24 hours."""
    if key not in OFFERS:
        return False, f"no verified offer is registered for {key}"
    path = _state_path(key)
    state = None
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = None
    fresh = state and (time.time() - float(state.get("checked_at", 0))) < MAX_AGE_SEC
    if not fresh and refresh:
        state = check(key, fetcher)
        fresh = True
    if not state or not fresh:
        return False, f"offer check for {key} is stale or missing"
    if state.get("ok"):
        return True, f"offer verified open at {state.get('checked_at_utc')}"
    reason = state.get("error") or f"page no longer says: {state.get('missing')}"
    return False, f"offer for {key} not verified: {reason}"


def runtime_model_keys(key: str) -> set:
    return set(OFFERS.get(key, {}).get("runtime_model_keys", set()))
