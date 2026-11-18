#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""check-rock: deterministic static linter for a rockcraft.yaml.

Checks what rockcraft itself would reject, plus the rock conventions -- the
rules that do NOT need judgement or a build -- so a pack is never spent on a
typo. Slices are checked to exist on the release (or on a local
chisel-releases checkout a part sources), not that they carry what the
workload needs. It does not replace a pack.

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
    "entrypoint-service", "environment", "parts", "package-repositories",
    "extensions", "adopt-info",
}  # fmt: skip

# keys rockcraft requires (`parts` is generated when an extension is used).
REQUIRED = (
    "name",
    "version",
    "summary",
    "description",
    "license",
    "base",
    "platforms",
    "parts",
)

# Debian arch names -- the only platform names rockcraft accepts; never
# x86_64 / aarch64.
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
    "bad-base": "base / build-base is not `bare` or `ubuntu@XX.YY`",
    "unknown-release": "the base names no known Ubuntu release",
    "bare-needs-build-base": "base: bare without build-base",
    "version-type": "version is not a string (quote it)",
    "version-granularity": "archive-based rocks version XX.YY; a patch level needs a pinned source-tag",
    "license-form": "rockcraft knows only the plain SPDX id (GPL-3.0, not GPL-3.0-or-later)",
    "root-user": "no `run-user: _daemon_`: the rock runs as root -- set it or justify it",
    "bad-platform": "a platform name that is not a Debian architecture",
    "service-command": "a Pebble service command must start with an absolute path",
    "service-override": "a Pebble service without `override: replace`",
    "mixed-stage": "a part mixes slices and whole debs in stage-packages",
    "debs-on-bare": "whole debs on base: bare -- use slices, or an ubuntu@ base for an unchiselled rock",
    "ppa-on-bare": "package-repositories feed whole debs, not slices -- use an ubuntu@ base",
    "unknown-slice": "a slice that does not exist on the release",
}


def cut_slices(script: str) -> list[str]:
    """slice args of every `chisel cut` in a scriptlet."""
    out = []
    joined = script.replace("\\\n", " ")
    for m in re.finditer(r"chisel\s+cut\b(.*?)(?:\n(?!\s)|$)", joined, re.DOTALL):
        out += [t for t in m.group(1).split() if SLICE.match(t)]
    return out


def check(doc: object, f: str, report: common.Report) -> None:
    add = report.add
    if not isinstance(doc, dict):
        add("block", "not-a-mapping", f)
        return
    ext = bool(doc.get("extensions"))
    for k in REQUIRED:
        if k not in doc and not (k == "parts" and ext):
            add("block", "missing-key", f, key=k)
    for k in doc:
        if k not in KNOWN:
            add("block", "unknown-key", f, key=k)

    base, bb = doc.get("base"), doc.get("build-base")
    if base is not None and base != "bare" and not BASE.match(str(base)):
        add("block", "bad-base", f, key="base", value=str(base))
    if base == "bare" and not bb:
        add("block", "bare-needs-build-base", f)
    if bb is not None and not BASE.match(str(bb)):
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
    parts = doc.get("parts") if isinstance(doc.get("parts"), dict) else {}
    pinned = any("source-tag" in (p or {}) for p in parts.values())
    if isinstance(v, str) and not pinned and not re.fullmatch(r"\d+\.\d+", v):
        add("warn", "version-granularity", f, value=v)

    lic = doc.get("license")
    if isinstance(lic, str) and re.search(r"-(or-later|only)$|\+$", lic):
        add("block", "license-form", f, value=lic)
    if doc.get("run-user") != "_daemon_":
        add("warn", "root-user", f)

    plats = doc.get("platforms")
    if isinstance(plats, dict):
        for a in plats:
            if a not in ARCHES:
                add("block", "bad-platform", f, value=str(a))

    for name, svc in (doc.get("services") or {}).items():
        svc = svc or {}
        if not str(svc.get("command", "")).startswith("/"):
            add("block", "service-command", f, service=name)
        if svc.get("override") != "replace":
            add("warn", "service-override", f, service=name)

    used, debs = [], []
    for pname, p in parts.items():
        p = p or {}
        sp = [str(x) for x in p.get("stage-packages") or []]
        sl = [x for x in sp if SLICE.match(x)]
        if sl and len(sl) != len(sp):
            add("block", "mixed-stage", f, part=pname)
        used += sl
        debs += [x for x in sp if not SLICE.match(x)]
        for k, val in p.items():
            if str(k).startswith("override-") and isinstance(val, str):
                used += cut_slices(val)
    if doc.get("package-repositories") and base == "bare":
        add("warn", "ppa-on-bare", f)
    if base == "bare" and debs:
        add("warn", "debs-on-bare", f, value=" ".join(debs))

    if used and release:
        # a part sourcing a local chisel-releases checkout carries new slices
        local = [
            str(p.get("source"))
            for p in parts.values()
            if isinstance(p, dict)
            and p.get("source")
            and Path(str(p["source"]), "chisel.yaml").is_file()
        ]
        rel = local[0] if local else release
        for pkg in sorted({s.split("_", 1)[0] for s in used}):
            try:
                have = set(rl.slices_of(rel, pkg) or [])
            except rl.Unavailable as e:
                report.mark_unavailable("slices", str(e))
                break
            for s in sorted({u for u in used if u.startswith(pkg + "_")} - have):
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
