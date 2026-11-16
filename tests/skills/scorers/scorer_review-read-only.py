#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""review-read-only: did the reviewer leave the checkout's files alone?

the reviewer skill is read-only. 0.0 when a write/edit-style tool touched a
path under slices/ or tests/, or a bash command redirected into one, else 1.0.
"""
import re

from _lib import *

_REDIRECT = re.compile(r"(>>?|\btee\b|\bsed\s+-i)\s*\S*(slices|tests)/")


def score() -> float:
    for c in calls()["calls"]:
        if any("slices/" in p or "tests/" in p for p in c["paths"]):
            return 0.0
        if c["command"] and _REDIRECT.search(c["command"]):
            return 0.0
    return 1.0


emit(score)
