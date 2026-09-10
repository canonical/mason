#!/usr/bin/env python3
"""
List files and maintainer scripts inside a debian package to aid chisel slice authoring.

Usage: deb-list.py <package> [arch]
  package    debian package name (e.g. bash, libssl3)
  arch       target architecture (default: host arch; fallback amd64)
             valid values: amd64 arm64 armhf i386 ppc64el riscv64 s390x

Output:
  - package header (name, version, arch)
  - Depends: line for wiring essential: entries
  - non-directory files, lexicographically sorted: octal mode, owner and path,
    then what file(1) makes of it on the next line (ELF binary, shell script,
    symbolic link to <target>, gzip data, ASCII text, ...)
  - the postinst script in full, if the package has one -- chisel never runs
    it, so whatever it does is yours to reproduce or drop

Requirements: dpkg-deb, file, python3, and network access to the ubuntu mirror
(archive.ubuntu.com / ports.ubuntu.com). No sudo, no apt, no populated apt
cache: the .deb is fetched straight from the mirror's Packages index.
Note: the release suite is read from ./chisel.yaml -- run from a chisel-releases
      checkout (or a dir whose chisel.yaml names the suite).
"""

import gzip
import io
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# Only install-time scripts matter for slice authoring; remove scripts are irrelevant.

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
    except OSError:
        return None


def _filename_from_packages(data, pkg):
    """Find pkg's `Filename:` (pool path) in a gzipped Packages index blob."""
    try:
        text = gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "replace")
    except (OSError, EOFError):
        return None
    cur = {}
    for line in text.splitlines():
        if not line:
            if cur.get("Package") == pkg:
                return cur.get("Filename")
            cur = {}
        elif ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            cur[k] = v.strip()
    return cur.get("Filename") if cur.get("Package") == pkg else None


def download_deb(pkg, arch, suite, workdir):
    """Fetch pkg's .deb straight from the mirror: walk the Packages indexes for
    suite{,-updates,-security} x components, resolve Filename, download it."""
    base = arch_base_url(arch)
    for try_suite in (f"{suite}-updates", f"{suite}-security", suite):
        for comp in _COMPONENTS:
            data = _fetch(f"{base}/dists/{try_suite}/{comp}/binary-{arch}/Packages.gz")
            if data is None:
                continue
            filename = _filename_from_packages(data, pkg)
            if not filename:
                continue
            deb = _fetch(f"{base}/{filename}")
            if deb is None:
                return None
            dest = Path(workdir) / Path(filename).name
            dest.write_bytes(deb)
            return dest
    return None


def deb_field(deb_path, field):
    result = run(["dpkg-deb", "-f", str(deb_path), field], capture=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


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


def file_descriptions(deb_path, workdir, paths):
    """file(1) output for each path, in order. Symlinks are described, not followed."""
    root = Path(workdir) / "root"
    root.mkdir()
    run(["dpkg-deb", "-x", str(deb_path), str(root)], capture=True)
    out = []
    # chunked: a big package (python3.x, perl) runs past ARG_MAX in one go.
    for i in range(0, len(paths), 500):
        chunk = [str(root) + p for p in paths[i : i + 500]]
        result = run(["file", "-bh", "--", *chunk], capture=True)
        out += result.stdout.splitlines()
    return out


def main():
    args = sys.argv[1:]

    if not args:
        print("usage: deb-list.py <package> [arch]", file=sys.stderr)
        sys.exit(1)

    pkg = args[0]
    arch = args[1] if len(args) > 1 else host_arch()

    suite = read_suite()
    if not suite:
        print(
            "error: could not read the release suite from ./chisel.yaml",
            file=sys.stderr,
        )
        print("hint:  run deb-list.py from a chisel-releases checkout", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as workdir:
        deb = download_deb(pkg, arch, suite, workdir)
        if not deb:
            print(
                f"error: {pkg} (arch {arch}) not found on the mirror for suite {suite}",
                file=sys.stderr,
            )
            print(
                "hint:  check the package name + arch; the mirror must be reachable",
                file=sys.stderr,
            )
            sys.exit(1)

        version = deb_field(deb, "Version")
        depends = deb_field(deb, "Depends")

        print(f"package: {pkg}  version: {version}  arch: {arch}\n")

        if depends:
            print(f"Depends: {depends}\n")

        entries = deb_contents(deb)
        kinds = file_descriptions(deb, workdir, [e[0] for e in entries])
        print("files (lexicographic):")
        for (path, perms, owner), kind in zip(entries, kinds):
            print(f"  {perms} {owner}  {path}")
            print(f"      {kind}")

        postinst = deb_postinst(deb, workdir)
        print("\npostinst:" + ("" if postinst else " none"))
        if postinst:
            print(postinst.rstrip())


if __name__ == "__main__":
    main()
