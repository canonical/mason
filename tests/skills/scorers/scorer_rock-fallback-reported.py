#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-fallback-reported: when slices are missing and the rock goes
unchiseled, the agent says so. na unless the case is such a fallback."""
from _lib import *

_PHRASES = ("unchiselled", "unchiseled", "not chiselled", "not chiseled", "without chisel")


def score() -> float:
    c = case()
    if not c.get("fallback"):
        raise NA
    t = transcript()
    hay = ("\n".join(t["texts"]) if t["parsed"] else t["raw"]).lower()
    return 1.0 if any(p in hay for p in _PHRASES) else 0.0


emit(score)
