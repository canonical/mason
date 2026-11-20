#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-source-build: a source-built rock builds the right thing -- a part with
the expected plugin (1/3), sourced from the expected repo (1/3), at the expected
tag (1/3). na unless the case names a plugin."""
from _lib import *


def score() -> float:
    c = case()
    if "plugin" not in c:
        raise NA
    best = 0.0
    for p in parts(rock()).values():
        s = (
            (p.get("plugin") == c["plugin"])
            + (c["source"] in str(p.get("source", "")))
            + (str(p.get("source-tag", "")) == str(c["source-tag"]))
        )
        best = max(best, s / 3)
    return best


emit(score)
