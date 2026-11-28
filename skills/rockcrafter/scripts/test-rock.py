#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""test-rock: run the rock's spread tests with `rockcraft test` and report each
task's outcome.

Before spending a test run it checks the suite is real: a rockcraft-test.yaml
(not only the deprecated spread.yaml), and no task still holding the scaffold's
placeholder. Then it runs every task -- or only the given spread expressions --
and reports the failed tasks, the prepare / restore scripts that failed, and a
suite spread could not load, with the error spread printed for them. Each is a
defect of the rock or of its tests; tasks that never ran for another reason (no
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

import common

# the placeholder `rockcraft init --profile=test` writes into its task.
PLACEHOLDER = "Put your test code here"

# spread's per-task error block and summary lines (spread >= the one rockcraft
# 1.21 bundles); rockcraft prefixes every spread line with ":: ".
ERROR = r"Error {verb} (\S+) \("
SUMMARY = re.compile(r"(Successful|Failed|Aborted) tasks: (\d+)")
# a prepare / restore script that died on the network is not a defect of the rock.
OFFLINE = re.compile(
    r"Could not resolve|Temporary failure in name resolution|Network is unreachable"
    r"|unable to contact snap store|[Cc]onnection timed out"
)
# what spread's project loader stops at, before any task runs, when
# rockcraft-test.yaml, a suite's directory or a task.yaml is wrong.
LOAD_ERROR = re.compile(
    r"error: ((?:cannot (?:load|list) |invalid (?:project|backend|suite|task|variable) name"
    r"|must define at least one |no systems specified for ).*"
    r"|.* is missing a summary|.* refers to invalid system name.*)$"
)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

CODES = {
    "no-suite": "no rockcraft-test.yaml: scaffold it with `rockcraft init --profile=test --name <rock-name>`",
    "deprecated-spread-yaml": "spread.yaml is deprecated for rockcraft test: rename it to rockcraft-test.yaml and drop `project:`",
    "placeholder": "a task still holds the scaffold's placeholder instead of real checks",
    "task-failed": "a spread task failed: the rock or its test is wrong",
    "setup-failed": "a prepare / restore script failed: tasks behind a failed prepare never ran",
    "suite-invalid": "spread could not load the suite: rockcraft-test.yaml, a suite's directory or a task.yaml is wrong",
}


def lint(report: common.Report) -> None:
    """problems that make a test run pointless."""
    if Path("rockcraft-test.yaml").exists():
        pass  # rockcraft reads it first; a spread.yaml beside it is not its suite
    elif Path("spread.yaml").exists():
        report.add("block", "deprecated-spread-yaml", "spread.yaml")
    else:
        report.add("block", "no-suite", "rockcraft-test.yaml")
    for task in sorted(Path("spread").glob("**/task.yaml")):
        if PLACEHOLDER in task.read_text(encoding="utf-8", errors="replace"):
            report.add("block", "placeholder", task)


def failures(lines: list[str], verb: str = "executing") -> dict[str, list[str]]:
    """task -> the error block spread printed for it (between its ----- rules).
    verb: executing (the task), or preparing / restoring (a task, suite or
    project script around it)."""
    error = re.compile(ERROR.format(verb=verb))
    out: dict[str, list[str]] = {}
    for i, line in enumerate(lines):
        m = error.search(line)
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
    for ln in lines:
        m = LOAD_ERROR.search(ln)
        if m:
            report.add("block", "suite-invalid", "rockcraft-test.yaml", output=m.group(1))
    for task, block in failures(lines).items():
        report.add("block", "task-failed", task, output=" | ".join(block) or None)
    for step in ("preparing", "restoring"):
        for what, block in failures(lines, step).items():
            if OFFLINE.search("\n".join(block)):
                report.mark_unavailable(
                    "test", f"{what}: {step} could not reach the network"
                )
                continue
            report.add("block", "setup-failed", what, step=step,
                       output=" | ".join(block) or None)  # fmt: skip
    report.data["tasks"] = common.Flow(
        passed=counts.get("successful", 0),
        failed=counts.get("failed", 0),
        aborted=counts.get("aborted", 0),
    )
    if counts.get("aborted") and not failures(lines, "preparing"):
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
