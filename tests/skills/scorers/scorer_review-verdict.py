#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""review-verdict: did the review end on the verdict key.yaml expects?

the sandbox holds no CI evidence, so approve is never right: request-changes
when a seeded defect is blocking or should-fix, incomplete otherwise.
  1.0  the expected verdict
  0.5  the other non-approve verdict (incomplete vs request-changes)
  0.0  approve, or no verdict found
the stated verdict is the one on a "verdict" line, else the last of the three
words in the final message.
"""
import re

from _lib import *

_WORDS = r"(approve[ds]?|request[- _]changes|incomplete)"
_LINE = re.compile(r"verdict[^a-z\n]{0,12}" + _WORDS, re.IGNORECASE)
_ANY = re.compile(_WORDS, re.IGNORECASE)


def _norm(w: str) -> str:
    w = w.lower()
    if w.startswith("approve"):
        return "approve"
    return "request-changes" if w.startswith("request") else "incomplete"


def score() -> float:
    want = review_key().get("verdict")
    text = final_text()
    m = _LINE.findall(text) or _ANY.findall(text)
    if not m:
        return 0.0
    got = _norm(m[-1])
    if got == want:
        return 1.0
    return 0.0 if got == "approve" else 0.5


emit(score)
