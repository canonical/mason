#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""mason-stops-clean: did /mason stop after printing, loading nothing else?

the skill is explicit: print the usage block verbatim, then stop -- no other
skill, no scripts, no files. each violation class costs a third:
  - ran the chisel-slice orientation script (its output lines in the raw
    transcript, same detection as scorer_orientation-called)
  - ran chisel or rockcraft (a `chisel cut` / `try-cut` / `rockcraft` command,
    or one of the rock helpers)
  - wrote or edited any file
"""
from _lib import *


def score() -> float:
    t = transcript()
    commands = "\n".join(t["commands"]) if t["parsed"] else t["raw"]
    violations = (
        any(m in t["raw"] for m in ORIENTATION_MARKERS)
        + any(c in commands for c in ("chisel cut", "try-cut", "rockcraft ", "-rock.py"))
        + bool(t["writes"])
    )
    return 1.0 - violations / 3.0


emit(score)
