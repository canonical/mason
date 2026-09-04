#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""orientation-called: did the agent run scripts/orientation before anything else?

reads the run transcript and checks for orientation's own success marker
("working dir (chisel-releases checkout):"), the same way scorer_chisel-cut.py
does. four transcript formats, tried in order (see that scorer's docstring):
claude stream-json, opencode --format json, codex jsonl, plain text.
  0.0  orientation never ran (no invocation attempt found)
  0.5  invocation attempted but failed (e.g. wrong path -- no success marker)
  1.0  ran successfully, before the first write to a slice file
"""
from _lib import *  # noqa: F403
import json
import re

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# orientation's own output lines. several, spread through the output, because
# harnesses truncate: codex keeps only the tail of a long aggregated_output, so
# a marker pinned to the first line (as this scorer once used) reads as failure
# on a run that succeeded. any one of these hitting means it ran.
_SUCCESS_MARKERS = (
    "working dir (chisel-releases checkout):",
    "skill dir (read-only):",
    "existing slices:",
    "(gates SDF features",
    "->  write to",
)
_ATTEMPT_MARKERS = ("orientation",)


def _jsonl(path):
    """yield parsed json objects from a jsonl file, skipping non-json lines."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _claude_events():
    """yield the bash commands + tool outputs from claude stream-json in
    stdout.log. None if no claude-shaped events (claude lines carry
    "message"/"session_id"; opencode's json uses "sessionID" + "part")."""
    events = []
    saw_claude = False
    for ev in _jsonl(OUT / "stdout.log"):
        if "message" in ev or "session_id" in ev:
            saw_claude = True
        for c in ((ev.get("message") or {}).get("content") or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c.get("name") == "Bash":
                events.append(str((c.get("input") or {}).get("command", "")))
            elif c.get("type") == "tool_result":
                cont = c.get("content")
                text = " ".join(b.get("text", "") for b in cont if isinstance(b, dict)) if isinstance(cont, list) else str(cont or "")
                events.append(text)
    return events if saw_claude else None


def _opencode_events():
    """yield the bash commands + tool outputs + assistant/reasoning text from
    opencode --format json events in stdout.log. None if no opencode-shaped
    events (each carries a "part" object)."""
    events = []
    saw_oc = False
    for ev in _jsonl(OUT / "stdout.log"):
        part = ev.get("part")
        if not isinstance(part, dict):
            continue
        saw_oc = True
        if ev.get("type") == "tool_use":
            state = part.get("state") or {}
            events.append(str((state.get("input") or {}).get("command", "")))
            events.append(str(state.get("output") or state.get("error") or ""))
        elif ev.get("type") in ("text", "reasoning"):
            events.append(str(part.get("text", "")))
    return events if saw_oc else None


def _codex_events():
    """yield commands, their output, and assistant text from codex's jsonl
    (item.started/item.completed wrapping an "item"). None if not codex."""
    events = []
    saw_codex = False
    for ev in _jsonl(OUT / "stdout.log"):
        item = ev.get("item")
        if not isinstance(item, dict) or not str(ev.get("type", "")).startswith("item."):
            continue
        saw_codex = True
        if ev.get("type") != "item.completed":
            continue
        kind = item.get("type")
        if kind == "command_execution":
            events.append(str(item.get("command", "")))
            events.append(str(item.get("aggregated_output") or ""))
        elif kind == "agent_message":
            events.append(str(item.get("text", "")))
    return events if saw_codex else None


def _score_events(events) -> float:
    joined = "\n".join(events)
    if not any(m in joined for m in _ATTEMPT_MARKERS):
        return 0.0
    return 1.0 if any(m in joined for m in _SUCCESS_MARKERS) else 0.5


def _score_text() -> float:
    chunks = []
    for name in ("stderr.log", "stdout.log"):
        p = OUT / name
        if p.exists():
            chunks.append(_ANSI.sub("", p.read_text(encoding="utf-8", errors="replace")))
    text = "\n".join(chunks)
    if not any(m in text for m in _ATTEMPT_MARKERS):
        return 0.0
    return 1.0 if any(m in text for m in _SUCCESS_MARKERS) else 0.5


def score() -> float:
    for events in (_claude_events(), _opencode_events(), _codex_events()):
        if events is not None:
            return _score_events(events)
    return _score_text()


emit(score)
