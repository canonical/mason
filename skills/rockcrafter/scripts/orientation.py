#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""orientation: where are we, and what is here -- run FIRST, every time, from
the directory you work in. Deterministic: it reports which tools this machine
has, the git state, the chisel-releases checkout or rock project in the
current directory (each only when it is there), and which Ubuntu releases
Ubuntu, chisel-releases and the installed rockcraft each know.

It lists and does not judge: whether a missing tool, a missing checkout or an
unmaintained release blocks a task is for the skill to say. Nearly every value
is read off the machine, the directory or an upstream source. The few that are
derived or assumed instead are marked DERIVED where they are computed.

It only reads, and everything it starts is bounded, so a dead network costs
the release facts that came over it and nothing else.

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
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import yaml

TOOLS = ("chisel", "rockcraft", "dpkg-deb", "file", "spread", "lxc", "docker", "uv", "python3", "git")  # fmt: skip
SUITES = ("rockcraft-test.yaml", "spread.yaml")
ROCK_KEYS = ("name", "version", "base", "build-base")

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
TIMEOUT = 20  # seconds, per command
FETCH_TIMEOUT = 8  # seconds, per fetch
DEADLINE = 45  # seconds, for all release discovery together

_ABSENT = (FileNotFoundError, IsADirectoryError, NotADirectoryError)


class Failed(Exception):
    """A read that could not be made, as opposed to one that answered no."""


def run(cmd: list[str], timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
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


def here(path: str) -> str | None:
    """The text of a file in the working directory, None when no file by that
    name is here. Failed when it is there and cannot be read."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except _ABSENT:
        return None
    except OSError as e:
        raise Failed(f"{path}: {e}") from e


def after(date: str | None, today: str) -> bool | None:
    """Whether an ISO date is still ahead of today. None without a usable one."""
    try:
        return _dt.date.fromisoformat(date or "") > _dt.date.fromisoformat(today)
    except ValueError:
        return None


# --- the working directory ---------------------------------------------------


def git_state(report: common.Report) -> common.Flow:
    state = common.Flow(repository=None)
    if not shutil.which("git"):
        return state
    try:
        # git exits non-zero outside a repository: that is its answer
        inside = run(["git", "rev-parse", "--is-inside-work-tree"])
        state["repository"] = inside.stdout.strip() == "true"
        if state["repository"]:
            branch = run(["git", "branch", "--show-current"])
            if branch.returncode:
                raise Failed(branch.stderr.strip() or "git branch failed")
            state["branch"] = branch.stdout.strip() or None  # None: detached HEAD
    except Failed as e:
        report.mark_unavailable("git", str(e))
    return state


def context(name: str, path: str, facts, report: common.Report) -> None:
    """Report facts(text) under `name` when `path` is a file here. The key is
    left out when it is not, and None when it is there but cannot be read."""
    try:
        text = here(path)
    except Failed as e:
        report.data[name] = None
        report.mark_unavailable(name, str(e))
        return
    if text is not None:
        report.data[name] = facts(text, report)


def flow_list(value: str | None) -> list[str] | None:
    """A flow list like [a, b] written on the key's own line, else None."""
    m = re.fullmatch(r"\[(.*)\]", value or "")
    return [v.strip() for v in m.group(1).split(",") if v.strip()] if m else None


def checkout(text: str, report: common.Report, today: str) -> dict:
    m = common.manifest(text)
    # the base is a fact of the manifest, not of whatever branch is checked out
    base = common.target_base()
    ref = n = None
    try:
        ref = common.base_ref(base, timeout=TIMEOUT) if base else None
    except subprocess.TimeoutExpired as e:
        report.mark_unavailable("git", f"base ref: {e}")
    try:
        n = len([f for f in os.listdir("slices") if not f.startswith(".")])
    except _ABSENT:
        n = 0
    except OSError as e:
        report.mark_unavailable("chisel-releases", f"slices/: {e}")
    return {
        "target base": base,
        "base ref": ref,
        "ubuntu version": m["version"],
        "manifest format": m["format"],
        "suites": flow_list(m["suites"]),
        "components": flow_list(m["components"]),
        "end-of-life": m["end-of-life"],
        "maintained": after(m["end-of-life"], today),
        "existing slices": n,
    }


def rock(text: str, report: common.Report) -> dict:
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
        facts["test suites"] = [s for s in SUITES if here(s) is not None]
    except Failed as e:
        facts["test suites"] = None
        report.mark_unavailable("rock", str(e))
    return facts


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


def branch_facts(branch: str, manifest: str | None, today: str) -> common.Flow:
    """What a branch's manifest states. Every fact is None when it has none."""
    m = common.manifest(manifest or "")
    digits = re.search(r"[0-9]+", m["format"] or "")  # "chisel-v1" / "1" -> "v1"
    maintained = after(m["end-of-life"], today)
    if maintained is None:
        m["end-of-life"] = None
        if manifest is not None and expired_interim(branch, today):
            maintained = False
    return common.Flow(
        {
            "branch": branch,
            "format": f"v{digits.group(0)}" if digits else None,
            "end-of-life": m["end-of-life"],
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
    refs = (line.partition("\t") for line in listed.stdout.splitlines())
    return {
        ref.removeprefix("refs/heads/"): rev
        for rev, _, ref in refs
        if ref.startswith("refs/heads/")
    }


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
                **({"development": True} if devel else {}),
            )
    return out


def rockcraft_version() -> str | None:
    """The installed rockcraft's own version string, or None without one."""
    if not shutil.which("rockcraft"):
        return None
    asked = run(["rockcraft", "--version"], timeout=10)
    words = asked.stdout.split()
    if asked.returncode:
        raise Failed(f"rockcraft --version failed (exit {asked.returncode})")
    if not words:
        raise Failed("rockcraft --version printed no version")
    return words[-1]


def rockcraft_schema(version: str) -> dict:
    """The schema of rockcraft.yaml that the given rockcraft version publishes."""
    # read at the tag of the installed version, never at main: another
    # version's schema would be a guess about this one.
    url = os.environ.get("ROCKCRAFT_SCHEMA_URL", ROCKCRAFT_SCHEMA)
    try:
        schema = json.loads(fetch(url.format(version=version)))
        schema["properties"]["base"]["enum"]  # the part every reader relies on
    except (ValueError, KeyError, TypeError) as e:
        raise Failed(f"rockcraft {version}: its schema does not read: {e!r}") from e
    return schema


def rockcraft_bases(version: str) -> dict[str, common.Flow]:
    """release -> how the given rockcraft version accepts it."""
    try:
        props = rockcraft_schema(version)["properties"]
        build = props["build-base"]["anyOf"]
        accepted = {
            "base": props["base"]["enum"],
            "build-base": [e for alt in build for e in alt.get("enum", [])],
        }
    except (KeyError, TypeError) as e:
        raise Failed(f"rockcraft {version}: its schema does not read: {e!r}") from e
    out: dict[str, common.Flow] = {}
    for key, names in accepted.items():
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


def releases(today: str, report: common.Report) -> None:
    """One row per Ubuntu release, with what each of the three sources says.
    A source that does not know a release has no entry in its row."""
    url = os.environ.get("CHISEL_RELEASES_URL", DEFAULT_URL)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)

    def answer(job, check: str, label: str = ""):
        """A job's result, or None with the reason recorded."""
        try:
            return job.result(timeout=0)
        except concurrent.futures.TimeoutError:
            reason = "not read before the deadline"
        except Failed as e:
            reason = str(e)
        report.mark_unavailable(check, f"{label}: {reason}" if label else reason)
        return None

    try:
        ubuntu = pool.submit(ubuntu_releases)
        bases = None
        manifests: dict = {}
        try:
            version = rockcraft_version()
            bases = pool.submit(rockcraft_bases, version) if version else None
        except Failed as e:
            report.mark_unavailable("rockcraft bases", str(e))
        try:
            for branch, revision in sorted(remote_branches(url).items()):
                manifests[branch] = pool.submit(branch_manifest, url, revision)
        except Failed as e:
            report.mark_unavailable("release discovery", str(e))
        jobs = [ubuntu, *manifests.values(), *([bases] if bases else [])]
        concurrent.futures.wait(jobs, timeout=DEADLINE)
        sources = {
            "ubuntu": answer(ubuntu, "ubuntu releases") or {},
            # a branch the remote lists is a fact even when its manifest could
            # not be read: its other facts are then unknown
            "chisel-releases": {
                branch.removeprefix("ubuntu-"): branch_facts(
                    branch, answer(job, "release discovery", branch), today
                )
                for branch, job in manifests.items()
            },
            "rockcraft": (answer(bases, "rockcraft bases") if bases else None) or {},
        }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    listed = {v for v, u in sources["ubuntu"].items() if u["supported"]}
    listed |= set(sources["chisel-releases"]) | set(sources["rockcraft"])

    def numeric(version: str) -> list[int]:
        return [int(x) if x.isdigit() else -1 for x in version.split(".")]

    report.data["releases"] = rows = {
        version: {name: known[version] for name, known in sources.items() if version in known}
        for version in sorted(listed, key=numeric)
    }
    report.data["default rock base"] = default_rock_base(rows)


def main() -> int:
    if len(sys.argv) > 1:
        return common.usage("Usage: orientation.py")
    today = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().date().isoformat()
    report = common.Report({})
    report.data["working dir"] = os.getcwd()
    report.data["git"] = git_state(report)
    report.data["tools"] = common.tools(TOOLS)
    context("chisel-releases", "chisel.yaml", lambda t, r: checkout(t, r, today), report)
    context("rock", "rockcraft.yaml", rock, report)
    releases(today, report)
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
