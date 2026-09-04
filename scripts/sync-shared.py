#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""sync-shared: copy files from _shared/ into the skills that ask for them.

Installers copy a skill directory verbatim and know nothing about siblings, so
anything a skill needs has to live inside it. _shared/ is the single source of
truth for material used by more than one skill; this script materialises it.

Everything is declared in .shared.yaml at the repo root: a `shared:` map keyed
by skill, then by _shared/-relative source, each entry naming where the copy
goes. The destination is a path, not a directory convention -- a skill decides
where its copies live and what they are called:

    shared:
      chisel-slicer:
        chisel-cli.md:
          path: shared/chisel-cli.md      # under shared/
        slice-conventions.md:
          path: reference/style.md        # anywhere else, renamed
        spread-tests.md:                  # no entry body -- same relative path

Nothing about this lives in the skill directories: a copy is a byte-for-byte
duplicate of its source carrying its mode, and no listing file sits beside it.
A skill dir holds only what ships.

Being an exact duplicate is also how a copy is recognised, so no record of past
writes is kept: a file inside a skill whose bytes match some _shared/ file but
which nothing declares is a leftover, and is removed. Drop an entry or point it
somewhere else and the file at the old path goes away rather than lingering.

The one leftover this cannot see is one whose source was edited in the same
change that moved it -- its content no longer matches anything in _shared/.
Running sync after a retarget alone always catches it.

Usage:
  sync-shared.py            write the copies (make sync-shared)
  sync-shared.py --check    write nothing; list what differs, exit 1 if anything does
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "_shared"
SKILLS = ROOT / "skills"
MANIFEST = ROOT / ".shared.yaml"

ENTRY_KEYS = {"path"}


def fail(msg: str) -> None:
    sys.exit(f"error: {MANIFEST.name}: {msg}")


def read_manifest() -> dict[Path, Path]:
    """Parse .shared.yaml into {destination: source}."""
    if not MANIFEST.is_file():
        sys.exit(f"error: {MANIFEST.name} not found at the repo root")
    doc = yaml.safe_load(MANIFEST.read_text()) or {}
    if not isinstance(doc, dict):
        fail("must be a mapping with a 'shared:' key")
    extra = set(doc) - {"shared"}
    if extra:
        fail(f"unknown top-level key(s) {sorted(extra)}")

    by_skill = doc.get("shared") or {}
    if not isinstance(by_skill, dict):
        fail("'shared' must be a map keyed by skill name")

    want: dict[Path, Path] = {}
    for name, entries in by_skill.items():
        skill = SKILLS / str(name)
        if not (skill / "SKILL.md").is_file():
            fail(f"'{name}' is not a skill (no skills/{name}/SKILL.md)")
        if entries is None:
            continue
        if not isinstance(entries, dict):
            fail(f"{name}: must be a map keyed by _shared/ source path")
        for src, entry in entries.items():
            if not isinstance(src, str):
                fail(f"{name}: source {src!r} is not a string")
            if not (SHARED / src).is_file():
                fail(f"{name} lists {src}, but _shared/{src} does not exist")
            if entry is None:
                entry = {}
            if not isinstance(entry, dict):
                fail(f"{name}: entry for {src} must be a map (e.g. 'path: ...')")
            bad = set(entry) - ENTRY_KEYS
            if bad:
                fail(f"{name}: {src} has unknown key(s) {sorted(bad)}")
            dest = entry.get("path") or src
            if not isinstance(dest, str):
                fail(f"{name}: path for {src} is not a string")
            if Path(dest).is_absolute() or ".." in Path(dest).parts:
                fail(f"{name}: path {dest!r} must stay inside the skill")
            target = skill / dest
            if target in want:
                fail(f"two sources both target {target.relative_to(ROOT)}")
            want[target] = SHARED / src

    return want


def expected() -> dict[Path, tuple[bytes, bool]]:
    """dest path -> (content, executable) for every file every skill asks for."""
    return {
        dest: (src.read_bytes(), bool(src.stat().st_mode & stat.S_IXUSR))
        for dest, src in read_manifest().items()
    }


def _stat(p: Path) -> tuple[bytes, bool]:
    return p.read_bytes(), bool(p.stat().st_mode & stat.S_IXUSR)


def actual(want: dict[Path, tuple[bytes, bool]]) -> dict[Path, tuple[bytes, bool]]:
    """Copies on disk: the declared ones that exist, plus any undeclared file in
    a skill that duplicates a _shared/ source -- those are leftovers to sweep."""
    have = {p: _stat(p) for p in want if p.is_file()}
    sources = {f.read_bytes() for f in SHARED.rglob("*") if f.is_file()}
    for skill in SKILLS.iterdir():
        if not skill.is_dir():
            continue
        for p in skill.rglob("*"):
            if p.is_file() and p not in want and p.read_bytes() in sources:
                have[p] = _stat(p)
    return have


def diff(want: dict, have: dict) -> list[tuple[str, Path]]:
    out = []
    for p, (content, executable) in want.items():
        if p not in have:
            out.append(("missing", p))
        elif have[p][0] != content:
            out.append(("differs", p))
        elif have[p][1] != executable:
            out.append(("mode", p))
    out.extend(("stale", p) for p in have if p not in want)
    return sorted(out, key=lambda t: t[1])


def prune_empty_dirs() -> None:
    for skill in SKILLS.iterdir():
        if not skill.is_dir():
            continue
        for p in sorted(skill.rglob("*"), key=lambda q: -len(q.parts)):
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()


def apply(want: dict, have: dict) -> None:
    for kind, p in diff(want, have):
        if kind == "stale":
            p.unlink()
            print(f"removed  {p.relative_to(ROOT)}")
            continue
        content, executable = want[p]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        mode = p.stat().st_mode
        mode = mode | 0o111 if executable else mode & ~0o111
        p.chmod(mode)
        print(f"wrote    {p.relative_to(ROOT)}")
    prune_empty_dirs()


def main(argv: list[str]) -> int:
    check = "--check" in argv
    want = expected()
    have = actual(want)
    if not check:
        apply(want, have)
        return 0
    findings = diff(want, have)
    for kind, p in findings:
        print(f"{kind:8} {p.relative_to(ROOT)}")
    if findings:
        print(
            "shared copies out of date: run `make sync-shared` and commit",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
