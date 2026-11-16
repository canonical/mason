#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""port-key: did the port make the adaptations its task's key.yaml requires?

key.yaml, beside a porter task:
  present    content paths some slice must declare
  absent     content paths no slice may declare (gone from the target package)
  essential  slices some slice (or the top level) must depend on
  absent-essential  slices no slice may depend on (a dependency the target dropped)
  only       true: no content path beyond `present` (a port that needs no change)
each item is one check, the score is the share passed. paths match as globs
both ways, so `/usr/lib/*-linux-*/libssl.so.*` and a spelled-out triplet agree.
na without a key.
"""
import os
from fnmatch import fnmatchcase
from pathlib import Path

import yaml
from _lib import *


def _key() -> dict:
    p = Path(os.environ.get("PATS_SCORED_TASK_DIR", "")) / "key.yaml"
    if not p.is_file():
        raise NA
    return yaml.safe_load(p.read_text()) or {}


def _match(a: str, b: str) -> bool:
    return a == b or fnmatchcase(a, b) or fnmatchcase(b, a)


def _essentials(doc) -> set[str]:
    out: set[str] = set()

    def add(e):
        out.update(e if isinstance(e, (list, dict)) else [])

    add(doc.get("essential") or [])
    for body in (doc.get("slices") or {}).values():
        add((body or {}).get("essential") or [])
    return out


def score() -> float:
    key = _key()
    doc = produced(TASK)
    if not has_slices(doc):
        return 0.0
    paths = content_paths(doc)
    deps = _essentials(doc)
    checks = [any(_match(p, k) for p in paths) for k in key.get("present") or []]
    checks += [not any(_match(p, k) for p in paths) for k in key.get("absent") or []]
    checks += [k in deps for k in key.get("essential") or []]
    checks += [k not in deps for k in key.get("absent-essential") or []]
    if key.get("only"):
        allowed = key.get("present") or []
        checks.append(all(any(_match(p, k) for k in allowed) for p in paths))
    return sum(checks) / len(checks) if checks else 1.0


emit(score)
