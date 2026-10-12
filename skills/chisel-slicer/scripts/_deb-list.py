#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""
List files and maintainer scripts inside a debian package to aid chisel slice authoring.

Usage: deb-list.py <package> [arch]
  package    debian package name (e.g. bash, libssl3)
  arch       target architecture (default: host arch; fallback amd64)
             valid values: amd64 arm64 armhf i386 ppc64el riscv64 s390x

Output: the YAML report described in common.py, then the package:
  - package, version, arch and the suite searched
  - depends and pre-depends, for runtime dependency inspection
  - files: every non-directory entry, lexicographically sorted, with its octal
    mode, owner and what file(1) makes of it (ELF binary, shell script,
    symbolic link to <target>, gzip data, ASCII text, ...)
  - postinst: the script in full, or null -- chisel never runs it, so whatever
    it does is yours to reproduce or drop

A package missing from every public index checked fails; a lookup that cannot
establish either answer is unavailable.

Requirements: dpkg-deb and network access to the ubuntu mirror
(archive.ubuntu.com / ports.ubuntu.com). file(1) gives the file types; without
it the bundled file.py stands in with less detail (no ELF version/BuildID, no
timestamps) and an info finding says so. No sudo, no apt, no populated apt
cache: the .deb is fetched straight from the mirror's Packages index. Only
public mirrors are supported, not authenticated Ubuntu Pro archives or
arbitrary manifest archive configuration. The first matching package in the
updates/security/base search is inspected; this is not chisel's version resolver.
Note: the release suite is read from ./chisel.yaml -- run from a chisel-releases
      checkout (or a dir whose chisel.yaml names the suite).
"""

import gzip
import io
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zlib
from pathlib import Path

try:
    import _common as common
    import _file as filetype
except ImportError:
    import common
    import file as filetype

CODES = {
    "absent": "not in the public ubuntu indexes for this suite and arch; ubuntu pro archives are not checked",
    "file-fallback": "file(1) is not installed, so the bundled classifier gave the file types, with less detail",
}


class ArchiveError(Exception):
    """The archive lookup could not establish a package result."""


def perms_to_octal(perms):
    """Convert symbolic permissions string (e.g. -rwsr-xr-x) to octal (e.g. 4755).

    Keeps setuid/setgid/sticky (s/S/t/T in the exec positions) -- exactly the
    mode information that matters for security-sensitive binaries like sudo.
    """

    def triplet(t):
        return (
            (4 if t[0] == "r" else 0)
            + (2 if t[1] == "w" else 0)
            + (1 if t[2] in "xst" else 0)
        )

    p = perms[1:10]  # skip type char, take 9 permission chars
    special = (
        (4 if p[2] in "sS" else 0)
        + (2 if p[5] in "sS" else 0)
        + (1 if p[8] in "tT" else 0)
    )
    return f"{special}{triplet(p[0:3])}{triplet(p[3:6])}{triplet(p[6:9])}"


def run(cmd, cwd=None, check=True, capture=False):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=capture, text=True)


def host_arch():
    try:
        return run(["dpkg", "--print-architecture"], capture=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "amd64"


# Ubuntu mirrors 403 python-urllib's default UA; apt's UA is always accepted.
_UA = "Debian APT-HTTP/1.3"
_COMPONENTS = ["main", "universe", "restricted", "multiverse"]


def arch_base_url(arch):
    # amd64/i386 live on archive.ubuntu.com; every other port on ports.ubuntu.com.
    if arch in ("amd64", "i386"):
        return "http://archive.ubuntu.com/ubuntu"
    return "http://ports.ubuntu.com/ubuntu-ports"


def read_suite():
    """Base release codename from ./chisel.yaml (archives.ubuntu.suites[0]).

    Minimal parse (no pyyaml): scan for the first token under `suites:` in either
    inline (`suites: [noble, ...]`) or block (`suites:\\n  - noble`) form, then
    strip any pocket suffix so we get the base suite (we add -updates/-security).
    """
    try:
        text = Path("chisel.yaml").read_text()
    except OSError:
        return None
    m = re.search(r"suites:\s*\[\s*([A-Za-z0-9.-]+)", text)  # inline list
    if not m:
        m = re.search(r"suites:\s*\n\s*-\s*([A-Za-z0-9.-]+)", text)  # block list
    if not m:
        return None
    return re.sub(r"-(updates|security|backports|proposed)$", "", m.group(1))


def _fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except OSError as e:
        raise ArchiveError(f"could not fetch {url}: {e}") from e


def _filename_from_packages(data, pkg):
    """Find pkg's `Filename:` (pool path) in a gzipped Packages index blob."""
    try:
        text = gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "replace")
    except (OSError, EOFError, zlib.error) as e:
        raise ArchiveError(f"invalid Packages index: {e}") from e
    cur = {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur and not cur.get("Package"):
                raise ArchiveError(
                    "invalid Packages index: record has no Package field"
                )
            if cur.get("Package") == pkg:
                if not cur.get("Filename"):
                    raise ArchiveError(f"Packages entry for {pkg} has no Filename")
                return cur["Filename"]
            cur = {}
        elif not line.startswith((" ", "\t")):
            k, separator, v = line.partition(":")
            if not separator or not k or any(c.isspace() for c in k):
                raise ArchiveError("invalid Packages index: malformed field")
            cur[k] = v.strip()
    return None


def download_deb(pkg, arch, suite, workdir):
    """Fetch pkg's .deb straight from the mirror: walk the Packages indexes for
    suite{,-updates,-security} x components, resolve Filename, download it."""
    base = arch_base_url(arch)
    failures = []
    for try_suite in (f"{suite}-updates", f"{suite}-security", suite):
        for comp in _COMPONENTS:
            url = f"{base}/dists/{try_suite}/{comp}/binary-{arch}/Packages.gz"
            try:
                filename = _filename_from_packages(_fetch(url), pkg)
            except ArchiveError as e:
                failures.append(f"{url}: {e}")
                continue
            if not filename:
                continue
            deb = _fetch(f"{base}/{filename}")
            dest = Path(workdir) / Path(filename).name
            dest.write_bytes(deb)
            return dest
    if failures:
        raise ArchiveError(
            f"package absence not established; {len(failures)} index lookups failed; "
            f"first failure: {failures[0]}"
        )
    return None


def deb_field(deb_path, field):
    result = run(["dpkg-deb", "-f", str(deb_path), field], capture=True)
    return result.stdout.strip()


def deb_contents(deb_path):
    """
    Returns list of (path, perms, owner), lexicographically sorted.
    Directories are excluded -- chisel creates them implicitly.

    dpkg-deb --contents columns: perms links owner/group size date time path [-> target]
    """
    result = run(["dpkg-deb", "--contents", str(deb_path)], capture=True)
    entries = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        perms = parts[0]
        owner = parts[1]  # format: user/group
        entry_type = perms[0]  # - d l

        if entry_type == "d":
            continue  # skip directories

        # NOTE: removeprefix, not lstrip("./") -- lstrip strips any run of '.'
        # and '/' chars, corrupting targets like ../lib/foo or /etc/foo.
        if entry_type == "l" and len(parts) >= 3 and parts[-2] == "->":
            path = parts[-3].removeprefix("./")
        else:
            path = parts[-1].removeprefix("./")

        if not path or path == ".":
            continue

        entries.append((f"/{path}", perms_to_octal(perms), owner))

    entries.sort(key=lambda e: e[0])
    return entries


def deb_postinst(deb_path, workdir):
    """The package's postinst script, or None if it has none."""
    ctrl_dir = Path(workdir) / "ctrl"
    ctrl_dir.mkdir()
    run(["dpkg-deb", "--control", str(deb_path), str(ctrl_dir)], capture=True)
    path = ctrl_dir / "postinst"
    return path.read_text() if path.exists() else None


def classify(paths):
    """file(1)'s brief line for each path, or the bundled classifier's without it.
    Symlinks are described, not followed."""
    if not shutil.which("file"):
        return [filetype.describe(p) for p in paths]
    out = []
    # chunked: a big package (python3.x, perl) runs past ARG_MAX in one go.
    for i in range(0, len(paths), 500):
        result = run(["file", "-bh", "--", *paths[i : i + 500]], capture=True)
        out += result.stdout.splitlines()
    return out


def file_descriptions(deb_path, workdir, paths):
    root = Path(workdir) / "root"
    root.mkdir()
    run(["dpkg-deb", "-x", str(deb_path), str(root)], capture=True)
    return classify([str(root) + p for p in paths])


def main(report):
    args = sys.argv[1:]
    if len(args) not in (1, 2):
        return common.usage("usage: deb-list.py <package> [arch]")

    if not shutil.which("dpkg-deb"):
        report.mark_unavailable("tools", "dpkg-deb is not installed")
        return report.emit()

    pkg = args[0]
    arch = args[1] if len(args) > 1 else host_arch()
    suite = read_suite()
    if not suite:
        report.mark_unavailable(
            "release",
            "could not read the release suite from ./chisel.yaml; run from a chisel-releases checkout",
        )
        return report.emit()

    report.data.update(package=pkg, arch=arch, suite=suite)
    with tempfile.TemporaryDirectory() as workdir:
        deb = download_deb(pkg, arch, suite, workdir)
        if not deb:
            report.add("block", "absent", pkg, arch=arch, suite=suite)
            return report.emit()

        report.data["version"] = deb_field(deb, "Version")
        for field in ("Depends", "Pre-Depends"):
            value = deb_field(deb, field)
            if value:
                report.data[field.lower()] = value
        if not shutil.which("file"):
            report.add("info", "file-fallback", pkg)
        entries = deb_contents(deb)
        kinds = file_descriptions(deb, workdir, [e[0] for e in entries])
        report.data["files"] = [
            common.Flow(path=path, mode=perms, owner=owner, type=kind)
            for (path, perms, owner), kind in zip(entries, kinds)
        ]
        report.data["postinst"] = deb_postinst(deb, workdir)
    return report.emit()


def cli():
    report = common.Report(CODES)
    try:
        return main(report)
    except ArchiveError as e:
        report.mark_unavailable("archive", str(e))
    except subprocess.CalledProcessError as e:
        report.mark_unavailable(
            "package", f"{' '.join(e.cmd[:2])} failed: exit {e.returncode}"
        )
    except (OSError, UnicodeError, subprocess.SubprocessError) as e:
        report.mark_unavailable("package", f"verification failed: {e}")
    return report.emit()


if __name__ == "__main__":
    sys.exit(cli())
