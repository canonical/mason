#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-tests-functional: the tests exercise the workload, not just its
presence.

CLI: a task runs the binary in the rock with real arguments (1.0); only
--version / --help (0.5); never (0). service: a task starts the rock detached
(1/2) and talks to it -- curl / wget / nc -- (1/2).
"""
import re

from _lib import *

_SHALLOW = re.compile(r"^\s*(--?version|-v|--help|-h)?\s*$")


def score() -> float:
    c = case()
    text = tests_text()
    if not text:
        return 0.0
    if c.get("service"):
        detached = re.search(r"docker run[^\n]*\s-d\b", text) is not None
        talks = re.search(r"\b(curl|wget|nc)\b", text) is not None
        return (detached + talks) / 2
    binary = c["binary"].rsplit("/", 1)[-1]
    calls = re.findall(rf"\b{re.escape(binary)}\b([^\n|]*)", text)
    if not calls:
        return 0.0
    return 1.0 if any(not _SHALLOW.match(a) for a in calls) else 0.5


emit(score)
