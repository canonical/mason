#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""check-rock: deterministic static linter for a rockcraft.yaml.

Checks what rockcraft itself would reject, plus the rock conventions -- the
rules that do NOT need judgment or a build -- so a pack is never spent on a
typo. Which top-level keys, required keys and bases rockcraft accepts is read
from the schema the installed rockcraft publishes for its version; no list of
them is kept here. Slices are checked to exist on the release (or on a local
chisel-releases checkout a part cuts them from), not that they carry what the
workload needs; slices cut from a remote source are not checked. It does not
replace a pack.

Usage: check-rock.py [<rockcraft.yaml>]   (default: ./rockcraft.yaml)

Unavailable when rockcraft is not installed or its schema cannot be read (the
key and base checks then do not run), when chisel-releases cannot be reached
for the slice check, or when slices depend on a base that names no release
(`build-base: devel`); every other finding is still reported.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import orientation
import rocklib as rl
import yaml

# Debian arch names -- what a platform is named after unless it sets
# `build-for`; never x86_64 / aarch64.
ARCHES = {"amd64", "arm64", "armhf", "i386", "ppc64el", "riscv64", "s390x"}

# <package>_<slice>: a stage-packages entry with an underscore is a slice
# (Debian package names can't contain one).
SLICE = re.compile(r"^[a-z0-9][a-z0-9.+-]*_[a-z0-9][a-z0-9-]*$")

# ubuntu@XX.YY -- read off an accepted base to find its chisel-releases branch.
BASE = re.compile(r"^ubuntu@(\d\d\.\d\d)$")
BRANCH = re.compile(r"ubuntu-\d\d\.\d\d")

CODES = {
    "not-a-mapping": "rockcraft.yaml is not a YAML mapping",
    "missing-key": "a key rockcraft requires is absent",
    "unknown-key": "a top-level key rockcraft rejects",
    "bad-type": "a key whose value is not the YAML type rockcraft expects",
    "bad-base": "a base or build-base the installed rockcraft does not accept",
    "unknown-release": "chisel-releases has no branch for the release slices are read from (the base, or a `chisel cut --release`): use one it has, or build unchiseled",
    "bare-needs-build-base": "base: bare without build-base",
    "version-type": "version is not a string (quote it)",
    "version-granularity": "archive-based rocks version XX.YY; a patch level needs a pinned source-tag",
    "root-user": "no `run-user: _daemon_`: the rock runs as root -- set it or justify it",
    "bad-platform": "a platform without `build-for` whose name is not a Debian architecture",
    "service-command": "a Pebble service command must start with an absolute path",
    "service-override": "a Pebble service without `override: replace`",
    "mixed-stage": "a part mixes slices and whole debs in stage-packages",
    "debs-on-bare": "whole debs on base: bare -- use slices, or an ubuntu@ base for an unchiseled rock",
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
    if BRANCH.fullmatch(rel):
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


def accepted(report: common.Report) -> dict | None:
    """What the installed rockcraft accepts at the top level of a
    rockcraft.yaml: its keys, the required ones, and the values of base and
    build-base, as the schema of that version states them. None, with the
    reason recorded, when that cannot be read: there is no list to fall back on."""
    try:
        version = orientation.rockcraft_version()
        if version is None:
            raise orientation.Failed("rockcraft is not installed, so what it accepts is unknown")
        schema = orientation.rockcraft_schema(version)
        props = schema["properties"]
        # build-base is "one of these, or null": an alternative that is neither
        # would let values through that no list here names
        build = [alt.get("enum") for alt in props["build-base"]["anyOf"] if alt != {"type": "null"}]
        takes = {
            "keys": props,
            "required": schema["required"],
            "base": props["base"]["enum"],
            "build-base": [e for enum in build for e in enum],
        }
        names = (takes["required"], takes["base"], takes["build-base"])
        shaped = (
            isinstance(props, dict)
            and all(isinstance(n, list) and all(isinstance(e, str) for e in n) for n in names)
            and takes["base"]
            and takes["build-base"]
            # only a schema that forbids other keys makes an unlisted key a rejection
            and schema.get("additionalProperties") is False
        )
        if not shaped:
            raise orientation.Failed(f"rockcraft {version}: its schema is not in a shape this reads")
    except (AttributeError, KeyError, TypeError) as e:
        report.mark_unavailable("rockcraft schema", f"its schema does not read: {e!r}")
    except orientation.Failed as e:
        report.mark_unavailable("rockcraft schema", str(e))
    else:
        return takes
    return None


def check(doc: object, f: str, report: common.Report) -> None:
    add = report.add
    if not isinstance(doc, dict):
        add("block", "not-a-mapping", f)
        return
    takes = accepted(report)
    # `parts` is generated when an extension is used
    generated = {"parts": doc.get("extensions")}
    for k in takes["required"] if takes else ():
        absent = doc.get(k) is None or (k == "name" and doc[k] == "")
        if absent and not generated.get(k) and k != "version":
            add("block", "missing-key", f, key=k)
    # not in the schema: craft-application asks for a version after validating,
    # unless a part is named to set it (craft_application/services/project.py,
    # "'adopt-info' not set and required fields are missing").
    if doc.get("version") is None and not doc.get("adopt-info"):
        add("block", "missing-key", f, key="version")
    for k in doc if takes else ():
        if k not in takes["keys"]:
            add("block", "unknown-key", f, key=k)

    base, bb = doc.get("base"), doc.get("build-base")
    refused = set()
    for key, value in (("base", base), ("build-base", bb)):
        if takes and value is not None and value not in takes[key]:
            refused.add(key)
            add("block", "bad-base", f, key=key, value=str(value), accepted=" ".join(takes[key]))
    if base == "bare" and not bb:
        add("block", "bare-needs-build-base", f)
    # slices are looked up on the chisel-releases branch of the release the
    # rock is built from. none when that base was refused, or is `devel`,
    # which names no release.
    key, value = ("build-base", bb) if base == "bare" else ("base", base)
    m = None if key in refused else BASE.match(str(value))
    release = f"ubuntu-{m.group(1)}" if m else None

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
    unchecked = False
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
        # "" stands for "the rock's release, and there is none": told apart
        # from None, a tree that is deliberately not read
        wanted = [(release or "", sl)]
        for k, val in p.items():
            if str(k).startswith("override-") and isinstance(val, str):
                wanted += [(cut_from(rel, p, release or ""), s) for rel, s in cuts(val)]
        for tree, slices in wanted:
            if tree:
                used.setdefault(tree, set()).update(slices)
            elif tree == "" and slices:
                unchecked = True
    if unchecked and key not in refused:
        report.mark_unavailable(
            "slices", f"{key}: {value} names no release, so slices that depend on it were not checked"
        )
    if doc.get("package-repositories") and base == "bare":
        add("warn", "ppa-on-bare", f)
    if base == "bare" and debs:
        add("warn", "debs-on-bare", f, value=" ".join(debs))

    for rel, slices in used.items():
        if not slices:
            continue
        try:
            # asked first: on a branch that is not there every slice would
            # look missing, one finding each, for a single cause
            if BRANCH.fullmatch(rel) and not rl.has_branch(rel):
                add("block", "unknown-release", f, release=rel)
                continue
        except rl.Unavailable as e:
            report.mark_unavailable("slices", str(e))
            return
        for pkg in sorted({s.split("_", 1)[0] for s in slices}):
            try:
                have = set(rl.slices_of(rel, pkg) or [])
            except rl.Unavailable as e:
                report.mark_unavailable("slices", str(e))
                return
            except ValueError:  # a release Ubuntu's own list does not know
                add("block", "unknown-release", f, release=rel)
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
