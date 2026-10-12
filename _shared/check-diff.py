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
  check-diff.py                                 # git: the target base vs worktree
  check-diff.py --base=<ref> [<pathspec> ...]   # git: compare <ref> vs worktree
  check-diff.py <old.yaml> <new.yaml>           # compare two files directly

git mode enumerates changed slices/*.yaml and compares each against the base.
Without --base that is the release branch chisel.yaml names, ubuntu-<version>,
as a remote-tracking or local branch, whichever this checkout has; a branch
that is not fetched is an unavailable check. The comparison point is the merge
base of the base and HEAD, or the base's tip where history has no merge base.
The report lists the changed SDFs, added ones included, under `changed`, for
the single-file checkers to take from there.

Output: the YAML report described in common.py. Findings are advisory; a base
that git cannot produce or that does not parse makes the check unavailable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

try:
    import _common as common
except ImportError:
    import common

REJECTED = "reviewers reject it unless it left the archive"
CODES = {
    "sdf-removed": "removed-slices ci fails unless the package left the archive",
    "sdf-renamed": "the old file name is gone: removed-slices ci fails unless the package left the archive",
    "slice-removed": "removed-slices ci fails unless the package left the archive",
    "removed": f"dropped from a published slice; {REJECTED}",
    "narrowed": f"kept, but installed on fewer arches or dropped after mutate; {REJECTED}",
    "moved": "still installed through an essential, i.e. a subdivided slice",
    "unparseable": "the new file does not parse as an SDF; fix that first",
}


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


def compare(old_text: str, new_text: str, label: str, report: common.Report) -> None:
    old_doc = parse(old_text)
    if not isinstance(old_doc, dict) or not isinstance(old_doc.get("slices"), dict):
        report.mark_unavailable("base", f"{label}: base is not a parseable SDF")
        return
    new_doc = parse(new_text)
    old, new = slice_contents(old_doc), slice_contents(new_doc)
    if not old:
        return
    if new_doc is None or not new:
        # don't report every old slice as removed when the real defect is a
        # broken new file -- that misdirects the fix.
        report.add("warn", "unparseable", label)
        return
    reach = reachable(new_doc)
    pkg = new_doc.get("package")
    for sname in old:
        if sname not in new:
            report.add("warn", "slice-removed", label, slice=sname)
            continue
        for path in sorted(old[sname], key=str):
            was = old[sname][path]
            owner = next(
                (
                    o
                    for o in reach[sname]
                    if path in new[o] and covers(was, new[o][path])
                ),
                None,
            )
            if owner == sname:
                continue
            at = {"slice": sname, "path": path}
            if owner is not None:
                report.add("info", "moved", label, **at, to=f"{pkg}_{owner}")
            elif path in new[sname]:
                now = new[sname][path]
                report.add(
                    "warn", "narrowed", label, **at, was=was or {}, now=now or {}
                )
            else:
                report.add("warn", "removed", label, **at)


def run_base(base: str, pathspecs: list[str], report: common.Report) -> None:
    specs = pathspecs or ["slices/*.yaml"]
    rev = common.comparison(base, report)
    status = common.git(["diff", "--name-status", rev, "--", *specs])
    if status is None:
        report.mark_unavailable(
            "base",
            f"git diff against {base!r} failed; is this a chisel-releases checkout, and is the ref present?",
        )
        return
    changed = []
    for line in status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code, path = parts[0], parts[-1]
        if code.startswith("D"):
            report.add("warn", "sdf-removed", path)
            continue
        if code.startswith("R") and len(parts) >= 3:
            # rename: old path is parts[1], new is parts[2]. the old filename is
            # gone (removed-slices CI fails on it, e.g. a soname bump), and the
            # rename may also drop slices/paths -- compare old vs new content.
            old_path, new_path = parts[1], parts[2]
            report.add("warn", "sdf-renamed", old_path, to=new_path)
            compare_revisions(rev, old_path, new_path, report)
        elif code.startswith("M"):
            compare_revisions(rev, path, path, report)
        if Path(path).exists():
            changed.append(path)
    report.data["changed"] = changed


def compare_revisions(
    base: str, old_path: str, new_path: str, report: common.Report
) -> None:
    old_text = common.git(["show", f"{base}:{old_path}"])
    try:
        new_text = Path(new_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        new_text = None
    if old_text is None or new_text is None:
        report.mark_unavailable("base", f"{new_path}: cannot read both revisions")
        return
    compare(old_text, new_text, new_path, report)


USAGE = "usage: check-diff.py [--base=<ref> [<pathspec> ...]] | <old.yaml> <new.yaml>"


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    report = common.Report(CODES)
    if argv and argv[0].startswith("--base="):
        base = argv[0].partition("=")[2]
        if not base:
            return common.usage(USAGE)
        run_base(base, argv[1:], report)
    elif argv and argv[0] == "--base":
        return common.usage(USAGE)
    elif not argv:
        base = common.derived_base(report)
        if base is not None:
            run_base(base, [], report)
    elif len(argv) == 2:
        try:
            old, new = (Path(a).read_text(encoding="utf-8") for a in argv)
        except (OSError, UnicodeError) as e:
            report.mark_unavailable("read", str(e))
        else:
            compare(old, new, argv[1], report)
    else:
        return common.usage(USAGE)
    return report.emit()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
