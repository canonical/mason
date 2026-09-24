#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""check-diff: catch append-only regressions between two versions of an SDF.

Published slices are append-only: removing an SDF or a slice fails the
removed-slices CI gate; dropping a content path from a kept slice has no CI
gate but is an append-only regression reviewers reject. Those are diff-shaped
checks -- single-file linting can't see them. This does:

  - an SDF that existed is now gone (or renamed) -> removed-slices CI fails
  - a slice key that existed is now gone         -> removed-slices CI fails
  - a content path dropped from a kept slice     -> append-only regression
  - a kept path limited to fewer arches, or to
    before mutation (until: mutate)              -> append-only regression

Each is reported unless the package or path genuinely left the archive (which
only the archive can confirm -- a human/CI decides that), so these are warnings
carrying the CI consequence, not hard blocks.

A dropped path the slice still installs through its essentials is a subdivided
slice, not a regression, and is reported as info. Only same-package essentials
that apply on every arch count; paths moved to another package still warn.

Usage:
  check-diff.py --base <ref> [<pathspec> ...]   # git: compare <ref> vs worktree
  check-diff.py <old.yaml> <new.yaml>           # compare two files directly

--base mode enumerates changed slices/*.yaml via git and compares each against
<ref> (e.g. the release branch a PR targets). Default pathspec: slices/*.yaml.

Output: one finding per line, `SEVERITY  where: message`. Exit 1 on error (git
failure, unreadable revision), otherwise 0 (advisory); inspect `warn` to gate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def parse(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def slice_contents(doc: Any) -> dict[str, dict[str, Any]]:
    """slice name -> {content path: its options}. empty if not an SDF."""
    out: dict[str, dict[str, Any]] = {}
    slices = doc.get("slices") if isinstance(doc, dict) else None
    if not isinstance(slices, dict):
        return out
    for name, body in slices.items():
        contents = body.get("contents") if isinstance(body, dict) else None
        out[name] = dict(contents) if isinstance(contents, dict) else {}
    return out


def essential_names(value: Any) -> list[str]:
    """essential entries in list (v1/v2) or map (v3) form, minus arch-limited ones."""
    if isinstance(value, list):
        return [e for e in value if isinstance(e, str)]
    if isinstance(value, dict):
        return [
            k for k, v in value.items() if not (isinstance(v, dict) and "arch" in v)
        ]
    return []


def reachable(doc: Any) -> dict[str, list[str]]:
    """slice name -> itself, then every same-package slice its essentials pull in."""
    slices = doc["slices"]
    pkg = doc.get("package")

    def same_package(value: Any) -> list[str]:
        names = essential_names(value)
        return [s for p, _, s in (n.partition("_") for n in names) if p == pkg]

    everywhere = same_package(doc.get("essential"))
    out: dict[str, list[str]] = {}
    for start in slices:
        order: list[str] = []
        queue = [start, *everywhere]
        while queue:
            name = queue.pop(0)
            if name in order or name not in slices:
                continue
            order.append(name)
            body = slices[name]
            if isinstance(body, dict):
                queue += same_package(body.get("essential"))
        out[start] = order
    return out


def arches(options: Any) -> set[str] | None:
    """the arches a content entry is limited to; None when it has no limit."""
    arch = options.get("arch") if isinstance(options, dict) else None
    if isinstance(arch, str):
        return {arch}
    if isinstance(arch, list):
        return {a for a in arch if isinstance(a, str)}
    return None


def dropped_after_mutate(options: Any) -> bool:
    return isinstance(options, dict) and options.get("until") not in (None, "")


def covers(old: Any, new: Any) -> bool:
    """whether the new entry installs the path wherever the old one did."""
    if dropped_after_mutate(new) and not dropped_after_mutate(old):
        return False
    new_arches, old_arches = arches(new), arches(old)
    if new_arches is None:
        return True
    return old_arches is not None and old_arches <= new_arches


def compare(old_text: str, new_text: str, label: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    old_doc = parse(old_text)
    if not isinstance(old_doc, dict) or not isinstance(old_doc.get("slices"), dict):
        raise SystemExit(f"error: {label}: base is not a parseable SDF")
    new_doc = parse(new_text)
    old, new = slice_contents(old_doc), slice_contents(new_doc)
    if not old:
        return rows
    if new_doc is None or not new:
        # don't report every old slice as removed when the real defect is a
        # broken new file -- that misdirects the fix.
        return [("warn", label, "new file is not a parseable SDF -- fix that first")]
    reach = reachable(new_doc)
    pkg = new_doc.get("package")
    for sname in old:
        if sname not in new:
            rows.append(
                (
                    "warn",
                    f"{label}: {sname}",
                    "slice removed -- removed-slices CI fails unless the package left the archive",
                )
            )
            continue
        for path in sorted(old[sname], key=str):
            owner = next(
                (
                    o
                    for o in reach[sname]
                    if path in new[o] and covers(old[sname][path], new[o][path])
                ),
                None,
            )
            if owner == sname:
                continue
            if owner is not None:
                rows.append(
                    (
                        "info",
                        f"{label}: {sname}",
                        f"path moved to {pkg}_{owner}, still installed via essential: {path}",
                    )
                )
                continue
            change = "narrowed in" if path in new[sname] else "removed from"
            rows.append(
                (
                    "warn",
                    f"{label}: {sname}",
                    f"path {change} published slice: {path} (append-only regression)",
                )
            )
    return rows


def git(args: list[str]) -> str | None:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def run_base(base: str, pathspecs: list[str]) -> list[tuple[str, str, str]]:
    specs = pathspecs or ["slices/*.yaml"]
    status = git(["diff", "--name-status", base, "--", *specs])
    if status is None:
        raise SystemExit(
            f"error: git diff against {base!r} failed -- is this a chisel-releases checkout, and is the ref present?"
        )
    rows: list[tuple[str, str, str]] = []
    for line in status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code, path = parts[0], parts[-1]
        if code.startswith("D"):
            rows.append(
                (
                    "warn",
                    path,
                    "SDF removed -- removed-slices CI fails unless the package left the archive",
                )
            )
        elif code.startswith("R") and len(parts) >= 3:
            # rename: old path is parts[1], new is parts[2]. the old filename is
            # gone (removed-slices CI fails on it, e.g. a soname bump), and the
            # rename may also drop slices/paths -- compare old vs new content.
            old_path, new_path = parts[1], parts[2]
            rows.append(
                (
                    "warn",
                    old_path,
                    "SDF renamed away -- removed-slices CI fails unless the package left the archive",
                )
            )
            old_text = git(["show", f"{base}:{old_path}"])
            new = Path(new_path)
            if old_text is not None and new.exists():
                rows += compare(old_text, new.read_text(encoding="utf-8"), new_path)
            else:
                raise SystemExit(f"error: {new_path}: cannot read both revisions")
        elif code.startswith("M"):
            old_text = git(["show", f"{base}:{path}"])
            new = Path(path)
            if old_text is None or not new.exists():
                raise SystemExit(f"error: {path}: cannot read both revisions")
            rows += compare(old_text, new.read_text(encoding="utf-8"), path)
    return rows


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    rows: list[tuple[str, str, str]]
    if argv and argv[0] == "--base":
        if len(argv) < 2:
            print("usage: check-diff.py --base <ref> [<pathspec> ...]", file=sys.stderr)
            return 2
        rows = run_base(argv[1], argv[2:])
    elif len(argv) == 2:
        old, new = Path(argv[0]), Path(argv[1])
        rows = compare(
            old.read_text(encoding="utf-8"), new.read_text(encoding="utf-8"), str(new)
        )
    else:
        print(
            "usage: check-diff.py --base <ref> [<pathspec> ...] | <old.yaml> <new.yaml>",
            file=sys.stderr,
        )
        return 2

    for sev, where, msg in rows:
        print(f"{sev:5}  {where}: {msg}")
    if not rows:
        print("ok: no append-only regressions")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
