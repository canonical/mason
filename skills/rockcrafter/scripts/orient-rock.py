#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""orient-rock: what this machine and this project offer for a rock -- run
FIRST, every time. Reports which tools are installed, the rock project in the
current directory (its rockcraft.yaml and test suite, if any) and the
supported Ubuntu releases, with the one to default to. It only reads.

Usage: orient-rock.py

Unavailable when rockcraft is not installed -- a rock cannot be started
(`rockcraft init`), packed or tested without it -- or when the Ubuntu release
list cannot be reached. The facts that could be established are still reported.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import rocklib as rl
import yaml

TOOLS = ("rockcraft", "lxc", "docker", "chisel", "dpkg-deb", "git", "uv")
SUITES = ("rockcraft-test.yaml", "spread.yaml")
KEYS = ("name", "version", "base", "build-base")


def rock() -> common.Flow | str | None:
    """The identifying keys of ./rockcraft.yaml, or None when there is none."""
    try:
        text = Path("rockcraft.yaml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        doc = None
    if not isinstance(doc, dict):
        return "present, does not parse"
    return common.Flow({k: doc[k] for k in KEYS if k in doc})


def project() -> dict:
    inside = (common.git(["rev-parse", "--is-inside-work-tree"]) or "").strip()
    return {
        "rockcraft.yaml": rock(),
        "test suite": next((s for s in SUITES if Path(s).is_file()), None),
        "git repository": inside == "true",
    }


def releases() -> dict:
    """The supported Ubuntu releases, and the one to default to."""
    default = rl.resolve_release(None)
    supported = [
        common.Flow(version=r.version, codename=r.codename, lts=r.lts)
        for r in rl.releases()
        if r.supported
    ]
    return {"default": default.version, "supported": supported}


def main() -> int:
    if len(sys.argv) > 1:
        return common.usage(__doc__.strip())
    report = common.Report({})
    report.data["working dir"] = os.getcwd()
    report.data["tools"] = found = common.tools(TOOLS)
    if not found["rockcraft"]["present"]:
        report.mark_unavailable(
            "rockcraft",
            "not installed: a rock cannot be started (rockcraft init), packed "
            "or tested without it",
        )
    report.data["project"] = project()
    try:
        report.data["releases"] = releases()
    except rl.Unavailable as e:
        report.mark_unavailable("releases", str(e))
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
