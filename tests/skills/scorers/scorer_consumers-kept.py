#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""consumers-kept: does the rewrite keep the slice names other slices use?

a knocked-out package's slices are dependencies of other slices files on the
branch (stage records them in <pkg>.consumers). renaming or dropping one breaks
every consumer. scored as the share of those names the produced file defines,
per target, averaged. na when nothing else depends on the package.
"""
from _lib import *


def score() -> float:
    vals = []
    for t in targets():
        f = OUT / f"{t}.consumers"
        if not f.exists():
            continue
        names = {n for n in f.read_text().split() if n.startswith(f"{t}_") and len(n) > len(t) + 1}
        if not names:
            continue
        doc = produced(t)
        have = {f"{t}_{name}" for name, _ in iter_bodies(doc)} if has_slices(doc) else set()
        vals.append(len(names & have) / len(names))
    if not vals:
        raise NA
    return sum(vals) / len(vals)


emit(score)
