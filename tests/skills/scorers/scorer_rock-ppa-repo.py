#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-ppa-repo: a PPA rock declares the PPA in package-repositories (1/2)
on an ubuntu@ base, since chisel cannot read PPAs (1/2). na unless the case
names a ppa."""
from _lib import *


def score() -> float:
    c = case()
    if "ppa" not in c:
        raise NA
    doc = rock()
    if doc is None:
        return 0.0
    repos = doc.get("package-repositories") or []
    has = any(isinstance(r, dict) and str(r.get("ppa", "")).removeprefix("ppa:") == c["ppa"] for r in repos)
    base = c["release"].replace("ubuntu-", "ubuntu@")
    return (has + (doc.get("base") == base)) / 2


emit(score)
