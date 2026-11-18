"""rocklib: the rock helpers' shared knowledge of Ubuntu, its archive and chisel.

Not a script -- the rock helpers beside it import it (as _rocklib.py once
synced into a skill, like _common.py). Stdlib only.

Nothing release-specific is hardcoded: Ubuntu releases come from
changelogs.ubuntu.com/meta-release{,-development}, package facts from the
archive / PPA Packages indexes, slices from canonical/chisel-releases. Fetches
are cached for a day under ~/.cache/mason; an unreachable source raises
Unavailable for the caller to report, never an offline substitute.
"""

from __future__ import annotations

import gzip
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the installed skill


class Unavailable(Exception):
    """A source the answer depends on could not be reached."""


CACHE = Path.home() / ".cache" / "mason"
UA = "Debian APT-HTTP/1.3"
COMPONENTS = ("main", "universe", "restricted", "multiverse")
RAW_SLICES = "https://raw.githubusercontent.com/canonical/chisel-releases/{branch}/slices/{pkg}.yaml"
_mem: dict[str, bytes | None] = {}
_failed: set[str] = set()  # urls that could not be reached (vs 404 = absent)


def fetch_failed(url: str) -> bool:
    return url in _failed


# --- network -----------------------------------------------------------------


def fetch(url: str, tries: int = 4, timeout: int = 10) -> bytes | None:
    """GET with retries. reads exactly Content-Length: the Ubuntu mirrors keep
    the connection open, so a bare read() blocks until the timeout. 404 -> None."""
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                n = r.headers.get("Content-Length")
                return r.read(int(n)) if n else r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    _failed.add(url)
    return None


def cached(url: str, max_age: int = 86400, gunzip: bool = False) -> bytes | None:
    """fetch, cached in memory and on disk under ~/.cache/mason."""
    if url in _mem:
        return _mem[url]
    f = CACHE / re.sub(r"[^A-Za-z0-9.-]+", "_", url)
    if f.exists() and time.time() - f.stat().st_mtime < max_age:
        _mem[url] = f.read_bytes()
        return _mem[url]
    data = fetch(url)
    if data is not None and gunzip:
        data = gzip.decompress(data)
    if data is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    _mem[url] = data
    return data


# --- Ubuntu releases -----------------------------------------------------------


@dataclass(frozen=True)
class Release:
    version: str  # "24.04"
    codename: str  # "noble"
    lts: bool
    supported: bool  # supported, or the development release

    @property
    def branch(self) -> str:  # chisel-releases branch
        return f"ubuntu-{self.version}"

    @property
    def base(self) -> str:  # rockcraft base / build-base
        return f"ubuntu@{self.version}"


def _meta_release() -> list[Release]:
    out = []
    for url, dev in (
        ("http://changelogs.ubuntu.com/meta-release", False),
        ("http://changelogs.ubuntu.com/meta-release-development", True),
    ):
        raw = cached(url)
        if not raw:
            continue
        for block in raw.decode("utf-8", "replace").split("\n\n"):
            f = dict(ln.split(": ", 1) for ln in block.splitlines() if ": " in ln)
            m = re.match(r"(\d+\.\d+)", f.get("Version", ""))
            if f.get("Dist") and m:
                out.append(
                    Release(
                        m.group(1),
                        f["Dist"],
                        "LTS" in f.get("Version", ""),
                        f.get("Supported") == "1" or dev,
                    )
                )
    return out


def releases() -> list[Release]:
    """every known Ubuntu release, newest last (deduplicated by version)."""
    seen: dict[str, Release] = {}
    for r in _meta_release():
        seen[r.version] = r
    return sorted(
        seen.values(), key=lambda r: tuple(int(x) for x in r.version.split("."))
    )


def resolve_release(text: str | None) -> Release:
    """ubuntu-24.04 / ubuntu@24.04 / ubuntu:24.04 / ubuntu/24.04 / 24.04 / noble
    -> Release. None/empty -> the newest supported LTS. Unknown -> ValueError;
    release list unreachable -> Unavailable."""
    rels = releases()
    if not rels:
        raise Unavailable(
            "Ubuntu release list unreachable (changelogs.ubuntu.com/meta-release)"
        )
    if not text:
        lts = [r for r in rels if r.lts and r.supported]
        return lts[-1] if lts else rels[-1]
    t = text.strip().lower()
    for r in rels:
        if t == r.codename:
            return r
    m = re.fullmatch(r"(?:ubuntu[-@:/])?(\d\d\.\d\d)", t)
    for r in rels:
        if m and r.version == m.group(1):
            return r
    known = ", ".join(f"{r.version} ({r.codename})" for r in rels if r.supported)
    raise ValueError(f"unknown Ubuntu release {text!r} -- supported: {known}")


# --- Packages indexes (archive + PPA) ------------------------------------------


def _stanza(raw: bytes, pkg: str) -> dict | None:
    i = raw.find(f"\nPackage: {pkg}\n".encode())
    if i < 0:
        if not raw.startswith(f"Package: {pkg}\n".encode()):
            return None
        i = -1
    end = raw.find(b"\n\n", i + 1)
    cur, key = {}, None
    for line in (
        raw[i + 1 : end if end > 0 else len(raw)]
        .decode("utf-8", "replace")
        .splitlines()
    ):
        if line.startswith((" ", "\t")) and key:
            cur[key] += "\n" + line
        elif ":" in line:
            key, _, v = line.partition(":")
            cur[key] = v.strip()
    return cur


def archive_base(arch: str) -> str:
    return (
        "http://archive.ubuntu.com/ubuntu"
        if arch in ("amd64", "i386")
        else "http://ports.ubuntu.com/ubuntu-ports"
    )


def package(
    pkg: str, rel: Release, arch: str = "amd64", ppa: str | None = None
) -> dict | None:
    """Packages stanza for pkg (+ `_url` of its .deb), from the archive or a PPA
    (`owner/name`). archive: -updates first (newest), small indexes first.
    None when absent; Unavailable when an index it needed couldn't be fetched
    (a denied fetch is not evidence of absence)."""
    missed = []
    if ppa:
        base = f"https://ppa.launchpadcontent.net/{ppa}/ubuntu"
        suites, comps = (rel.codename,), ("main",)
    else:
        base = archive_base(arch)
        suites, comps = (f"{rel.codename}-updates", rel.codename), COMPONENTS
    for comp in comps:
        for suite in suites:
            url = f"{base}/dists/{suite}/{comp}/binary-{arch}/Packages.gz"
            raw = cached(url, gunzip=True)
            if raw is None and fetch_failed(url):
                missed.append(url)
            st = _stanza(raw, pkg) if raw else None
            if st:
                st["_url"] = f"{base}/{st['Filename']}"
                return st
    if missed:
        raise Unavailable(f"package index unreachable: {missed[0]}")
    return None


def deps(stanza: dict) -> list[str]:
    """first alternative of each Depends entry, version constraints dropped."""
    out = []
    for d in stanza.get("Depends", "").split(","):
        name = d.split("|")[0].strip().split(" ")[0].split(":")[0]
        if name:
            out.append(name)
    return out


def upstream_version(debver: str, full: bool = False) -> str:
    """2:1.24.0-2ubuntu7 -> 1.24 (or 1.24.0 with full=True)."""
    up = re.sub(r"^\d+:", "", debver).rsplit("-", 1)[0]
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", up)
    if not m:
        return up.split("+")[0].split("~")[0]
    return (
        ".".join(g for g in m.groups() if g) if full else f"{m.group(1)}.{m.group(2)}"
    )


def deb_facts(stanza: dict) -> tuple[list[str], str | None]:
    """(binaries, SPDX licence) from the downloaded .deb (needs dpkg-deb)."""
    data = fetch(stanza["_url"])
    if not data:
        return [], None
    with tempfile.TemporaryDirectory() as tmp:
        deb = Path(tmp, "p.deb")
        deb.write_bytes(data)
        listing = subprocess.run(
            ["dpkg-deb", "-c", str(deb)], capture_output=True, text=True, check=False
        ).stdout
        bins = sorted(
            {
                ln.split()[5][1:]
                for ln in listing.splitlines()
                if len(ln.split()) > 5
                and ln.split()[5].startswith(
                    ("./usr/bin/", "./usr/sbin/", "./bin/", "./sbin/")
                )
                and not ln.split()[5].endswith("/")
            }
        )
        subprocess.run(
            ["dpkg-deb", "-x", str(deb), tmp], capture_output=True, check=False
        )
        cr = Path(tmp, "usr/share/doc", stanza["Package"], "copyright")
        return bins, (
            license_from_text(cr.read_text(errors="replace")) if cr.is_file() else None
        )


# --- licences ------------------------------------------------------------------

# DEP-5 / short names -> the plain SPDX ids rockcraft accepts (no -only / -or-later).
_SHORT = {
    "gpl-2": "GPL-2.0",
    "gpl-2+": "GPL-2.0",
    "gpl-3": "GPL-3.0",
    "gpl-3+": "GPL-3.0",
    "lgpl-2": "LGPL-2.0",
    "lgpl-2+": "LGPL-2.0",
    "lgpl-2.1": "LGPL-2.1",
    "lgpl-2.1+": "LGPL-2.1",
    "lgpl-3": "LGPL-3.0",
    "lgpl-3+": "LGPL-3.0",
    "agpl-3": "AGPL-3.0",
    "agpl-3+": "AGPL-3.0",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "expat": "MIT",
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "isc": "ISC",
    "mpl-2.0": "MPL-2.0",
    "zlib": "Zlib",
    "artistic": "Artistic-1.0",
    "psf-2": "Python-2.0",
    "public-domain": "CC0-1.0",
    "unlicense": "Unlicense",
    "bsl-1.0": "BSL-1.0",
}
_PROSE = (
    (r"GNU Affero General Public License.{0,80}version 3", "AGPL-3.0"),
    (r"GNU Lesser General Public License.{0,80}version 3", "LGPL-3.0"),
    (r"GNU Lesser General Public License.{0,80}version 2\.1", "LGPL-2.1"),
    (r"GNU General Public License.{0,80}version 3", "GPL-3.0"),
    (r"GNU General Public License.{0,80}version 2", "GPL-2.0"),
    (r"Apache License,? Version 2\.0", "Apache-2.0"),
    (r"Mozilla Public License,? (?:Version|v\.?) ?2\.0", "MPL-2.0"),
    (
        r"Permission is hereby granted, free of charge, to any person obtaining a copy",
        "MIT",
    ),
    (
        r"Permission to use, copy, modify, and(?:/or)? distribute this software for any purpose",
        "ISC",
    ),
    (
        r"Redistribution and use in source and binary forms.{0,600}Neither the name",
        "BSD-3-Clause",
    ),
    (r"Redistribution and use in source and binary forms", "BSD-2-Clause"),
)


def spdx(name: str | None) -> str | None:
    """normalise an SPDX-ish id (`GPL-3.0-or-later`, `GPL-3+`, `MIT`) to what
    rockcraft accepts."""
    if not name:
        return None
    n = name.strip().strip("\"'()")
    n = re.split(r"\s+(?:OR|AND|WITH)\s+|\s*/\s*", n)[0].strip(
        "()"
    )  # first id of an expression
    n = re.sub(r"-(?:or-later|only)$", "", n)
    return _SHORT.get(n.lower(), n if re.fullmatch(r"[A-Za-z0-9.+-]+", n) else None)


def license_from_text(text: str) -> str | None:
    """SPDX id from a debian/copyright (DEP-5 or prose) or a LICENSE file."""
    m = re.search(
        r"^Files:\s*\*\s*$.*?^License:\s*(\S+)", text, re.MULTILINE | re.DOTALL
    ) or re.search(r"^License:\s*(\S+)", text, re.MULTILINE)
    if m and m.group(1).lower() in _SHORT:
        return _SHORT[m.group(1).lower()]
    m = re.search(r"/usr/share/common-licenses/([A-Za-z0-9.+-]+)", text)
    if m and m.group(1).lower().rstrip(".") in _SHORT:
        return _SHORT[m.group(1).lower().rstrip(".")]
    m = re.search(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)", text)
    if m:
        return spdx(m.group(1))
    flat = " ".join(text.split())
    for pat, sid in _PROSE:
        if re.search(pat, flat, re.IGNORECASE):
            return sid
    return None


# --- slices --------------------------------------------------------------------

_SLICE_KEY = re.compile(r"^  ([a-z0-9][a-z0-9-]*):\s*(#.*)?$")


def slice_names(sdf: str) -> list[str]:
    names, inside = [], False
    for line in sdf.splitlines():
        if re.match(r"^slices:\s*(#.*)?$", line):
            inside = True
            continue
        if inside and line and not line.startswith((" ", "#")):
            break
        m = _SLICE_KEY.match(line) if inside else None
        if m:
            names.append(m.group(1))
    return names


def release_ref(text: str) -> str:
    """a chisel-releases checkout dir (as-is) or any release spelling -> branch."""
    return text if Path(text).is_dir() else resolve_release(text).branch


def read_sdf(release: str, pkg: str) -> str | None:
    """slices/<pkg>.yaml on a chisel-releases branch or local checkout; None if absent."""
    ref = release_ref(release)
    local = Path(ref)
    if local.is_dir():
        if not (local / "chisel.yaml").is_file():
            raise ValueError(
                f"{ref} has no chisel.yaml -- not a chisel-releases checkout"
            )
        sdf = local / "slices" / f"{pkg}.yaml"
        return sdf.read_text() if sdf.is_file() else None
    url = RAW_SLICES.format(branch=ref, pkg=pkg)
    data = cached(url, max_age=3600)
    if data is None and fetch_failed(url):
        raise Unavailable(f"chisel-releases unreachable ({url})")
    return data.decode() if data is not None else None


def slices_of(release: str, pkg: str) -> list[str] | None:
    """['<pkg>_<slice>', ...] or None when the package has no slices file."""
    sdf = read_sdf(release, pkg)
    return None if sdf is None else [f"{pkg}_{n}" for n in slice_names(sdf)]
