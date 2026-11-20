#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-version: version matches the case -- `version` exactly (XX.YY for an
archive package, the pinned tag for a source build) or `version-pattern` (a
moving target such as a PPA). 1.0 as a quoted string; 0.5 the right value but
not a string (a yaml float); 0 otherwise."""
import re

from _lib import *


def score() -> float:
    c = case()
    if "version" not in c and "version-pattern" not in c:
        raise NA
    doc = rock()
    if doc is None or "version" not in doc:
        return 0.0
    v = doc["version"]

    def ok(x: str) -> bool:
        return x == c["version"] if "version" in c else bool(re.match(c["version-pattern"], x))

    if isinstance(v, str):
        return 1.0 if ok(v) else 0.0
    return 0.5 if ok(str(v)) else 0.0


emit(score)
