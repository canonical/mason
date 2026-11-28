#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""review-read-only: did the reviewer leave the checkout's files alone?

the reviewer skill is read-only. 0.0 when a write/edit-style tool touched a
path under the checkout's slices/ or tests/, or a bash command redirected or
sed -i'd into one, else 1.0. a scratch copy elsewhere (/tmp/rel/slices/) is
fine: the agent's cwd is the checkout, at /workspace in the sandbox, and a
relative path stops counting after a `cd` elsewhere in the same command.
"""
import re

from _lib import *

_TARGET = r"(/workspace/|\./)?(?:slices|tests)/"
_REDIRECT = re.compile(r"(?:>>?|\btee(?:\s+-a)?)\s*" + _TARGET)
_SED_I = re.compile(r"\bsed\s+-\w*i[^|;&]*\s" + _TARGET)
_CD = re.compile(r"^\s*cd\s+(\S+)")


def _writes_checkout(cmd: str) -> bool:
    home = True
    for seg in re.split(r"&&|\|\||;|\n", cmd):
        m = _CD.match(seg)
        if m:
            home = m.group(1).strip("\"'").rstrip("/") in ("/workspace", ".", "~+")
            continue
        for rx in (_REDIRECT, _SED_I):
            for hit in rx.finditer(seg):
                if hit.group(1) == "/workspace/" or home:
                    return True
    return False
_PREFIXES = ("slices/", "tests/", "./slices/", "./tests/", "/workspace/slices/", "/workspace/tests/")


def score() -> float:
    for c in calls()["calls"]:
        if any(p.startswith(_PREFIXES) for p in c["paths"]):
            return 0.0
        if _writes_checkout(c["command"] or ""):
            return 0.0
    return 1.0


emit(score)
