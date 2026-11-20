#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-fault-fixed: the injected fault is gone from rockcraft.yaml.

  slice          the misnamed slice is gone and the right one is staged (1.0);
                 anything else, including dropping the workload, scores 0
  add-slice      the missing slice is now staged (1.0)
  build-package  the tool the scriptlet runs is in build-packages (1.0); the
                 scriptlet no longer runs it -- worked around -- (0.5)
"""
from _lib import *


def score() -> float:
    f = case().get("fault")
    if not isinstance(f, dict):
        raise NA
    doc = rock()
    if doc is None:
        return 0.0
    used = slices_used(doc)
    if f["kind"] == "slice":
        return 1.0 if f["bad"] not in used and f["good"] in used else 0.0
    if f["kind"] == "add-slice":
        return 1.0 if f["good"] in used else 0.0
    pkg = f["package"]
    if any(pkg in (p.get("build-packages") or []) for p in parts(doc).values()):
        return 1.0
    p = parts(doc).get(f["part"], {})
    runs = any(f"{pkg} " in str(v) for k, v in p.items() if str(k).startswith("override-"))
    return 0.0 if runs else 0.5


emit(score)
