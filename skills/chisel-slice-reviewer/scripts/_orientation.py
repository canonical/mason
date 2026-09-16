#!/usr/bin/env python3
"""orientation: deterministic orientation for the slice-authoring agent -- run
FIRST, every time. Reports where you are, which tools this machine actually
has, the target release + manifest format parsed from ./chisel.yaml, and the
live release landscape (discovered, never hardcoded). Work from this, not from
guesses.

The output is YAML, so it reads as prose and parses as data. Every value is a
fact read off the machine or the checkout; nothing here is inferred.

Usage: orientation.py

Stdlib only, so it runs before anything else is known to work.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

TOOLS = ("chisel", "dpkg-deb", "file", "spread", "uv", "python3", "git")
DEFAULT_URL = "https://github.com/canonical/chisel-releases.git"
RAW = "https://raw.githubusercontent.com/canonical/chisel-releases"

_VERSION = re.compile(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?")
_FORMAT = re.compile(r"^format:[ \t]*(.*)$", re.MULTILINE)
_UBUNTU_VERSION = re.compile(r"^[ \t]+version:[ \t]*(.*)$", re.MULTILINE)
_SUITES = re.compile(r"suites:[ \t]*(.*)$", re.MULTILINE)
_COMPONENTS = re.compile(r"components:[ \t]*(.*)$", re.MULTILINE)
_EOL = re.compile(r"^[ \t]*end-of-life:[ \t]*(.*)$", re.MULTILINE)


def q(value: str | None) -> str:
    """YAML-safe scalar: quoted, so a version or a date is not read as a float
    or a timestamp, and an empty value comes back as null rather than nothing."""
    if not value:
        return "null"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run(cmd: list[str], timeout: int = 20, require_ok: bool = True) -> str | None:
    """stdout of a command, or None if it is missing, hangs, or (unless
    require_ok is off) exits non-zero."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 or not require_ok else None


def first(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def tools() -> list[str]:
    # --version only. a bare "<tool> version" fallback would be a real
    # invocation -- spread would read spread.yaml and treat it as a job filter --
    # and orientation must stay read-only.
    out = ["tools:"]
    for t in TOOLS:
        if not shutil.which(t):
            out.append(f"  {t}: {{present: false, version: null}}")
            continue
        text = run([t, "--version"], timeout=10, require_ok=False) or ""
        m = _VERSION.search(text)
        # present but unversioned is a fact of its own: chisel prints "unknown"
        # on an unstamped build, spread has no version flag at all. null is
        # reserved for a tool that is not here to have a version.
        out.append(f"  {t}: {{present: true, version: {q(m.group(0) if m else 'unknown')}}}")
    return out


def checkout(today: str) -> list[str]:
    """Facts about ./chisel.yaml, or the release: null line when there is none."""
    try:
        text = Path("chisel.yaml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["release: null  # no ./chisel.yaml here; cd into a chisel-releases checkout first"]

    branch = (run(["git", "branch", "--show-current"]) or "").strip()
    eol = first(_EOL, text)
    try:
        n = len([f for f in os.listdir("slices") if not f.startswith(".")])
    except OSError:
        n = 0
    return [
        f"branch: {q(branch)}",
        f"ubuntu version: {q(first(_UBUNTU_VERSION, text).replace(chr(39), ''))}",
        f"manifest format: {q(first(_FORMAT, text))}",
        f"suites: {first(_SUITES, text) or 'null'}",
        f"components: {first(_COMPONENTS, text) or 'null'}",
        f"end-of-life: {q(eol)}",
        # a branch with no end-of-life cannot be shown to be maintained.
        f"maintained: {'true' if eol and eol > today else 'false'}",
        f"existing slices: {n}",
    ]


def branch_manifest(url: str, branch: str) -> str | None:
    """chisel.yaml for a remote branch: a local origin ref when the checkout has
    one (full clone), else the raw file from github when that is where the
    releases live."""
    local = run(["git", "show", f"origin/{branch}:chisel.yaml"])
    if local:
        return local
    if url != DEFAULT_URL:
        return None
    try:
        with urllib.request.urlopen(f"{RAW}/{branch}/chisel.yaml", timeout=8) as r:
            return r.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def live_releases(today: str) -> list[str]:
    """Which ubuntu-XX.XX branches exist, their manifest format, and whether they
    are still maintained. A branch EXISTING does not establish maintenance: EOL
    branches stay in the repo, frozen. Best-effort: an empty map without network."""
    url = os.environ.get("CHISEL_RELEASES_URL", DEFAULT_URL)
    refs = run(["git", "ls-remote", "--heads", url, "ubuntu-*"], timeout=30) or ""
    branches = sorted(line.rsplit("refs/heads/", 1)[-1] for line in refs.splitlines() if "refs/heads/" in line)
    if not branches:
        return ["live releases: {}  # chisel-releases remote unreachable"]

    out = ["live releases:"]
    for b in branches:
        cy = branch_manifest(url, b)
        if not cy:
            continue
        # normalise "v3" / "chisel-v1" / "1" -> "v1".."v3".
        digits = re.search(r"[0-9]+", first(_FORMAT, cy))
        fmt = f"v{digits.group(0)}" if digits else ""
        eol = first(_EOL, cy)
        # live only. ISO dates sort lexically == chronologically.
        if not eol or eol <= today:
            continue
        out.append(f"  {b}: {{format: {q(fmt)}, end-of-life: {q(eol)}}}")
    return out


def main() -> int:
    today = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().date().isoformat()
    lines = [f"working dir: {q(os.getcwd())}", "", *tools(), "", *checkout(today), "", *live_releases(today)]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
