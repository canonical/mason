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

Output: one finding per line, `SEVERITY  where: message`.
  warn   missing/malformed task, unfinished scaffold, or no binary references.
  info   partial coverage (lists the untested binaries to review), or nothing
         to check (the SDF declares no explicit binaries).
Exit code is always 0 (advisory); grep for `warn` to gate. Stdlib + pyyaml.
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml

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


def check(sdf: Path, task_arg: str | None) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    try:
        doc = yaml.safe_load(sdf.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as e:
        rows.append(("warn", str(sdf), f"cannot read SDF: {e}"))
        return rows

    bins = declared_binaries(doc)
    task = (
        Path(task_arg)
        if task_arg
        else (Path("tests/spread/integration") / sdf.stem / "task.yaml")
    )
    if not task.exists():
        rows.append(
            (
                "warn",
                str(sdf),
                "no spread test found -- every package needs a task.yaml",
            )
        )
        return rows

    try:
        sources = task_sources(task)
    except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError) as e:
        return [("warn", str(task), f"cannot validate spread task: {e}")]
    if any("TODO(author):" in source for source in sources):
        rows.append(
            (
                "warn",
                str(task),
                "unfinished scaffold -- replace TODO(author) placeholders",
            )
        )
    if not bins:
        rows.append(
            (
                "info",
                str(sdf),
                "no explicit binaries to scan; review slice assertions manually",
            )
        )
        return rows
    try:
        text = "\n".join(
            " ".join(shlex.split(source, comments=True)) for source in sources
        )
    except ValueError as e:
        rows.append(
            (
                "info",
                str(task),
                f"cannot scan shell references: {e}; review coverage manually",
            )
        )
        return rows

    # lookarounds, not \b: \b needs a word char adjacent, so names ending in
    # non-word chars (c++, g++, [) never match. exclude name-continuation
    # chars but allow a leading / so path-prefixed invocations still count.
    referenced = {
        n for n in bins if re.search(rf"(?<![\w.+-]){re.escape(n)}(?![\w.+-])", text)
    }
    unreferenced = sorted(set(bins) - referenced)
    if not referenced:
        rows.append(
            (
                "warn",
                str(task),
                f"spread test references none of the {len(bins)} declared binaries",
            )
        )
    elif unreferenced:
        shown = ", ".join(unreferenced[:12]) + (
            f", +{len(unreferenced) - 12} more" if len(unreferenced) > 12 else ""
        )
        rows.append(
            (
                "info",
                str(task),
                f"{len(referenced)}/{len(bins)} binaries referenced; unreferenced: {shown}",
            )
        )
    return rows


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not args:
        print("usage: check-test.py <slices/pkg.yaml> [<task.yaml>]", file=sys.stderr)
        return 2
    sdf = Path(args[0])
    task_arg = args[1] if len(args) > 1 else None
    rows = check(sdf, task_arg)
    for sev, where, msg in rows:
        print(f"{sev:5}  {where}: {msg}")
    if not rows:
        print(
            f"ok: {sdf} task shape valid; all explicit binaries referenced (not runtime proof)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
