#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""mutate-paths: mutate read/write paths match ground truth (jaccard).

na when the agent wrote no mutate at all: mutate-present already scores that,
and one miss shouldn't count twice."""
from _lib import *


def score() -> float:
    def f(t: str) -> float | None:
        exp_map = mutate_map(expected(t))
        if not exp_map:
            return 1.0
        act_map = mutate_map(produced(t))
        if not act_map:
            return None
        exp_paths = set().union(*(mutate_paths(s) for s in exp_map.values()))
        act_paths = set().union(*(mutate_paths(s) for s in act_map.values()))
        if not exp_paths and not act_paths:
            return 1.0
        union = exp_paths | act_paths
        return len(exp_paths & act_paths) / len(union) if union else 0.0
    vals = [v for v in (f(t) for t in targets()) if v is not None]
    if not vals:
        raise NA
    return sum(vals) / len(vals)

emit(score)
