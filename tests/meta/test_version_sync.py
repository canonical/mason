"""Every place that records a version must agree with the root VERSION file.

VERSION is the source of truth. Everything else -- the plugin manifests -- is a
copy, and a copy that drifts ships the wrong number to a registry. Run:

    uv run --with pytest pytest tests/meta/
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# every file that carries the version, and how to pull it out.
MANIFESTS = (".claude-plugin/plugin.json", ".tessl-plugin/plugin.json")


def version() -> str:
    """The root VERSION file: `#` comment lines, then the bare number."""
    for raw in (ROOT / "VERSION").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            return line
    raise AssertionError("VERSION holds no version line")


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", version()), version()


def test_manifests_match_version() -> None:
    want = version()
    for rel in MANIFESTS:
        got = json.loads((ROOT / rel).read_text(encoding="utf-8")).get("version")
        assert got == want, f"{rel} says {got!r}, VERSION says {want!r}"


def test_every_version_declaration_is_registered() -> None:
    """COVER: a single source of truth only holds if new copies cannot appear
    unnoticed. Any tracked file declaring its own version (a `"version": "x.y.z"`
    key or a `version = x.y.z` assignment) must be one of MANIFESTS and must
    match -- so adding a third manifest fails here until it is registered.

    Deliberately narrower than the line-level rule `gg release` uses to find
    sync candidates: that one also matches prose, and the reference docs
    legitimately name chisel's own versions.
    """
    import subprocess

    decl = re.compile(r'(?:^|[\s,{])"?version"?\s*[:=]\s*"?(\d+\.\d+\.\d+)')
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    want = version()
    problems: list[str] = []
    for rel in tracked:
        p = ROOT / rel
        if rel == "VERSION" or rel.startswith("tests/") or not p.is_file():
            continue
        if p.stat().st_size > 1 << 20:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            m = decl.search(line)
            if not m:
                continue
            if rel not in MANIFESTS:
                problems.append(
                    f"{rel}:{n}: declares a version but is not in MANIFESTS"
                )
            elif m.group(1) != want:
                problems.append(f"{rel}:{n}: says {m.group(1)}, VERSION says {want}")
    assert not problems, "version drift:\n" + "\n".join(problems)
