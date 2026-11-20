#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""chisel-cut: did the agent validate its slices by running `chisel cut`?

correlates each `chisel cut` / `try-cut` command to its result:
  0.0  never ran chisel cut (no validation attempted)
  0.5  ran it but no invocation succeeded (every cut errored)
  1.0  ran it and at least one cut exited cleanly

old plain-text transcripts fall back to `$ <command>` blocks scanned for failure
markers.
"""
import re

from _lib import *

# substrings in chisel-cut output that mean the cut failed (case-insensitive).
_FAIL = ("error:", "no content at", "cannot find", "not found", "panic", "usage:")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# try-cut's report: its status line decides, since chisel's own log in the same
# output has lines like 'credentials not found' for an archive it then ignores.
_STATUS = re.compile(r"^status: (passed|failed|unavailable)\s*$", re.MULTILINE)


def _cut_ok(is_err: bool, text: str) -> bool:
    m = _STATUS.search(text)
    if m:
        return m.group(1) == "passed"
    return not is_err and not any(m in text.lower() for m in _FAIL)


def _is_cut_cmd(cmd: str) -> bool:
    return "chisel cut" in cmd or "try-cut" in cmd


def _score_calls(cs: list[dict]) -> float:
    cuts = [c for c in cs if _is_cut_cmd(c["command"])]
    if not cuts:
        return 0.0
    return 1.0 if any(c["done"] and _cut_ok(c["error"], c["output"]) for c in cuts) else 0.5


def _score_text() -> float:
    """plain-text transcript (e.g. opencode): scan `$ <command>` blocks for
    chisel-cut/try-cut invocations and check their output for failure markers."""
    chunks = []
    for name in ("stderr.log", "stdout.log"):
        p = OUT / name
        if p.exists():
            chunks.append(_ANSI.sub("", p.read_text(encoding="utf-8", errors="replace")))
    text = "\n".join(chunks)
    if not text.strip():
        return 0.0

    # split into command blocks: a block starts at a line beginning with "$ "
    # (a bash tool invocation) and runs until the next such line.
    lines = text.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    cur_cmd: str | None = None
    cur_out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("$ "):
            if cur_cmd is not None:
                blocks.append((cur_cmd, cur_out))
            cur_cmd = stripped[2:]
            cur_out = []
        elif cur_cmd is not None:
            cur_out.append(line)
    if cur_cmd is not None:
        blocks.append((cur_cmd, cur_out))

    cut_blocks = [(cmd, out) for cmd, out in blocks if _is_cut_cmd(cmd)]
    if not cut_blocks:
        return 0.0
    for _, out in cut_blocks:
        if _cut_ok(False, "\n".join(out)):
            return 1.0
    return 0.5


def score() -> float:
    c = calls()
    if c["parsed"]:
        return _score_calls(c["calls"])
    return _score_text()


emit(score)
