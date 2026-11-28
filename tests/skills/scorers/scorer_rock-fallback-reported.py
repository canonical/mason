#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-fallback-reported: when a package has no slices and is staged as a
whole deb, the agent says so. na unless the case is such a fallback."""
from _lib import *

_PHRASES = (
    "no slices", "without slices", "whole deb",
    "unchiselled", "unchiseled", "not chiselled", "not chiseled", "without chisel",
)  # fmt: skip


def score() -> float:
    c = case()
    if not c.get("fallback"):
        raise NA
    t = transcript()
    hay = ("\n".join(t["texts"]) if t["parsed"] else t["raw"]).lower()
    return 1.0 if any(p in hay for p in _PHRASES) else 0.0


emit(score)
