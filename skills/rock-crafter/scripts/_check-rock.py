#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""check-rock: deterministic static linter for a rockcraft.yaml.

Checks what rockcraft itself would reject, plus the rock conventions -- the
rules that do NOT need judgement or a build -- so a pack is never spent on a
typo. Slices are checked to exist on the release (or on a local
chisel-releases checkout a part cuts them from), not that they carry what the
workload needs; slices cut from a remote source are not checked. It does not
replace a pack.

Usage: check-rock.py [<rockcraft.yaml>]   (default: ./rockcraft.yaml)

Unavailable when the release list or chisel-releases cannot be reached for
the slice check; every other finding is still reported.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

try:
    import _common as common
    import _rocklib as rl
except ImportError:
    import common
    import rocklib as rl

# top-level keys rockcraft accepts (rockcraft.yaml reference); anything else is
# rejected with "extra inputs are not permitted". changes with rockcraft
# releases, not Ubuntu releases.
KNOWN = {
    "name", "title", "version", "summary", "description", "license", "base",
    "build-base", "run-user", "platforms", "services", "checks",
    "entrypoint-service", "entrypoint-command", "environment", "parts",
    "package-repositories", "extensions", "adopt-info", "contact", "issues",
    "source-code", "build-slices",
}  # fmt: skip

# keys rockcraft requires (`parts` is generated when an extension is used,
# `version` may be set by the part `adopt-info` names).
REQUIRED = (
    "name",
    "version",
    "summary",
    "description",
    "base",
    "platforms",
    "parts",
)

# Debian arch names -- what a platform is named after unless it sets
# `build-for`; never x86_64 / aarch64.
ARCHES = {"amd64", "arm64", "armhf", "i386", "ppc64el", "riscv64", "s390x"}

# <package>_<slice>: a stage-packages entry with an underscore is a slice
# (Debian package names can't contain one).
SLICE = re.compile(r"^[a-z0-9][a-z0-9.+-]*_[a-z0-9][a-z0-9-]*$")

# ubuntu@XX.YY -- the version itself is validated live against the release list.
BASE = re.compile(r"^ubuntu@(\d\d\.\d\d)$")

CODES = {
    "not-a-mapping": "rockcraft.yaml is not a YAML mapping",
    "missing-key": "a key rockcraft requires is absent",
    "unknown-key": "a top-level key rockcraft rejects",
    "bad-type": "a key whose value is not the YAML type rockcraft expects",
    "bad-base": "base is not `bare` or `ubuntu@XX.YY`, or build-base not `ubuntu@XX.YY` or `devel`",
    "unknown-release": "the base, or a `chisel cut --release`, names no known Ubuntu release",
    "bare-needs-build-base": "base: bare without build-base",
    "version-type": "version is not a string (quote it)",
    "version-granularity": "archive-based rocks version XX.YY; a patch level needs a pinned source-tag",
    "root-user": "no `run-user: _daemon_`: the rock runs as root -- set it or justify it",
    "bad-platform": "a platform without `build-for` whose name is not a Debian architecture",
    "service-command": "a Pebble service command must start with an absolute path",
    "service-override": "a Pebble service without `override: replace`",
    "mixed-stage": "a part mixes slices and whole debs in stage-packages",
    "debs-on-bare": "whole debs on base: bare -- use slices, or an ubuntu@ base for an unchiselled rock",
    "ppa-on-bare": "package-repositories feed whole debs, not slices -- use an ubuntu@ base",
    "unknown-slice": "a slice that does not exist on the release",
}


def cuts(script: str) -> list[tuple[str | None, list[str]]]:
    """(its --release, its slice args) of every `chisel cut` in a scriptlet."""
    lines = script.replace("\\\n", " ").splitlines()
    live = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
    out = []
    for m in re.finditer(r"chisel\s+cut\b([^\n;&|]*)", live):
        rel = re.search(r"--release[=\s]\s*(\S+)", m.group(1))
        slices = [t for t in m.group(1).split() if SLICE.match(t)]
        out.append((rel.group(1).strip("\"'") if rel else None, slices))
    return out


def cut_slices(script: str) -> list[str]:
    """slice args of every `chisel cut` in a scriptlet."""
    return [s for _, slices in cuts(script) for s in slices]


def cut_from(rel: str | None, part: dict, release: str) -> str | None:
    """where a `chisel cut --release <rel>` reads its slices: an Ubuntu release, a
    local chisel-releases checkout, or None when that is a tree this cannot read
    (a part's remote source). a relative <rel>, or one behind a $CRAFT_* variable,
    is inside the part's source."""
    if rel is None:
        return release
    if re.fullmatch(r"ubuntu-\d\d\.\d\d", rel):
        return rel
    src = part.get("source")
    inside = re.sub(r"^\$\{?\w+\}?/?", "", rel) or "."
    tree = Path(rel) if rel.startswith("/") else Path(str(src), inside) if src else None
    if tree and (tree / "chisel.yaml").is_file():
        return str(tree)
    return None if src and not Path(str(src)).is_dir() else release


def mappings(value: object, key: str, f: str, report: common.Report) -> dict:
    """the mapping entries of a mapping of mappings; anything else is reported."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        report.add("block", "bad-type", f, key=key)
        return {}
    for name in [n for n, v in value.items() if not isinstance(v, dict)]:
        report.add("block", "bad-type", f, key=f"{key}.{name}")
    return {n: v for n, v in value.items() if isinstance(v, dict)}


def check(doc: object, f: str, report: common.Report) -> None:
    add = report.add
    if not isinstance(doc, dict):
        add("block", "not-a-mapping", f)
        return
    generated = {"parts": doc.get("extensions"), "version": doc.get("adopt-info")}
    for k in REQUIRED:
        absent = doc.get(k) is None or (k == "name" and doc[k] == "")
        if absent and not generated.get(k):
            add("block", "missing-key", f, key=k)
    for k in doc:
        if k not in KNOWN:
            add("block", "unknown-key", f, key=k)

    base, bb = doc.get("base"), doc.get("build-base")
    if base is not None and base != "bare" and not BASE.match(str(base)):
        add("block", "bad-base", f, key="base", value=str(base))
    if base == "bare" and not bb:
        add("block", "bare-needs-build-base", f)
    if bb is not None and bb != "devel" and not BASE.match(str(bb)):
        add("block", "bad-base", f, key="build-base", value=str(bb))
    m = BASE.match(str(bb if base == "bare" else base))
    release = None
    if m:
        try:
            release = rl.resolve_release(m.group(1)).branch
        except ValueError:
            add("block", "unknown-release", f, value=f"ubuntu@{m.group(1)}")
        except rl.Unavailable as e:
            report.mark_unavailable("release", str(e))

    v = doc.get("version")
    if v is not None and not isinstance(v, str):
        add("block", "version-type", f, value=repr(v))
    parts = mappings(doc.get("parts"), "parts", f, report)
    pinned = any("source-tag" in p for p in parts.values())
    if isinstance(v, str) and not pinned and not re.fullmatch(r"\d+\.\d+", v):
        add("warn", "version-granularity", f, value=v)

    if doc.get("run-user") != "_daemon_":
        add("warn", "root-user", f)

    plats = doc.get("platforms")
    if isinstance(plats, dict):
        for a, spec in plats.items():
            named = isinstance(spec, dict) and spec.get("build-for")
            if a not in ARCHES and not named:
                add("block", "bad-platform", f, value=str(a))
    elif plats is not None:
        add("block", "bad-type", f, key="platforms")

    for name, svc in mappings(doc.get("services"), "services", f, report).items():
        if not str(svc.get("command", "")).startswith("/"):
            add("block", "service-command", f, service=name)
        if svc.get("override") != "replace":
            add("warn", "service-override", f, service=name)

    # where the slices are read from -> the slices: stage-packages come off the
    # release, a `chisel cut` off whatever its --release names.
    used: dict[str, set[str]] = {}
    debs = []
    for pname, p in parts.items():
        sp = p.get("stage-packages")
        sp = [] if sp is None else sp
        if not isinstance(sp, list):
            add("block", "bad-type", f, key=f"parts.{pname}.stage-packages")
            continue
        sp = [str(x) for x in sp]
        sl = [x for x in sp if SLICE.match(x)]
        if sl and len(sl) != len(sp):
            add("block", "mixed-stage", f, part=pname)
        debs += [x for x in sp if not SLICE.match(x)]
        if release:
            used.setdefault(release, set()).update(sl)
            for k, val in p.items():
                if str(k).startswith("override-") and isinstance(val, str):
                    for rel, slices in cuts(val):
                        tree = cut_from(rel, p, release)
                        if tree:
                            used.setdefault(tree, set()).update(slices)
    if doc.get("package-repositories") and base == "bare":
        add("warn", "ppa-on-bare", f)
    if base == "bare" and debs:
        add("warn", "debs-on-bare", f, value=" ".join(debs))

    for rel, slices in used.items():
        for pkg in sorted({s.split("_", 1)[0] for s in slices}):
            try:
                have = set(rl.slices_of(rel, pkg) or [])
            except rl.Unavailable as e:
                report.mark_unavailable("slices", str(e))
                return
            except ValueError:  # a `chisel cut --release` naming no Ubuntu release
                add("block", "unknown-release", f, value=rel)
                break
            for s in sorted({u for u in slices if u.startswith(pkg + "_")} - have):
                add("block", "unknown-slice", f, slice=s, release=rel,
                    available=" ".join(sorted(have)) or None)  # fmt: skip


def main() -> int:
    if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1].startswith("-")):
        return common.usage(__doc__.strip())
    path = Path(sys.argv[1] if len(sys.argv) == 2 else "rockcraft.yaml")
    report = common.Report(CODES)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        report.mark_unavailable("read", f"{path}: {e.strerror}")
        return report.emit()
    except yaml.YAMLError as e:
        report.add("block", "not-a-mapping", path, value=str(e).splitlines()[0])
        return report.emit()
    check(doc, str(path), report)
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
