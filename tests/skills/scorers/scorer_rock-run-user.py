#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-run-user: the rock runs as the non-root _daemon_ user."""
from _lib import *


def score() -> float:
    case()
    doc = rock()
    return 1.0 if doc is not None and doc.get("run-user") == "_daemon_" else 0.0


emit(score)
