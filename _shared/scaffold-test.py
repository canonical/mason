#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""scaffold-test: emit a spread task.yaml skeleton for a slice's binaries.

This reads an SDF and prints a starting task.yaml with a fresh rootfs for each
non-copyright slice. Explicit paths in recognised binary directories get a
chroot placeholder; other slices and globbed binaries get author markers.
Replace these with functional checks following kb/_spread-tests.md. The
scaffold does not establish coverage or prove that any command works.

Usage:
  scaffold-test.py slices/<pkg>.yaml > tests/spread/integration/<pkg>/task.yaml

Prints to stdout. It does not overwrite anything. Binaries hidden behind globs
(e.g. /usr/libexec/foo/*) can't be enumerated statically, so they're left as a
marker comment to fill in. Stdlib + pyyaml.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

BIN_DIRS = ("/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/", "/usr/libexec/")


def slice_execs(doc: Any) -> dict[str, tuple[list[str], list[str]]]:
    """slice name -> (explicit binary paths, glob paths), ordered as in the SDF."""
    out: dict[str, tuple[list[str], list[str]]] = {}
    slices = doc.get("slices") if isinstance(doc, dict) else None
    if not isinstance(slices, dict):
        return out
    for sname, body in slices.items():
        if sname == "copyright":
            continue
        contents = body.get("contents") if isinstance(body, dict) else None
        if not isinstance(contents, dict):
            out[sname] = ([], [])
            continue
        bins, globs = [], []
        for path in contents:
            if not isinstance(path, str) or not any(
                path.startswith(d) for d in BIN_DIRS
            ):
                continue
            if path.endswith("/"):
                continue
            if "*" in path or "?" in path:
                globs.append(path)
            else:
                bins.append(path)
        out[sname] = (bins, globs)
    return out


def scaffold(doc: Any, pkg: str) -> str:
    execs = slice_execs(doc)
    lines = [f"summary: Integration tests for {pkg}", ""]
    lines += [
        "# Replace author placeholders using kb/_spread-tests.md before running spread.",
        "",
    ]
    if not execs:
        execs = {"<slice>": ([], [])}

    lines.append("execute: |")
    first = True
    for sname, (bins, globs) in execs.items():
        if not first:
            lines.append("")
        first = False
        lines.append(
            f"  # {pkg}_{sname}: fresh rootfs so a missing dep can't hide behind another test."
        )
        lines.append(f'  rootfs="$(install-slices {pkg}_{sname})"')
        for b in bins:
            lines.append(
                f'  chroot "$rootfs" {b} --version  # TODO(author): real functional check'
            )
        for g in globs:
            lines.append(f"  # TODO(author): exercise the binaries matching {g}")
        if not bins and not globs:
            lines.append(
                "  # TODO(author): add assertions for this slice using the shared testing policy"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not args:
        print("usage: scaffold-test.py slices/<pkg>.yaml", file=sys.stderr)
        return 2
    sdf = Path(args[0])
    try:
        doc = yaml.safe_load(sdf.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        print(f"error: cannot read {sdf}: {e}", file=sys.stderr)
        return 2
    pkg = (
        doc.get("package")
        if isinstance(doc, dict) and isinstance(doc.get("package"), str)
        else sdf.stem
    )
    print(scaffold(doc, pkg), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
