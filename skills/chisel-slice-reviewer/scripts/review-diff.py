#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""review-diff: run every deterministic check over a chisel-releases PR diff.

one command for a PR-review bot. given the branch a PR targets, it finds the
changed SDFs and runs the three checkers over them:

  - check-slice   static conventions (sorting, naming, copyright, clutter, ...)
  - check-test    binary test coverage
  - check-diff    append-only regressions (removed SDF / slice / path)

then merges their reports into one, adds a verdict, and prints it as the YAML
report described in _common.py (failed when anything blocks, unavailable when a
check could not run).

Usage:
  review-diff.py --base <ref>

Run from the chisel-releases checkout root (the checkers read chisel.yaml for
the format version). pyyaml is declared so the checkers, invoked via this same
interpreter, can import it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import _common as common
import yaml

HERE = Path(__file__).resolve().parent


def run_check(script: str, *args: str) -> dict:
    """A checker's parsed report; unavailable when it crashes or breaks the contract."""
    try:
        r = subprocess.run(
            [sys.executable, str(HERE / script), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        return unavailable(script, f"cannot run checker ({e})")
    try:
        doc = yaml.safe_load(r.stdout)
    except yaml.YAMLError:
        doc = None
    status = doc.get("status") if isinstance(doc, dict) else None
    if "Traceback" in r.stderr or common.EXIT.get(status) != r.returncode:
        tail = (
            r.stderr.strip().splitlines()[-1]
            if r.stderr.strip()
            else f"exit {r.returncode}"
        )
        return unavailable(script, f"{' '.join(args)}: did not complete ({tail})")
    return doc


def unavailable(check: str, reason: str) -> dict:
    return {
        "status": common.UNAVAILABLE,
        "unavailable": [{"check": check, "reason": reason}],
    }


def changed_slices(base: str) -> list[str] | None:
    status = common.git(["diff", "--name-status", base, "--", "slices/*.yaml"])
    if status is None:
        return None
    out = []
    for line in status.splitlines():
        parts = line.split("\t")
        # added or modified (skip deletions -- check-diff reports those).
        if (
            len(parts) >= 2
            and parts[0][:1] in ("A", "M", "R")
            and Path(parts[-1]).exists()
        ):
            out.append(parts[-1])
    return out


def verdict(report: common.Report) -> str:
    if report.count("block"):
        return "request-changes"
    if report.unavailable:
        return "incomplete"
    return "comment" if report.count("warn") else "approve"


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) < 2 or argv[0] != "--base":
        return common.usage("usage: review-diff.py --base <ref>")
    base = argv[1]

    report = common.Report({})
    changed = changed_slices(base)
    if changed is None:
        report.mark_unavailable(
            "base",
            f"git diff against {base!r} failed; is this a checkout, and is the ref present?",
        )
    else:
        if changed:
            report.merge(run_check("_check-slice.py", *changed))
            for sdf in changed:
                report.merge(run_check("_check-test.py", sdf))
        report.merge(run_check("_check-diff.py", "--base", base))
    report.data.update(base=base, changed=changed or [], verdict=verdict(report))
    return report.emit()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
