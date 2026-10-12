"""Shipped helper scripts are python, and the docs run them one way.

An installed skill does not keep exec bits, so a helper runs only when invoked
through an interpreter; `uv run` also reads the script's inline metadata and
pulls in its dependencies. Run:

    uv run --with pyyaml --with pytest pytest tests/meta/
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
UV_SHEBANG = "#!/usr/bin/env -S uv run --script"


def manifest() -> dict:
    return yaml.safe_load((ROOT / ".shared.yaml").read_text(encoding="utf-8"))


def shipped() -> list[Path]:
    """Every helper a skill ships: synced copies' sources and skill-owned scripts."""
    sources = {
        ROOT / "_shared" / src
        for entries in manifest()["shared"].values()
        for src, entry in entries.items()
        if entry["path"].startswith("scripts/")
    }
    owned = {
        p
        for p in ROOT.glob("skills/*/scripts/*")
        if p.is_file() and not p.name.startswith("_")
    }
    return sorted(sources | owned)


def docs() -> list[Path]:
    return sorted([*ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("_shared/*.md")])


def test_helpers_are_python() -> None:
    bad = [str(p.relative_to(ROOT)) for p in shipped() if p.suffix != ".py"]
    assert not bad, bad


def test_helpers_declare_their_interpreter() -> None:
    bad = []
    for p in shipped():
        text = p.read_text(encoding="utf-8")
        if 'if __name__ == "__main__":' not in text:
            continue
        if not text.startswith(UV_SHEBANG + "\n# /// script\n"):
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad


def invocation() -> re.Pattern[str]:
    """A mention of a helper by its path inside a skill, with or without .py."""
    names = {
        Path(entry["path"]).name
        for entries in manifest()["shared"].values()
        for entry in entries.values()
        if entry["path"].startswith("scripts/")
    }
    names |= {p.name for p in shipped() if p.parent.name == "scripts"}
    stems = sorted({n.removesuffix(".py") for n in names}, key=len, reverse=True)
    alternatives = "|".join(map(re.escape, stems))
    return re.compile(rf"scripts/(?:{alternatives})(?:\.py)?(?![\w.-])")


def test_docs_run_helpers_through_uv() -> None:
    pattern = invocation()
    bad = []
    for doc in docs():
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for m in pattern.finditer(line):
                if not m.group(0).endswith(".py"):
                    bad.append(
                        f"{doc.relative_to(ROOT)}:{n}: {m.group(0)} is not python"
                    )
                elif "uv run " not in line[: m.start()]:
                    bad.append(
                        f"{doc.relative_to(ROOT)}:{n}: {m.group(0)} not run with uv run"
                    )
    assert not bad, "\n".join(bad)
