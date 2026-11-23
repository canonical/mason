#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-service: Pebble services match the workload.

service: a service exists (1/3) with override: replace (1/3) whose command runs
the expected absolute binary (1/3). CLI: no services (1.0).
"""
from _lib import *


def score() -> float:
    c = case()
    if "service" not in c:
        raise NA
    doc = rock()
    if doc is None:
        return 0.0
    svcs = doc.get("services") if isinstance(doc.get("services"), dict) else {}
    if not c["service"]:
        return 0.0 if svcs else 1.0
    bodies = [s for s in svcs.values() if isinstance(s, dict)]
    if not bodies:
        return 0.0
    replace = any(s.get("override") == "replace" for s in bodies)
    binary = any(str(s.get("command", "")).split()[:1] == [c["binary"]] for s in bodies)
    return (1 + replace + binary) / 3


emit(score)
