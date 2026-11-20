#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-fix-committed: in a git project the fix is committed. a commit beyond the
staged one (1/2), and rockcraft.yaml left with no uncommitted change (1/2);
0 with no new commit."""
from _lib import *


def score() -> float:
    if "fault" not in case():
        raise NA
    log = OUT / "git-log.txt"
    commits = len(log.read_text().splitlines()) if log.exists() else 0
    if commits <= 1:
        return 0.0
    status = OUT / "git-status.txt"
    dirty = status.exists() and "rockcraft.yaml" in status.read_text()
    return (1 + (not dirty)) / 2


emit(score)
