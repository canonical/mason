#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-tests-passed: the rock's tests ran and every task passed. 1.0 passed;
0.5 ran, not all passing; 0 never ran. na for a rock-debug case whose project
has no tests."""
from _lib import *


def score() -> float:
    c = case()
    if "fault" in c and not (OUT / "tests.expected.txt").exists():
        raise NA
    return tests_passed()


emit(score)
