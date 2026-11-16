#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""mutate-present: are the files ground truth's mutate scripts generate also
produced?

ground truth uses mutate where a maintainer script would create files (e.g.
/etc/passwd from the shipped masters). what matters is that the file exists in
the cut, not how: a produced path counts when its own mutate writes it, or it
is a `copy:` / `symlink:` entry, or a non-placeholder `text:`. scored as the
share of ground truth's written paths covered. na when ground truth writes
nothing.
"""
import re

from _lib import *

_WRITE = re.compile(r'content\.write\s*\(\s*["\']([^"\']+)["\']')


def _written(doc) -> set[str]:
    return {p for s in mutate_map(doc).values() for p in _WRITE.findall(s)}


def _provided(doc) -> set[str]:
    out = set(_written(doc))
    for _, path, entry in iter_contents(doc):
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if "copy" in entry or "symlink" in entry or (isinstance(text, str) and text.strip() and text != "FIXME"):
            out.add(path)
    return out


def score() -> float:
    vals = []
    for t in targets():
        want = _written(expected(t))
        if not want:
            continue
        got = _provided(produced(t)) if has_slices(produced(t)) else set()
        vals.append(len(want & got) / len(want))
    if not vals:
        raise NA
    return sum(vals) / len(vals)


emit(score)
