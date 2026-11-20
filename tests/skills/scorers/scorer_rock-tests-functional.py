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

import yaml
from _lib import *

_SHALLOW = {"--version", "-version", "-v", "-V", "--help", "-h"}
_INERT = {"MATCH", "NOMATCH", "grep", "echo", "printf"}  # they name the binary, they do not run it
_REDIRECT = re.compile(r"\d*[<>]+&?[ \t]*\S*")
_COMMENT = re.compile(r"(^|\s)#.*$", re.MULTILINE)


def _commands(text: str) -> str:
    """the execute scripts of the tasks in tests.txt (a task that does not parse: its text)."""
    out = []
    for body in re.split(r"^# spread/.*$", text, flags=re.MULTILINE)[1:]:
        try:
            doc = yaml.safe_load(body)
        except (yaml.YAMLError, ValueError):
            out.append(body)
            continue
        run = doc.get("execute") if isinstance(doc, dict) else None
        out.append("\n".join(map(str, run)) if isinstance(run, list) else str(run or ""))
    return "\n".join(out)


def _calls(binary: str, script: str) -> list[list[str]]:
    """the arguments of each call of the binary. it is called where a word is its
    name or a path to it, so the image a rock is loaded as (`<name>:latest`) is not
    one. an image loaded untagged reads as a call: `exec` and the binary's own name
    are not arguments, so it scores as the call behind it does."""
    script = _COMMENT.sub("", script.replace("\\\n", " "))
    calls = []
    for cmd in re.split(r"[|;&\n]+", _REDIRECT.sub(" ", script)):
        words = [w for w in (w.strip("'\"`$()") for w in cmd.split()) if w]
        if words and words[0] in _INERT:
            continue
        named = [w == binary or w.endswith("/" + binary) for w in words]
        calls += [
            [w for w, n in zip(words[i + 1 :], named[i + 1 :]) if not n and w != "exec"]
            for i, n in enumerate(named)
            if n
        ]
    return calls


def score() -> float:
    c = case()
    text = tests_text()
    if not text:
        return 0.0
    if c.get("service"):
        detached = re.search(r"docker run[^\n]*\s-d\b", text) is not None
        talks = re.search(r"\b(curl|wget|nc)\b", text) is not None
        return (detached + talks) / 2
    calls = _calls(c["binary"].rsplit("/", 1)[-1], _commands(text))
    if not calls:
        return 0.0
    return 1.0 if any(set(args) - _SHALLOW for args in calls) else 0.5


emit(score)
