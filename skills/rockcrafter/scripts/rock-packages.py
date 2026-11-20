#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""rock-packages: what the Ubuntu archive (or a PPA) and chisel-releases know
about the packages a rock stages. For each package: its version, description,
the executables it ships, what it depends on and its slices on the release.
It decides nothing and writes nothing: rockcraft.yaml comes from
`rockcraft init`, and what goes into it is the author's call.

Usage:
  rock-packages.py <pkg> [<pkg> ...] [--release 24.04]
  options: --ppa <owner>/<name> (the packages come from a PPA; chisel only
           reads the Ubuntu archive, so no slices are looked up), --arch <arch>
           (default amd64), --chisel-release <checkout> (read slices from a
           chisel-releases checkout: slices not yet upstream)

The release defaults to the newest supported LTS. Fails when a package does
not exist, or an archive package has no slices on the release. Unavailable
when the archive, the PPA or chisel-releases cannot be reached, or dpkg-deb is
not installed to list a package's executables.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import rocklib as rl

CODES = {
    "package-not-found": "the package is not in the archive / PPA for this release and architecture",
    "missing-slices": "an archive package has no slices on the release: author them, or build unchiselled",
}


def describe(stanza: dict) -> tuple[str, str]:
    """(summary, description) of a Packages stanza."""
    lines = stanza.get("Description", "").splitlines()
    summary = lines[0].strip() if lines else ""
    body = [ln.strip() for ln in lines[1:] if ln.strip() and ln.strip() != "."]
    return summary, "\n".join(body) or summary


def binaries(stanza: dict, report: common.Report) -> list[str] | None:
    try:
        return rl.deb_binaries(stanza)
    except rl.Unavailable as e:
        if not any(u["check"] == "binaries" for u in report.unavailable):
            report.mark_unavailable("binaries", str(e))
        return None


def facts(a: argparse.Namespace, rel: rl.Release, report: common.Report) -> None:
    ref = a.chisel_release or rel.branch
    packages = report.data["packages"] = {}
    for pkg in a.packages:
        st = rl.package(pkg, rel, a.arch, ppa=a.ppa)
        if not st:
            report.add("block", "package-not-found", pkg, release=rel.codename, arch=a.arch,
                       ppa=a.ppa)  # fmt: skip
            continue
        summary, description = describe(st)
        entry = packages[pkg] = {
            "version": st["Version"],
            "upstream version": rl.upstream_version(st["Version"]),
            "summary": summary,
            "description": description,
            "binaries": binaries(st, report),
            "depends": rl.deps(st),
        }
        if a.ppa:
            continue
        entry["slices"] = rl.slices_of(ref, pkg)
        if entry["slices"] is None:
            report.add("block", "missing-slices", pkg, release=ref)


def main() -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("packages", nargs="*")
    ap.add_argument("--release")
    ap.add_argument("--ppa")
    ap.add_argument("--chisel-release")
    ap.add_argument("--arch", default="amd64")
    a, unknown = ap.parse_known_args()
    if unknown or not a.packages:
        return common.usage(__doc__.strip())
    report = common.Report(CODES)
    try:
        try:
            rel = rl.resolve_release(a.release)
        except ValueError as e:
            return common.usage(str(e))
        release = {"version": rel.version, "codename": rel.codename, "base": rel.base}
        if not a.ppa:
            release["slices from"] = a.chisel_release or rel.branch
        report.data["release"] = common.Flow(release)
        if a.ppa:
            report.data["ppa"] = a.ppa
        facts(a, rel, report)
    except rl.Unavailable as e:
        report.mark_unavailable("discovery", str(e))
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
