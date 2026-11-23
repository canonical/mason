#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-no-collateral: the fix is targeted. against the known-good file, the
fraction of top-level keys and parts left identical: a minimal fix scores 1.0;
rebasing, dropping parts or switching the user costs a share per item."""
from _lib import *


def score() -> float:
    case()
    exp = rock_file("rockcraft.expected.yaml")
    if exp is None:
        raise NA
    got = rock()
    if got is None:
        return 0.0
    items = [(exp[k], got.get(k)) for k in exp if k != "parts"]
    gp = parts(got)
    items += [(p, gp.get(n)) for n, p in parts(exp).items()]
    return sum(a == b for a, b in items) / len(items)


emit(score)
