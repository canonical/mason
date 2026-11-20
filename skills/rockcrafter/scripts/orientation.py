#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""orientation: where are we, and what is here -- run FIRST, every time, from
the directory you work in. Deterministic: it reports which tools this machine
has, the git state, the chisel-releases checkout or rock project in the
current directory (each only when it is there), and which Ubuntu releases
Ubuntu, chisel-releases and the installed rockcraft each know. Work from
this, not from guesses.

It lists and does not judge: whether a missing tool, a missing checkout or an
unmaintained release blocks a task is for the skill to say. Nearly every value
is read off the machine, the directory or an upstream source. The few that are
derived or assumed instead are marked DERIVED where they are computed.

The output is the YAML report described in common.py. It only reads, and
everything it starts is bounded, so a dead network costs the release facts
and nothing else.

Usage: orientation.py

Unavailable when a read was refused or failed: a file that is there but
cannot be read, a git query that cannot run, an upstream that cannot be
reached. Absence (no checkout, no rock, a tool not installed) is a fact, not
a failure. The facts that could be established are always reported.
"""

from __future__ import annotations

import concurrent.futures
import datetime as _dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import yaml

TOOLS = (
    "chisel",
    "rockcraft",
    "dpkg-deb",
    "file",
    "spread",
    "lxc",
    "docker",
    "uv",
    "python3",
    "git",
)
# the three upstream sources. each can be pointed elsewhere (a mirror, a test
# fixture) through the environment variable named beside it.
DEFAULT_URL = "https://github.com/canonical/chisel-releases.git"  # CHISEL_RELEASES_URL
RAW = "https://raw.githubusercontent.com/canonical/chisel-releases"
# UBUNTU_META_RELEASE_URL. the release in development is in <url>-development.
META_RELEASE = "https://changelogs.ubuntu.com/meta-release"
# ROCKCRAFT_SCHEMA_URL. rockcraft publishes the schema of rockcraft.yaml in its
# repository, generated from its own models, one per release tag. the enums of
# `base` and `build-base` in it are the bases that version accepts.
ROCKCRAFT_SCHEMA = (
    "https://raw.githubusercontent.com/canonical/rockcraft/{version}/schema/rockcraft.json"
)
SUITES = ("rockcraft-test.yaml", "spread.yaml")
ROCK_KEYS = ("name", "version", "base", "build-base")
GIT_TIMEOUT = 20
FETCH_TIMEOUT = 8
DEADLINE = 45  # seconds for all release discovery together

_FORMAT = re.compile(r"^format:[ \t]*(.*)$", re.MULTILINE)
_SUITES = re.compile(r"suites:[ \t]*(.*)$", re.MULTILINE)
_COMPONENTS = re.compile(r"components:[ \t]*(.*)$", re.MULTILINE)
_EOL = re.compile(r"^[ \t]*end-of-life:[ \t]*(.*)$", re.MULTILINE)
_ABSENT = (FileNotFoundError, IsADirectoryError, NotADirectoryError)


class Failed(Exception):
    """A read that could not be made, as opposed to one that answered no."""


def run(cmd: list[str], timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a read-only command. Failed when it cannot start or does not end."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise Failed(f"{' '.join(cmd[:2])}: {e}") from e


def fetch(url: str) -> str:
    """The text at url. Failed when it cannot be had, a 404 included."""
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:
            return r.read().decode("utf-8", errors="replace")
    except (OSError, ValueError) as e:
        raise Failed(f"{url}: {e}") from e


def first(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def inline_list(value: str) -> list[str] | None:
    """A flow list like [a, b] written on the key's own line, else None."""
    m = re.fullmatch(r"\[(.*)\]", value.strip())
    return [v.strip() for v in m.group(1).split(",") if v.strip()] if m else None


def read(path: str) -> str | None:
    """The text of a file in the working directory, or None when no file by
    that name is here. Any other failure to read it is Failed."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except _ABSENT:
        return None
    except OSError as e:
        raise Failed(f"{path}: {e}") from e


# --- the working directory ---------------------------------------------------


def git_state(report: common.Report) -> common.Flow:
    if not shutil.which("git"):
        return common.Flow(repository=None)
    state = common.Flow(repository=None)
    try:
        inside = run(["git", "rev-parse", "--is-inside-work-tree"])
        # git exits non-zero outside a repository: that is its answer
        state["repository"] = inside.stdout.strip() == "true"
        if state["repository"]:
            branch = run(["git", "branch", "--show-current"])
            if branch.returncode:
                raise Failed(branch.stderr.strip() or "git branch failed")
            state["branch"] = branch.stdout.strip() or None  # None: detached HEAD
    except Failed as e:
        report.mark_unavailable("git", str(e))
    return state


def checkout(today: str, report: common.Report) -> None:
    """Facts about ./chisel.yaml, under `chisel-releases`, when there is one."""
    try:
        text = read("chisel.yaml")
    except Failed as e:
        report.data["chisel-releases"] = None
        report.mark_unavailable("chisel-releases", str(e))
        return
    if text is None:
        return

    # the base is a fact of the manifest, not of whatever branch is checked out
    base = common.target_base()
    ref = None
    try:
        ref = common.base_ref(base, timeout=GIT_TIMEOUT) if base else None
    except subprocess.TimeoutExpired as e:
        report.mark_unavailable("git", f"base ref: {e}")
    eol = first(_EOL, text).strip("\"'")
    try:
        maintained = _dt.date.fromisoformat(eol) > _dt.date.fromisoformat(today)
    except ValueError:
        maintained = None
    try:
        n = len([f for f in os.listdir("slices") if not f.startswith(".")])
    except _ABSENT:
        n = 0
    except OSError as e:
        n = None
        report.mark_unavailable("chisel-releases", f"slices/: {e}")
    report.data["chisel-releases"] = {
        "target base": base,
        "base ref": ref,
        "ubuntu version": common.ubuntu_version(text),
        "manifest format": first(_FORMAT, text) or None,
        "suites": inline_list(first(_SUITES, text)),
        "components": inline_list(first(_COMPONENTS, text)),
        "end-of-life": eol or None,
        "maintained": maintained,
        "existing slices": n,
    }


def rock(report: common.Report) -> None:
    """Facts about ./rockcraft.yaml, under `rock`, when there is one."""
    try:
        text = read("rockcraft.yaml")
    except Failed as e:
        report.data["rock"] = None
        report.mark_unavailable("rock", str(e))
        return
    if text is None:
        return
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        doc = None
    facts: dict = (
        {k: doc[k] for k in ROCK_KEYS if k in doc}
        if isinstance(doc, dict)
        else {"parses": False}
    )
    try:
        facts["test suites"] = [s for s in SUITES if is_file(s)]
    except Failed as e:
        facts["test suites"] = None
        report.mark_unavailable("rock", str(e))
    report.data["rock"] = facts


def is_file(path: str) -> bool:
    """Whether a file by that name is here. Failed when that cannot be told."""
    try:
        return stat.S_ISREG(Path(path).stat().st_mode)
    except _ABSENT:
        return False
    except OSError as e:
        raise Failed(f"{path}: {e}") from e


# --- releases ----------------------------------------------------------------


def expired_interim(branch: str, today: str) -> bool:
    """An interim release past its support window."""
    # DERIVED: not read from anywhere. Ubuntu supports an interim (non-LTS)
    # release for 9 months, and an LTS is the .04 of an even year. a branch of
    # an interim release that records no end-of-life is therefore taken as
    # unmaintained once 9 months have passed since its release month, plus one
    # month in case it shipped late in that month. LTS branches never qualify.
    m = re.fullmatch(r"ubuntu-(\d\d)\.(\d\d)", branch)
    if not m or (m.group(2) == "04" and int(m.group(1)) % 2 == 0):
        return False
    months = (2000 + int(m.group(1))) * 12 + int(m.group(2)) - 1 + 9 + 1
    end = _dt.date(months // 12, months % 12 + 1, 1)
    return _dt.date.fromisoformat(today) >= end


def branch_manifest(url: str, revision: str) -> str:
    """Read the exact revision advertised by the remote, never a stale ref."""
    try:
        local = run(["git", "show", f"{revision}:chisel.yaml"])
        if local.returncode == 0 and local.stdout:
            return local.stdout
    except Failed:
        pass
    if url != DEFAULT_URL:
        raise Failed(f"manifest object {revision} is not available locally for {url}")
    return fetch(f"{RAW}/{revision}/chisel.yaml")


def branch_facts(branch: str, manifest: str, today: str) -> common.Flow:
    # normalise "v3" / "chisel-v1" / "1" -> "v1".."v3".
    digits = re.search(r"[0-9]+", first(_FORMAT, manifest))
    eol = first(_EOL, manifest).strip("\"'")
    try:
        maintained = _dt.date.fromisoformat(eol) > _dt.date.fromisoformat(today)
    except ValueError:
        eol = ""
        maintained = False if expired_interim(branch, today) else None
    return common.Flow(
        {
            "branch": branch,
            "format": f"v{digits.group(0)}" if digits else None,
            "end-of-life": eol or None,
            "maintained": maintained,
        }
    )


def remote_branches(url: str) -> dict[str, str]:
    """ubuntu-* branch -> the revision the remote advertises for it."""
    if not shutil.which("git"):
        raise Failed(f"{url}: git is not installed to list its branches")
    listed = run(["git", "ls-remote", "--heads", url, "ubuntu-*"], timeout=30)
    if listed.returncode:
        raise Failed(f"{url}: {listed.stderr.strip() or f'exit {listed.returncode}'}")
    out = {}
    for line in listed.stdout.splitlines():
        rev, _, ref = line.partition("\t")
        if ref.startswith("refs/heads/"):
            out[ref.removeprefix("refs/heads/")] = rev
    return out


def ubuntu_releases() -> dict[str, common.Flow]:
    """version -> what Ubuntu's meta-release states about it. A release only
    the development list knows is the one in development."""
    out: dict[str, common.Flow] = {}
    stable = os.environ.get("UBUNTU_META_RELEASE_URL", META_RELEASE)
    for url, devel in ((stable, False), (f"{stable}-development", True)):
        for block in fetch(url).split("\n\n"):
            f = dict(ln.split(": ", 1) for ln in block.splitlines() if ": " in ln)
            m = re.match(r"(\d+\.\d+)", f.get("Version", ""))
            if not f.get("Dist") or not m or m.group(1) in out:
                continue
            out[m.group(1)] = common.Flow(
                codename=f["Dist"],
                lts="LTS" in f["Version"],
                supported=f.get("Supported") == "1",
            )
            if devel:
                out[m.group(1)]["development"] = True
    return out


def rockcraft_version() -> str | None:
    """The installed rockcraft's own version string, or None without one."""
    if not shutil.which("rockcraft"):
        return None
    words = run(["rockcraft", "--version"], timeout=10).stdout.split()
    if not words:
        raise Failed("rockcraft --version printed no version")
    return words[-1]


def rockcraft_bases(version: str) -> dict[str, common.Flow]:
    """version -> how the given rockcraft version accepts that release."""
    # the schema is read at the tag of the installed version, never at main:
    # another version's bases would be a guess about this one.
    try:
        url = os.environ.get("ROCKCRAFT_SCHEMA_URL", ROCKCRAFT_SCHEMA)
        schema = json.loads(fetch(url.format(version=version)))
        props = schema["properties"]
        base = props["base"]["enum"]
        build = [e for alt in props["build-base"]["anyOf"] for e in alt.get("enum", [])]
    except (ValueError, KeyError, TypeError) as e:
        raise Failed(f"rockcraft {version}: its schema does not read: {e!r}") from e
    out: dict[str, common.Flow] = {}
    for key, names in (("base", base), ("build-base", build)):
        for name in names:
            m = re.fullmatch(r"ubuntu@(\d+\.\d+)", str(name))
            if m:
                out.setdefault(m.group(1), common.Flow())[key] = True
    return out


def default_rock_base(rows: dict[str, dict]) -> str | None:
    # DERIVED: a choice, not a reading. the default base for a new rock is the
    # newest release that the installed rockcraft accepts as a base and that
    # Ubuntu marks LTS. rockcraft's bases are not in step with Ubuntu's
    # releases (it keeps interim ones past their support, and gains a new
    # release some time after it ships), so neither list alone answers this.
    # None when either list is missing.
    for version in reversed(list(rows)):
        row = rows[version]
        if row.get("rockcraft", {}).get("base") and row.get("ubuntu", {}).get("lts"):
            return f"ubuntu@{version}"
    return None


def release_key(version: str) -> tuple:
    return tuple(int(x) if x.isdigit() else -1 for x in re.split(r"[.-]", version))


def releases(today: str, report: common.Report) -> None:
    """One row per Ubuntu release, with what each of the three sources says.
    A source that does not know a release has no entry in its row."""
    url = os.environ.get("CHISEL_RELEASES_URL", DEFAULT_URL)
    deadline = time.monotonic() + DEADLINE
    ubuntu: dict = {}
    branches: dict = {}
    bases: dict = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    try:
        jobs = {pool.submit(ubuntu_releases): ("ubuntu releases", None)}
        try:
            version = rockcraft_version()
            if version:
                jobs[pool.submit(rockcraft_bases, version)] = ("rockcraft bases", None)
        except Failed as e:
            report.mark_unavailable("rockcraft bases", str(e))
        try:
            for branch, revision in sorted(remote_branches(url).items()):
                job = pool.submit(branch_manifest, url, revision)
                jobs[job] = ("release discovery", branch)
        except Failed as e:
            report.mark_unavailable("release discovery", str(e))

        concurrent.futures.wait(jobs, timeout=max(0.0, deadline - time.monotonic()))
        for job, (check, branch) in jobs.items():
            version = branch.removeprefix("ubuntu-") if branch else None
            if not job.done():
                what = branch or check
                report.mark_unavailable(check, f"{what}: not read before the deadline")
                problem = True
            else:
                problem = job.exception()
                if isinstance(problem, Failed):
                    reason = f"{branch}: {problem}" if branch else str(problem)
                    report.mark_unavailable(check, reason)
                elif problem:
                    raise problem
            if branch:
                # a branch the remote lists is a fact even when its manifest
                # could not be read: its other facts are then unknown
                branches[version] = (
                    common.Flow(
                        {"branch": branch, "format": None, "end-of-life": None,
                         "maintained": None}
                    )
                    if problem
                    else branch_facts(branch, job.result(), today)
                )  # fmt: skip
            elif not problem and check == "ubuntu releases":
                ubuntu = job.result()
            elif not problem:
                bases = job.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    listed = set(branches) | set(bases) | {v for v, u in ubuntu.items() if u["supported"]}
    rows = {}
    for version in sorted(listed, key=release_key):
        row = {}
        if version in ubuntu:
            row["ubuntu"] = ubuntu[version]
        if version in branches:
            row["chisel-releases"] = branches[version]
        if version in bases:
            row["rockcraft"] = bases[version]
        rows[version] = row
    report.data["releases"] = rows
    report.data["default rock base"] = default_rock_base(rows)


def main() -> int:
    if len(sys.argv) > 1:
        return common.usage("Usage: orientation.py")
    today = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().date().isoformat()
    report = common.Report({})
    report.data["working dir"] = os.getcwd()
    report.data["git"] = git_state(report)
    report.data["tools"] = common.tools(TOOLS)
    checkout(today, report)
    rock(report)
    releases(today, report)
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
