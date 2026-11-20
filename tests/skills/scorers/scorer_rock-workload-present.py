#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-workload-present: the rock carries the workload. each expected slice
(chiselled) or deb (unchiselled) is staged; na when the case names none (a
source build, whose workload is its part)."""
from _lib import *


def score() -> float:
    c = case()
    if not c.get("workload"):
        raise NA
    doc = rock()
    if doc is None:
        return 0.0
    have = set(stage_packages(doc)) | slices_used(doc)
    return sum(w in have for w in c["workload"]) / len(c["workload"])


emit(score)
