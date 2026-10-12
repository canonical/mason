#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""try-cut: run chisel cut from the current chisel-releases dir into a temp root.

Usage:
  try-cut.py [--arch ARCH] <pkg>_<slice> [<pkg>_<slice> ...]
  try-cut.py --base[=REF] [--arch ARCH] [<pkg>_<slice> ...]

  --arch ARCH   package architecture (passed through to chisel cut)
  --base[=REF]  cut every slice of each SDF changed since REF (or the slices
                named) twice, from REF and from the worktree, and report each
                path the worktree's cut no longer installs. REF defaults to
                the target base chisel.yaml names, resolved as check-diff does

Temp roots, and REF's release for --base, are created in the current directory
(chisel snap compat) and removed on exit. chisel's own output goes to stderr;
stdout is the YAML report described in common.py. Both --base cuts read the
same archive, so a lost path is down to the SDF change, not the archive. REF
is compared at its merge base with HEAD, or at its tip without one.

A cut that fails on the SDFs fails; one that fails on the archive or the
network, or that has no chisel to run, is unavailable. A slice REF itself can
no longer cut is not compared.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

try:
    import _common as common
except ImportError:
    import common

USAGE = (
    "usage: try-cut.py [--arch ARCH] <pkg>_<slice> [...]\n"
    "       try-cut.py --base[=REF] [--arch ARCH] [<pkg>_<slice> ...]"
)

CODES = {
    "cut-failed": "chisel rejected the slices; its last error line is shown",
    "lost": "the base ref's cut installs it and the worktree's does not: the change dropped it",
    "base-cut-failed": "the base ref no longer cuts, so this slice was not compared",
}

# chisel errors that say nothing about the SDFs: the archive or the network
# could not be reached, or served an inconsistent release.
UNREACHABLE = (
    "cannot talk to archive",
    "cannot fetch",
    "component digests",
    "dial tcp",
    "no such host",
    "i/o timeout",
    "connection refused",
    "connection reset",
    "tls handshake",
)


class Unreachable(Exception):
    """chisel could not reach a usable archive."""


def ignore_flags() -> list[str]:
    # --ignore flags match install-slices: without them a bare cut hard-errors on
    # devel (unstable) and EOL (unmaintained) branches where CI succeeds. guarded:
    # older chisel builds don't have the flag.
    r = subprocess.run(
        ["chisel", "cut", "--help"], capture_output=True, text=True, check=False
    )
    return (
        ["--ignore=unstable", "--ignore=unmaintained"]
        if "--ignore" in r.stdout + r.stderr
        else []
    )


def installed(root: Path) -> set[str]:
    """Every non-directory path under root, symlinks to directories included."""
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        links = [d for d in dirnames if (here / d).is_symlink()]
        for name in [*filenames, *links]:
            out.add("/" + str((here / name).relative_to(root)))
    return out


def cut(
    release: Path, slices: list[str], arch: str, ignore: list[str]
) -> tuple[set[str] | None, str]:
    """The paths a cut installs, or None and chisel's last error line."""
    root = Path(tempfile.mkdtemp(prefix="chisel-root.", dir=Path.cwd()))
    try:
        cmd = ["chisel", "cut", *ignore, "--release", str(release), "--root", str(root)]
        cmd += ["--arch", arch] if arch else []
        r = subprocess.run([*cmd, *slices], capture_output=True, text=True, check=False)
        sys.stderr.write(r.stdout + r.stderr)
        if r.returncode == 0:
            return installed(root), ""
    finally:
        shutil.rmtree(root, ignore_errors=True)
    lines = [ln for ln in r.stderr.splitlines() if ln.strip()]
    error = lines[-1] if lines else f"chisel cut exited {r.returncode}"
    if any(marker in error.lower() for marker in UNREACHABLE):
        raise Unreachable(error)
    return None, error


def cut_once(slices: list[str], arch: str, report: common.Report) -> None:
    paths, error = cut(Path.cwd(), slices, arch, ignore_flags())
    if paths is None:
        report.add("block", "cut-failed", " ".join(slices), error=error)
    else:
        report.data["files"] = len(paths)


def changed_slices(base: str) -> dict[str, list[str]] | None:
    """SDF path -> the slices it has both at base and in the worktree."""
    status = common.git(["diff", "--name-status", base, "--", "slices/*.yaml"])
    if status is None:
        return None
    out = {}
    for line in status.splitlines():
        code, _, path = line.partition("\t")
        if not code.startswith("M"):
            continue  # added, removed and renamed SDFs are check-diff's to report
        old = yaml.safe_load(common.git(["show", f"{base}:{path}"]) or "") or {}
        new = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        before = old.get("slices") or {}
        kept = [s for s in (new.get("slices") or {}) if s in before]
        out[path] = [f"{new.get('package')}_{s}" for s in kept]
    return out


def base_release(base: str, into: Path) -> bool:
    """Materialise base's chisel.yaml and slices/ as a release dir."""
    tar = subprocess.run(
        ["git", "archive", "--format=tar", base, "chisel.yaml", "slices"],
        capture_output=True,
        check=False,
    )
    if tar.returncode:
        return False
    untar = subprocess.run(
        ["tar", "-x", "-C", str(into)], input=tar.stdout, check=False
    )
    return untar.returncode == 0


def cut_diff(base: str, named: list[str], arch: str, report: common.Report) -> None:
    rev = common.comparison(base, report)
    changed = changed_slices(rev)
    report.data["compared"] = []
    if changed is None:
        report.mark_unavailable(
            "base", f"git diff against {base!r} failed; is the ref present?"
        )
        return
    work = [
        (sdf, s)
        for sdf, slices in changed.items()
        for s in slices
        if not named or s in named
    ]
    if not work:
        return
    ignore = ignore_flags()
    release = Path(tempfile.mkdtemp(prefix="chisel-base.", dir=Path.cwd()))
    try:
        if not base_release(rev, release):
            report.mark_unavailable(
                "base", f"cannot read chisel.yaml and slices/ at {base!r}"
            )
            return
        for sdf, s in work:
            before, _ = cut(release, [s], arch, ignore)
            if before is None:
                report.add("info", "base-cut-failed", sdf, slice=s)
                continue
            after, error = cut(Path.cwd(), [s], arch, ignore)
            if after is None:
                report.add("block", "cut-failed", sdf, slice=s, error=error)
                continue
            for path in sorted(before - after):
                report.add("warn", "lost", sdf, slice=s, path=path)
            report.data["compared"].append(
                common.Flow(slice=s, before=len(before), after=len(after))
            )
    finally:
        shutil.rmtree(release, ignore_errors=True)


def main(argv: list[str]) -> int:
    arch, base = "", None
    slices: list[str] = []
    it = iter(argv)
    for a in it:
        if a == "--arch":
            arch = next(it, "")
            if not arch:
                return common.usage(USAGE)
        elif a.startswith("--arch="):
            arch = a.split("=", 1)[1]
        elif a == "--base":
            base = ""  # derived from the manifest once there is a report
        elif a.startswith("--base="):
            base = a.split("=", 1)[1]
            if not base:
                return common.usage(USAGE)
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif a.startswith("-") or not a:
            return common.usage(USAGE)
        else:
            slices.append(a)
    if not slices and base is None:
        return common.usage(USAGE)

    report = common.Report(CODES)
    report.data.update(arch=arch or None, slices=slices)
    if base == "":
        base = common.derived_base(report)
    if not shutil.which("chisel"):
        report.mark_unavailable("cut", "chisel is not installed")
    if report.unavailable:
        return report.emit()
    try:
        if base is None:
            cut_once(slices, arch, report)
        else:
            cut_diff(base, slices, arch, report)
    except Unreachable as e:
        report.mark_unavailable("cut", str(e))
    return report.emit()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
