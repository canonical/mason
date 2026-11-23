#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-packed: the agent packed the rock. 1.0 a pack ran (the skill's
pack-rock or rockcraft pack) and left a .rock; 0.5 a pack ran but left none;
0 never packed."""
from _lib import *


def score() -> float:
    case()
    return packed()


emit(score)
