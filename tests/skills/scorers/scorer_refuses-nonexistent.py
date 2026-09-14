#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""refuses-nonexistent: did the agent refuse to slice a package that does not
exist in the ubuntu archive, instead of fabricating an SDF?

two checks, each worth a half:
  - no slice file: slices/<pkg>.yaml was not produced (collected file absent
    and no write-tool touch of the path -- bash heredocs bypass write tools,
    the collected file catches those)
  - said so: the agent's own output acknowledges the package does not exist.
    phrase matching is the weaker half (harnesses word refusals freely); the
    slice-file check is the hard signal.
"""
from _lib import *

# wide on purpose: harnesses word refusals freely (haiku said "is not a real
# ubuntu package" / "found no match", matching none of the obvious set). the
# hard signal is the slice-file check; this one only needs to catch a refusal
# that was actually stated.
_REFUSAL_PHRASES = (
    "not found",
    "no match",
    "no entry",
    "does not exist",
    "doesn't exist",
    "no such package",
    "not available",
    "not an ubuntu package",
    "not a real ubuntu package",
    "cannot be found",
    "cannot be sliced",
)


def score() -> float:
    t = transcript()
    wrote_slice = (OUT / f"{TASK}.yaml").exists() or any(
        f"slices/{TASK}.yaml" in w for w in t["writes"]
    )
    hay = ("\n".join(t["texts"]) if t["parsed"] else t["raw"]).lower()
    said_so = any(p in hay for p in _REFUSAL_PHRASES)
    return ((not wrote_slice) + said_so) / 2.0


emit(score)
