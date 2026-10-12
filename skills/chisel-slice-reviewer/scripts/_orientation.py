#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""orientation: deterministic orientation for the slice-authoring agent -- run
FIRST, every time. Reports where you are, which tools this machine actually
has, the target release + manifest format parsed from ./chisel.yaml, and the
live release landscape (discovered, never hardcoded). Work from this, not from
guesses.

The output is the YAML report described in common.py, so it reads as prose and
parses as data. Every value is a fact read off the machine or the checkout.
Discovery treats an interim release as expired once its 9 months of support
have passed, even when its branch never recorded an end-of-life.

Usage: orientation.py

Unavailable when release discovery is incomplete or there is no checkout to
read; the facts that could be established are still reported.
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

try:
    import _common as common
except ImportError:
    import common

TOOLS = ("chisel", "dpkg-deb", "file", "spread", "uv", "python3", "git")
DEFAULT_URL = "https://github.com/canonical/chisel-releases.git"
RAW = "https://raw.githubusercontent.com/canonical/chisel-releases"

_VERSION = re.compile(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?")
_FORMAT = re.compile(r"^format:[ \t]*(.*)$", re.MULTILINE)
_UBUNTU_VERSION = re.compile(r"^[ \t]+version:[ \t]*(.*)$", re.MULTILINE)
_SUITES = re.compile(r"suites:[ \t]*(.*)$", re.MULTILINE)
_COMPONENTS = re.compile(r"components:[ \t]*(.*)$", re.MULTILINE)
_EOL = re.compile(r"^[ \t]*end-of-life:[ \t]*(.*)$", re.MULTILINE)


def run(cmd: list[str], timeout: int = 20, require_ok: bool = True) -> str | None:
    """stdout of a command, or None if it is missing, hangs, or (unless
    require_ok is off) exits non-zero."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 or not require_ok else None


def first(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def tools() -> dict[str, common.Flow]:
    # --version only. a bare "<tool> version" fallback would be a real
    # invocation -- spread would read spread.yaml and treat it as a job filter --
    # and orientation must stay read-only.
    out = {}
    for t in TOOLS:
        if not shutil.which(t):
            out[t] = common.Flow(present=False, version=None)
            continue
        text = run([t, "--version"], timeout=10, require_ok=False) or ""
        m = _VERSION.search(text)
        # present but unversioned is a fact of its own: chisel prints "unknown"
        # on an unstamped build, spread has no version flag at all. null is
        # reserved for a tool that is not here to have a version.
        out[t] = common.Flow(present=True, version=m.group(0) if m else "unknown")
    return out


def inline_list(value: str) -> list[str] | None:
    """A flow list like [a, b] written on the key's own line, else None."""
    m = re.fullmatch(r"\[(.*)\]", value.strip())
    return [v.strip() for v in m.group(1).split(",") if v.strip()] if m else None


def checkout(today: str, report: common.Report) -> None:
    """Facts about ./chisel.yaml, or why there are none."""
    try:
        text = Path("chisel.yaml").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        report.mark_unavailable(
            "checkout",
            "no ./chisel.yaml here; cd into a chisel-releases checkout first",
        )
        return
    except OSError as e:
        report.mark_unavailable("checkout", str(e))
        return

    branch = (run(["git", "branch", "--show-current"]) or "").strip()
    # the base a review or cut compares against is a fact of the manifest, not
    # of what is checked out, which may be a feature branch or detached. A base
    # that is not fetched is reported here and becomes unavailable in the
    # helper that needs it.
    base = common.target_base()
    ref = common.base_ref(base) if base else None
    eol = first(_EOL, text).strip("\"'")
    try:
        maintained = _dt.date.fromisoformat(eol) > _dt.date.fromisoformat(today)
    except ValueError:
        maintained = None
    try:
        n = len([f for f in os.listdir("slices") if not f.startswith(".")])
    except OSError:
        n = 0
    report.data.update(
        {
            "branch": branch or None,
            "target base": base,
            "base ref": ref,
            "ubuntu version": first(_UBUNTU_VERSION, text).replace("'", "") or None,
            "manifest format": first(_FORMAT, text) or None,
            "suites": inline_list(first(_SUITES, text)),
            "components": inline_list(first(_COMPONENTS, text)),
            "end-of-life": eol or None,
            "maintained": maintained,
            "existing slices": n,
        }
    )


def branch_manifest(url: str, revision: str) -> str:
    """Read the exact revision advertised by the remote, never a stale ref."""
    local = run(["git", "show", f"{revision}:chisel.yaml"])
    if local:
        return local
    if url != DEFAULT_URL:
        raise OSError(f"manifest object {revision} is not available locally for {url}")
    with urllib.request.urlopen(f"{RAW}/{revision}/chisel.yaml", timeout=8) as r:
        return r.read().decode("utf-8", errors="replace")


def expired_interim(branch: str, today: str) -> bool:
    """An interim release past its 9 months of support, allowing a month for it
    to ship late in its release month. LTS releases (even-year .04) never qualify."""
    m = re.fullmatch(r"ubuntu-(\d\d)\.(\d\d)", branch)
    if not m or (m.group(2) == "04" and int(m.group(1)) % 2 == 0):
        return False
    months = (2000 + int(m.group(1))) * 12 + int(m.group(2)) - 1 + 9 + 1
    end = _dt.date(months // 12, months % 12 + 1, 1)
    return _dt.date.fromisoformat(today) >= end


def live_releases(today: str, report: common.Report) -> None:
    """Which ubuntu-XX.XX branches exist, their manifest format, and whether they
    are still maintained. A branch EXISTING does not establish maintenance: EOL
    branches stay in the repo, frozen. Report incomplete discovery explicitly."""
    url = os.environ.get("CHISEL_RELEASES_URL", DEFAULT_URL)
    problems = []
    refs = ""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", url, "ubuntu-*"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            problems.append(
                f"{url}: {result.stderr.strip() or f'exit {result.returncode}'}"
            )
        else:
            refs = result.stdout
    except (OSError, subprocess.SubprocessError) as e:
        problems.append(f"{url}: {e}")

    live = {}
    heads = (line.split() for line in refs.splitlines())
    for b, revision in sorted(
        (ref.removeprefix("refs/heads/"), rev) for rev, ref in heads
    ):
        try:
            cy = branch_manifest(url, revision)
        except OSError as e:
            problems.append(f"{b}: {e}")
            continue
        # normalise "v3" / "chisel-v1" / "1" -> "v1".."v3".
        digits = re.search(r"[0-9]+", first(_FORMAT, cy))
        fmt = f"v{digits.group(0)}" if digits else None
        eol = first(_EOL, cy).strip("\"'")
        try:
            maintained = _dt.date.fromisoformat(eol) > _dt.date.fromisoformat(today)
        except ValueError:
            if not expired_interim(b, today):
                problems.append(f"{b}: maintenance end-of-life missing or invalid")
            continue
        if not maintained:
            continue
        if not fmt:
            problems.append(f"{b}: manifest format missing or invalid")
        live[b] = common.Flow(format=fmt, **{"end-of-life": eol})
    report.data["live releases"] = live
    for problem in problems:
        report.mark_unavailable("release discovery", problem)


def main() -> int:
    today = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().date().isoformat()
    report = common.Report({})
    report.data["working dir"] = os.getcwd()
    report.data["tools"] = tools()
    checkout(today, report)
    live_releases(today, report)
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
