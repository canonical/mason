#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""copyright-essential: the package's copyright slice is a top-level essential.

`essential` is a list on v1 manifests and a map on v3; both count.
"""
from _lib import *


def score() -> float:
    def f(t: str) -> float:
        doc = produced(t)
        if not isinstance(doc, dict):
            return 0.0
        pkg = doc.get("package") if isinstance(doc.get("package"), str) else t
        essential = doc.get("essential")
        if not isinstance(essential, (list, dict)):
            return 0.0
        return 1.0 if f"{pkg}_copyright" in essential else 0.0
    return avg(f)


emit(score)
