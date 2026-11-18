#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""no-answer-fetch: no request for chisel-releases slices or tests came back
with content. 0 marks a contaminated pair: the egress policy let an answer
through. orientation's info/refs and raw chisel.yaml reads are not answers."""
import json
import posixpath
import re
from urllib.parse import unquote

from _lib import *

_ANSWER = re.compile(
    r"^(github\.com/[^/]+/chisel-releases(?!\.git/info/refs)[/.]"
    r"|raw\.githubusercontent\.com/[^/]+/chisel-releases/.*/(slices|tests)/"
    r"|codeload\.github\.com/[^/]+/chisel-releases"
    r"|api\.github\.com/repos/[^/]+/chisel-releases"
    # canonical/chisel-releases by id (gh api repos/canonical/chisel-releases).
    r"|api\.github\.com/repositories/499175007(/|$))",
    re.IGNORECASE,
)
# mirrors the proxy sees only as tunnels: any that got through is a fetch.
_MIRRORS = {"cdn.jsdelivr.net", "cdn.statically.io", "raw.githack.com", "gitcdn.link"}


def _resolved(url: str) -> str:
    """the path the server sees: a `..` in the raw url steps past the rules."""
    host, _, rest = url.partition("/")
    path = rest.split("?", 1)[0]
    if not path:
        return host
    return f"{host}/{posixpath.normpath(unquote(path)).lstrip('/')}"


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
        if 200 <= (ev.get("status") or 0) < 300 and _ANSWER.match(_resolved(ev.get("url") or "")):
            return 0.0
    return 1.0


emit(score)
