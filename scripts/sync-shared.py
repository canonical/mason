#!/usr/bin/env python3
"""sync-shared: copy files from _shared/ into the skills that list them.

Installers copy a skill directory verbatim and know nothing about siblings, so
anything a skill needs has to live inside it. _shared/ is the single source of
truth for material used by more than one skill; this script materialises it.

Each skill opts in with a shared.list next to its SKILL.md -- one _shared/-relative
path per line (blank lines and # comments ignored). Copies land in <skill>/shared/
with the source's mode, prefixed by a "generated" banner where the file type has
a comment syntax. Copies not listed any more are removed.

Usage:
  sync-shared.py            write the copies (make sync-shared)
  sync-shared.py --check    write nothing; list what differs, exit 1 if anything does
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "_shared"
SKILLS = ROOT / "skills"
LIST = "shared.list"
DEST = "shared"

HASH_COMMENT = {".sh", ".bash", ".py", ".yaml", ".yml", ".toml", ".cfg", ".ini"}


def banner(rel: str, src: bytes, suffix: str) -> bytes:
    note = f"generated from _shared/{rel} by scripts/sync-shared.py -- edit the source, then make sync-shared"
    if suffix == ".md":
        return f"<!-- {note} -->\n\n".encode() + src
    if suffix in HASH_COMMENT or src.startswith(b"#!"):
        line = f"# {note}\n".encode()
        if src.startswith(b"#!"):
            head, _, tail = src.partition(b"\n")
            return head + b"\n" + line + tail
        return line + src
    return src


def read_list(path: Path) -> list[str]:
    out = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def expected() -> dict[Path, tuple[bytes, bool]]:
    """dest path -> (content, executable) for every listed file of every skill."""
    want: dict[Path, tuple[bytes, bool]] = {}
    for skill in sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").is_file()):
        lst = skill / LIST
        if not lst.is_file():
            continue
        for rel in read_list(lst):
            src = SHARED / rel
            if not src.is_file():
                sys.exit(
                    f"error: {lst.relative_to(ROOT)} lists {rel}, but _shared/{rel} does not exist"
                )
            content = banner(rel, src.read_bytes(), src.suffix)
            executable = bool(src.stat().st_mode & stat.S_IXUSR)
            want[skill / DEST / rel] = (content, executable)
    return want


def actual() -> dict[Path, tuple[bytes, bool]]:
    have: dict[Path, tuple[bytes, bool]] = {}
    for skill in SKILLS.iterdir():
        dest = skill / DEST
        if not dest.is_dir():
            continue
        for p in dest.rglob("*"):
            if p.is_file():
                have[p] = (p.read_bytes(), bool(p.stat().st_mode & stat.S_IXUSR))
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
    for skill in SKILLS.iterdir():
        dest = skill / DEST
        if dest.is_dir() and not any(dest.rglob("*")):
            dest.rmdir()


def main(argv: list[str]) -> int:
    check = "--check" in argv
    want, have = expected(), actual()
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
