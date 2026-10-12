#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""check-test: validate a spread task and scan for binary references.

Reports references to explicit paths under /usr/bin, /usr/sbin, /bin, /sbin and
/usr/libexec from the package's execute script and sibling shell helpers.

It cannot judge whether a test is *meaningful* -- only that binaries are
referenced. Shell comments and YAML metadata are excluded, but strings and
uncalled helpers can still match. Globs and binaries outside the recognised
directories need manual review. Test depth and rootfs isolation are defined in
kb/_spread-tests.md; only running spread proves runtime behaviour.

Usage:
  check-test.py <slices/pkg.yaml> [<task.yaml>]

With no task.yaml, it looks for tests/spread/integration/<pkg>/task.yaml under
the cwd, and folds in any sibling *.sh helper files.

Output: the YAML report described in common.py. Findings are advisory: warn
for a missing or malformed task, an unfinished scaffold or no binary
references, info for partial coverage or nothing to check. An input that
cannot be read makes the check unavailable.
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    import _common as common
except ImportError:
    import common

CODES = {
    "sdf-unreadable": "the SDF does not read or parse, so its binaries are unknown",
    "no-test": "every package needs tests/spread/integration/<pkg>/task.yaml",
    "task-invalid": "a spread task is a mapping with non-empty summary and execute strings",
    "scaffold": "the scaffold's TODO(author) placeholders are still there",
    "no-binaries": "the SDF declares no explicit binaries; review the slice assertions by hand",
    "unscannable": "the shell does not tokenise; review coverage by hand",
    "untested": "the spread test references none of the declared binaries",
    "partly-tested": "some declared binaries are never referenced; review whether they need a test",
}

BIN_DIRS = ("/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/", "/usr/libexec/")


def declared_binaries(doc: Any) -> dict[str, str]:
    """basename -> slice name, for each explicit executable path (skips globs/dirs)."""
    out: dict[str, str] = {}
    slices = doc.get("slices") if isinstance(doc, dict) else None
    if not isinstance(slices, dict):
        return out
    for sname, body in slices.items():
        contents = body.get("contents") if isinstance(body, dict) else None
        if not isinstance(contents, dict):
            continue
        for path in contents:
            if not isinstance(path, str) or not any(
                path.startswith(d) for d in BIN_DIRS
            ):
                continue
            if path.endswith("/") or "*" in path or "?" in path:
                continue
            out.setdefault(path.rsplit("/", 1)[-1], sname)
    return out


def task_sources(task: Path) -> list[str]:
    """Validate the task's basic shape and return its shell sources."""
    doc = yaml.safe_load(task.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise TypeError("task must be a mapping")
    for key in ("summary", "execute"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise ValueError(f"task needs a non-empty {key} string")
    return [
        doc["execute"],
        *(sh.read_text(encoding="utf-8") for sh in sorted(task.parent.glob("*.sh"))),
    ]


def check(sdf: Path, task_arg: str | None) -> common.Report:
    report = common.Report(CODES)
    try:
        doc = yaml.safe_load(sdf.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, yaml.YAMLError) as e:
        report.add("warn", "sdf-unreadable", sdf, error=str(e).splitlines()[0])
        return report
    except OSError as e:
        report.mark_unavailable("read", f"{sdf}: {e}")
        return report

    bins = declared_binaries(doc)
    task = (
        Path(task_arg)
        if task_arg
        else (Path("tests/spread/integration") / sdf.stem / "task.yaml")
    )
    if not task.exists():
        report.add("warn", "no-test", sdf, expected=str(task))
        return report

    try:
        sources = task_sources(task)
    except (UnicodeError, TypeError, ValueError, yaml.YAMLError) as e:
        report.add("warn", "task-invalid", task, error=str(e).splitlines()[0])
        return report
    except OSError as e:
        report.mark_unavailable("read", f"{task}: {e}")
        return report
    if any("TODO(author):" in source for source in sources):
        report.add("warn", "scaffold", task)
    if not bins:
        report.add("info", "no-binaries", sdf)
        return report
    try:
        text = "\n".join(
            " ".join(shlex.split(source, comments=True)) for source in sources
        )
    except ValueError as e:
        report.add("info", "unscannable", task, error=str(e))
        return report

    # lookarounds, not \b: \b needs a word char adjacent, so names ending in
    # non-word chars (c++, g++, [) never match. exclude name-continuation
    # chars but allow a leading / so path-prefixed invocations still count.
    referenced = {
        n for n in bins if re.search(rf"(?<![\w.+-]){re.escape(n)}(?![\w.+-])", text)
    }
    unreferenced = sorted(set(bins) - referenced)
    if not referenced:
        report.add("warn", "untested", task, declared=len(bins))
    elif unreferenced:
        report.add(
            "info",
            "partly-tested",
            task,
            referenced=len(referenced),
            declared=len(bins),
            unreferenced=unreferenced,
        )
    return report


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not args:
        return common.usage("usage: check-test.py <slices/pkg.yaml> [<task.yaml>]")
    return check(Path(args[0]), args[1] if len(args) > 1 else None).emit()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
