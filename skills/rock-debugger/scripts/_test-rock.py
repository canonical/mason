#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""test-rock: run the rock's spread tests with `rockcraft test` and report each
task's outcome.

Before spending a test run it checks the suite is real: a rockcraft-test.yaml
(not the deprecated spread.yaml), and no task still holding the scaffold's
placeholder. Then it runs every task -- or only the given spread expressions --
and reports the failed tasks with the error spread printed for them. A task
that fails is a defect of the rock or of its test; tasks that never ran (no
test VM, no network) are unavailable, not failed.

Usage: test-rock.py [<spread-expression> ...]
  e.g. test-rock.py craft:ubuntu-24.04:spread/general/greeting

Unavailable when rockcraft is not installed, or spread could not run the tasks.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import _common as common
except ImportError:
    import common

# the placeholder `rockcraft init --profile=test` writes into its task.
PLACEHOLDER = "Put your test code here"

# spread's per-task error block and summary lines (spread >= the one rockcraft
# 1.21 bundles); rockcraft prefixes every spread line with ":: ".
ERROR = re.compile(r"Error executing (\S+) \(")
SUMMARY = re.compile(r"(Successful|Failed|Aborted) tasks: (\d+)")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

CODES = {
    "no-suite": "no rockcraft-test.yaml: scaffold it with `rockcraft init --profile=test --name <rock-name>`",
    "deprecated-spread-yaml": "spread.yaml is deprecated for rockcraft test: rename it to rockcraft-test.yaml and drop `project:`",
    "placeholder": "a task still holds the scaffold's placeholder instead of real checks",
    "task-failed": "a spread task failed: the rock or its test is wrong",
}


def lint(report: common.Report) -> None:
    """problems that make a test run pointless."""
    if Path("spread.yaml").exists():
        report.add("block", "deprecated-spread-yaml", "spread.yaml")
    elif not Path("rockcraft-test.yaml").exists():
        report.add("block", "no-suite", "rockcraft-test.yaml")
    for task in sorted(Path("spread").glob("**/task.yaml")):
        if PLACEHOLDER in task.read_text(encoding="utf-8", errors="replace"):
            report.add("block", "placeholder", task)


def failures(lines: list[str]) -> dict[str, list[str]]:
    """task -> the error block spread printed for it (between its ----- rules)."""
    out: dict[str, list[str]] = {}
    for i, line in enumerate(lines):
        m = ERROR.search(line)
        if not m:
            continue
        block, rules = [], 0
        for ln in lines[i + 1 :]:
            body = ln.removeprefix(":: ").rstrip()
            if body.startswith("-----"):
                rules += 1
                if rules == 2:
                    break
                continue
            if rules == 1:
                block.append(body)
        out[m.group(1)] = block[-12:]
    return out


def main() -> int:
    if any(a.startswith("-") for a in sys.argv[1:]):
        return common.usage(__doc__.strip())
    report = common.Report(CODES)
    lint(report)
    if report.count("block"):
        return report.emit()
    if not shutil.which("rockcraft"):
        report.mark_unavailable(
            "test", "rockcraft is not installed (snap install rockcraft --classic)"
        )
        return report.emit()

    r = subprocess.run(
        ["rockcraft", "test", "-v", *sys.argv[1:]],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [ANSI.sub("", ln) for ln in (r.stdout + r.stderr).splitlines()]
    counts: dict[str, int] = {}
    for ln in lines:
        m = SUMMARY.search(ln)
        if m:
            counts[m.group(1).lower()] = int(m.group(2))
    for task, block in failures(lines).items():
        report.add("block", "task-failed", task, output=" | ".join(block) or None)
    report.data["tasks"] = common.Flow(
        passed=counts.get("successful", 0),
        failed=counts.get("failed", 0),
        aborted=counts.get("aborted", 0),
    )
    if counts.get("aborted"):
        report.mark_unavailable(
            "test", f"{counts['aborted']} task(s) aborted before running"
        )
    if r.returncode and not report.count("block") and not counts.get("aborted"):
        # no task verdict at all: the VM or the pack never got that far
        tail = [ln.strip() for ln in lines if ln.strip()][-6:]
        report.mark_unavailable(
            "test", " | ".join(tail) or f"rockcraft test exited {r.returncode}"
        )
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
