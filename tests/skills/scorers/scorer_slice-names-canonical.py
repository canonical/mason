#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""slice-names-canonical: no slice name the conventions reject (bin, lib,
configs, dev, all, license, notice, bare rules). base-files is the one package
whose `bin` and `lib` slices are right: they build the directory trees."""
from _lib import *


def score() -> float:
    def f(t: str) -> float:
        doc = produced(t)
        if not has_slices(doc):
            return 0.0
        names = [n for n in doc["slices"] if isinstance(n, str)]
        allowed = {"bin", "lib"} if doc.get("package") == "base-files" else set()
        bad = [n for n in names if n in REJECTED_SLICE_NAMES - allowed]
        return 1.0 - len(bad) / len(names) if names else 0.0
    return avg(f)

emit(score)
