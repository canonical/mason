#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""review-recall: share of key.yaml's seeded defects the final review names.

a defect counts as named when any of its locators (a path, slice or package
name) appears in the final message. naming is not diagnosing, so this is a
floor under the judge's finding-level score, not a substitute. na on a control
task with no seeded defects.
"""
from _lib import *


def score() -> float:
    defects = review_key().get("defects") or []
    if not defects:
        raise NA
    text = final_text().lower()
    hit = sum(any(loc.lower() in text for loc in d.get("locators") or []) for d in defects)
    return hit / len(defects)


emit(score)
