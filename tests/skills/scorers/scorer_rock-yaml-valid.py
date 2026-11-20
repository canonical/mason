#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-yaml-valid: the rockcraft.yaml parses and has the keys rockcraft
requires (plus build-base with base: bare). the fraction present; 0 when there
is no file or it does not parse."""
from _lib import *

_REQUIRED = ("name", "version", "summary", "description", "license", "base", "platforms", "parts")


def score() -> float:
    case()
    doc = rock()
    if doc is None:
        return 0.0
    keys = list(_REQUIRED) + (["build-base"] if doc.get("base") == "bare" else [])
    if doc.get("extensions"):
        keys.remove("parts")  # the extension generates them
    return sum(k in doc for k in keys) / len(keys)


emit(score)
