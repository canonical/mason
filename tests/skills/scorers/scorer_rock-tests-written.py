#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-tests-written: the rock has a real spread suite. a share each:
rockcraft-test.yaml present; no deprecated spread.yaml left; at least one task;
no task still holding the scaffold's placeholder. 0 with no suite at all."""
from _lib import *

_PLACEHOLDER = "Put your test code here"


def score() -> float:
    case()
    text = tests_text() or ""
    if not text and not (OUT / "rockcraft-test.yaml").exists():
        return 0.0  # no suite at all: nothing to credit
    checks = [
        (OUT / "rockcraft-test.yaml").exists(),
        not (OUT / "spread.yaml").exists(),
        "# spread/" in text,
        bool(text) and _PLACEHOLDER not in text,
    ]
    return sum(checks) / len(checks)


emit(score)
