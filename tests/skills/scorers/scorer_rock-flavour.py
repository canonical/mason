#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-flavour: is the rock built the way the case expects?

  chiselled       base: bare, build-base on the release, stage-packages all slices
  part-chiselled  base: bare, build-base on the release, the workload debs
                  staged whole (they have no slices)
  unchiselled     base: ubuntu@<release>, the workload debs staged whole
each condition is an equal share.
"""
from _lib import *


def score() -> float:
    c = case()
    if "flavour" not in c:
        raise NA
    doc = rock()
    if doc is None:
        return 0.0
    base = c["release"].replace("ubuntu-", "ubuntu@")
    sp = stage_packages(doc)
    if c["flavour"] == "chiselled":
        checks = [
            doc.get("base") == "bare",
            doc.get("build-base") == base,
            bool(sp) and all(SLICE.match(s) for s in sp),
        ]
    elif c["flavour"] == "part-chiselled":
        checks = [
            doc.get("base") == "bare",
            doc.get("build-base") == base,
            all(p in sp for p in c.get("workload", [])),
        ]
    else:
        checks = [doc.get("base") == base, all(p in sp for p in c.get("workload", []))]
    return sum(checks) / len(checks)


emit(score)
