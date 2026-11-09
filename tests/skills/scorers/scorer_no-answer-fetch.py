#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""no-answer-fetch: no request for chisel-releases slices or tests came back
with content. 0 marks a contaminated pair: the egress policy let an answer
through. orientation's info/refs and raw chisel.yaml reads are not answers."""
import json
import re

from _lib import *

_ANSWER = re.compile(
    r"^(github\.com/[^/]+/chisel-releases(?!\.git/info/refs)[/.]"
    r"|raw\.githubusercontent\.com/[^/]+/chisel-releases/.*/(slices|tests)/"
    r"|codeload\.github\.com/[^/]+/chisel-releases"
    r"|api\.github\.com/repos/[^/]+/chisel-releases)",
    re.IGNORECASE,
)
# mirrors the proxy sees only as tunnels: any that got through is a fetch.
_MIRRORS = {"cdn.jsdelivr.net", "cdn.statically.io", "raw.githack.com", "gitcdn.link"}


def score() -> float:
    log = OUT / "egress.log"
    if not log.exists():
        raise NA
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not ev.get("allowed"):
            continue
        if ev.get("host") in _MIRRORS:
            return 0.0
        if 200 <= (ev.get("status") or 0) < 300 and _ANSWER.match(ev.get("url") or ""):
            return 0.0
    return 1.0


emit(score)
