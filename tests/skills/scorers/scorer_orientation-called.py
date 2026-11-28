#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""orientation-called: did the agent run scripts/orientation.py before anything else?

  0.0   orientation never ran (no bash command naming it)
  0.5   a command ran it but none printed orientation's output (e.g. wrong path)
  0.75  it ran, but only after the agent first wrote a slices file
  1.0   it ran, before any write to a slices file

reading the skill (which names the script) is not an attempt: only commands
count, and only their own output counts as success. old plain-text transcripts
fall back to a scan of the raw log.
"""
from _lib import *

_SUCCESS_MARKERS = ORIENTATION_MARKERS


def _writes_slice(c: dict) -> bool:
    return any("slices/" in p for p in c["paths"])


def _score_calls(cs: list[dict]) -> float:
    attempted = wrote = False
    for c in cs:
        if "orientation" in c["command"]:
            attempted = True
            if any(m in c["output"] for m in _SUCCESS_MARKERS):
                return 0.75 if wrote else 1.0
        if _writes_slice(c):
            wrote = True
    return 0.5 if attempted else 0.0


def _score_text() -> float:
    text = raw_text()
    if "orientation" not in text:
        return 0.0
    return 1.0 if any(m in text for m in _SUCCESS_MARKERS) else 0.5


def score() -> float:
    c = calls()
    return _score_calls(c["calls"]) if c["parsed"] else _score_text()


emit(score)
