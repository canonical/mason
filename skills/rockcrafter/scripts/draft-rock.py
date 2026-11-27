#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""draft-rock: start rockcraft.yaml with `rockcraft init`, then fill in what
was asked for, and have rockcraft validate the result.

It runs `rockcraft init` (the profile given, `rockcraft init -h` lists them)
and fills in the file init wrote; init's comments are not kept. It decides
nothing about the project: the profile, the packages, the source and its
plugin, and the service come from the caller. From the Ubuntu archive it reads
only facts: a package's version and description, and its slices. Rockcraft
itself validates the draft (`rockcraft expand-extensions`), so no list of
keys, plugins or bases is kept here. The report names the schema the installed
rockcraft ships, for every later edit, and what is left to the author under
`review`.

Usage:
  draft-rock.py --name <rock> [--profile <profile>] [--release 24.04] [options]
  options:
    --package <pkg>         stage an archive (or PPA) package: its `<pkg>_bins`
                            slice, else all its slices but `_copyright`, plus
                            `base-files_base`; repeatable
    --slice <pkg_slice>     stage one more slice (a source build's runtime);
                            repeatable
    --ppa <owner>/<name>    the packages come from this PPA: whole debs on an
                            ubuntu@ base, and a package-repositories entry
    --unchiseled            whole debs on an ubuntu@ base
    --source <git-url|dir> --plugin <plugin> [--source-tag <tag>]
                            a part that builds the project with that plugin
    --service "<command>"   a Pebble service named after the rock; the command
                            starts with the binary's absolute path
    --version <v>, --summary <text>, --arch <arch> (default amd64),
    --force (replace an existing rockcraft.yaml)

A framework profile's extension generates the parts and the service, so it
takes none of --package, --slice, --ppa, --source or --service, and rockcraft
checks the project has what the extension needs.

Leaves ./rockcraft.yaml only when rockcraft accepts it. Fails when a package
does not exist, an archive package has no slices (author them, or
--unchiseled), rockcraft rejects the draft, or rockcraft.yaml exists.
Unavailable when rockcraft is not installed, or the archive or chisel-releases
cannot be reached.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import orientation
import rocklib as rl
import yaml

CODES = {
    "exists": "rockcraft.yaml already exists (--force to replace it)",
    "init-failed": "`rockcraft init` refused the name, profile or base",
    "package-not-found": "the package is not in the archive / PPA for this release and architecture",
    "missing-slices": "an archive package has no slices on the release: author them, or --unchiseled",
    "rejected": "rockcraft rejected the draft: correct the option it names",
}

FRAMEWORK_ONLY = ("package", "slice", "ppa", "source", "service")


def tag_version(tag: str) -> str:
    """the version a release tag names: v1.7.1 / jq-1.7.1 -> 1.7.1."""
    m = re.search(r"\d+(?:\.\d+)+", tag)
    return m.group(0) if m else tag


def init(
    a: argparse.Namespace, rel: rl.Release, tmp: Path
) -> subprocess.CompletedProcess:
    cmd = ["rockcraft", "init", "--name", a.name, str(tmp)]
    if a.profile:
        cmd += ["--profile", a.profile]
    # newer rockcraft starts a git repository unless told not to
    helped = subprocess.run(
        ["rockcraft", "init", "-h"], capture_output=True, text=True, check=False
    )
    if "--vcs" in helped.stdout:
        cmd += ["--vcs", "none"]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def validate() -> subprocess.CompletedProcess:
    """rockcraft loads ./rockcraft.yaml through its own models, building
    nothing; a framework extension also checks the project it needs."""
    return subprocess.run(
        ["rockcraft", "expand-extensions"], capture_output=True, text=True, check=False
    )


def said(r: subprocess.CompletedProcess) -> str | None:
    """what rockcraft said went wrong: its listed problems, else its error line."""
    lines = [ln.strip() for ln in (r.stderr + r.stdout).splitlines()]
    lines = [
        ln
        for ln in lines
        if ln
        and not ln.startswith(("Full execution log", "Try ", "For more information"))
    ]
    listed = [ln.removeprefix("- ") for ln in lines if ln.startswith("- ")]
    if listed:
        return " | ".join(listed)
    lines = [ln for ln in lines if ln.startswith("Error:")] or lines
    return lines[0] if lines else None


def schema_location() -> str | None:
    """the schema of rockcraft.yaml the installed rockcraft ships, else the one
    published for its version."""
    url = os.environ.get("ROCKCRAFT_SCHEMA_URL")
    if url is None and orientation.SHIPPED_SCHEMA.is_file():
        return str(orientation.SHIPPED_SCHEMA)
    try:
        version = orientation.rockcraft_version()
    except orientation.Failed:
        return None
    return (
        (url or orientation.ROCKCRAFT_SCHEMA).format(version=version)
        if version
        else None
    )


def put(
    doc: dict, key: str, value, after: str | None = None, before: str | None = None
) -> None:
    """set a key, placing a new one after / before a key init wrote."""
    keys = list(doc)
    if key in doc or not ({after, before} & set(keys)):
        doc[key] = value
        return
    items = list(doc.items())
    items.insert(
        keys.index(after) + 1 if after in keys else keys.index(before), (key, value)
    )
    doc.clear()
    doc.update(items)


def staged(
    a: argparse.Namespace, rel: rl.Release, report: common.Report
) -> tuple[list[str], dict | None]:
    """(stage-packages, the first package's stanza)."""
    stage, first = [], None
    for pkg in a.package:
        st = rl.package(pkg, rel, a.arch, ppa=a.ppa)
        if not st:
            report.add(
                "block",
                "package-not-found",
                pkg,
                release=rel.codename,
                arch=a.arch,
                ppa=a.ppa,
            )
            continue
        first = first or st
        if a.ppa or a.unchiseled:
            stage.append(pkg)
            continue
        have = rl.slices_of(rel.branch, pkg)
        if have is None:
            report.add("block", "missing-slices", pkg, release=rel.branch)
            continue
        own = [s for s in have if s != f"{pkg}_copyright"]
        stage += [f"{pkg}_bins"] if f"{pkg}_bins" in own else own
    if stage and not (a.ppa or a.unchiseled):
        stage.insert(0, "base-files_base")
    stage += [s for s in a.slice if s not in stage]
    return stage, first


def fill(
    doc: dict,
    a: argparse.Namespace,
    rel: rl.Release,
    report: common.Report,
    review: list[str],
) -> None:
    chiseled = not (a.ppa or a.unchiseled)
    framework = bool(doc.get("extensions"))
    stage, first = ([], None) if framework else staged(a, rel, report)
    if first:
        lines = first.get("Description", "").splitlines()
        summary = lines[0].strip() if lines else ""
        body = [ln.strip() for ln in lines[1:] if ln.strip() and ln.strip() != "."]
        doc["summary"] = a.summary or summary
        doc["description"] = "\n".join(body or [summary]) + "\n"
    elif a.summary:
        doc["summary"] = a.summary
        review.append("description: still init's placeholder")
    else:
        review.append("summary, description: still init's placeholders")
    version = a.version or (tag_version(a.source_tag) if a.source_tag else None)
    if not version and first and not a.source:
        version = rl.upstream_version(first["Version"])
    if version:
        doc["version"] = version
    else:
        review.append("version: still init's placeholder")
    if not framework:
        if chiseled:
            doc["base"] = "bare"
            put(doc, "build-base", rel.base, after="base")
        else:
            doc["base"] = rel.base
            doc.pop("build-base", None)
    elif "build-base" in doc:
        doc["build-base"] = rel.base
    else:
        doc["base"] = rel.base
    if not framework:  # an extension sets the user itself
        put(
            doc,
            "run-user",
            "_daemon_",
            after="build-base" if "build-base" in doc else "base",
        )
    doc["platforms"] = {a.arch: None}
    if a.ppa:
        put(
            doc,
            "package-repositories",
            [{"type": "apt", "ppa": a.ppa, "priority": "always"}],
            before="parts",
        )
    if a.service:
        service = {
            a.name: {"override": "replace", "startup": "enabled", "command": a.service}
        }
        put(doc, "services", service, before="parts")
    if framework:
        return
    parts = {}
    if a.source:
        local = Path(a.source).is_dir()
        part = {
            "plugin": a.plugin,
            "source": a.source,
            "source-type": "local" if local else "git",
        }
        if a.source_tag:
            part["source-tag"] = a.source_tag
        elif not local:
            review.append("source: not pinned to a release tag (--source-tag)")
        parts[a.name] = part
        if stage:
            parts[f"{a.name}-runtime"] = {"plugin": "nil", "stage-packages": stage}
        else:
            review.append(
                "runtime: nothing staged for the build's runtime (--slice, kb/rock-slices.md)"
            )
    else:
        parts[a.name] = (
            {"plugin": "nil", "stage-packages": stage} if stage else {"plugin": "nil"}
        )
    doc["parts"] = parts


def main() -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--name")
    ap.add_argument("--profile")
    ap.add_argument("--release")
    ap.add_argument("--package", action="append", default=[])
    ap.add_argument("--slice", action="append", default=[])
    ap.add_argument("--ppa")
    ap.add_argument("--unchiseled", action="store_true")
    ap.add_argument("--source")
    ap.add_argument("--plugin")
    ap.add_argument("--source-tag")
    ap.add_argument("--service")
    ap.add_argument("--version")
    ap.add_argument("--summary")
    ap.add_argument("--arch", default="amd64")
    ap.add_argument("--force", action="store_true")
    a, unknown = ap.parse_known_args()
    framework = a.profile not in (None, "simple")
    if (
        unknown
        or not a.name
        or bool(a.source) != bool(a.plugin)
        or (a.source_tag and not a.source)
        or (a.ppa and not a.package)
        or (framework and any(getattr(a, k) for k in FRAMEWORK_ONLY))
    ):
        return common.usage(__doc__.strip())

    report = common.Report(CODES)
    out = Path("rockcraft.yaml")
    if out.exists() and not a.force:
        report.add("block", "exists", out)
        return report.emit()
    if not shutil.which("rockcraft"):
        report.mark_unavailable(
            "rockcraft", "rockcraft is not installed (snap install rockcraft --classic)"
        )
        return report.emit()
    try:
        try:
            rel = rl.resolve_release(a.release)
        except ValueError as e:
            return common.usage(str(e))
        report.data["release"] = f"{rel.version} ({rel.codename})"
        with tempfile.TemporaryDirectory() as tmp:
            r = init(a, rel, Path(tmp))
            if r.returncode:
                report.add(
                    "block", "init-failed", out, profile=a.profile, reason=said(r)
                )
                return report.emit()
            doc = yaml.safe_load(
                (Path(tmp) / "rockcraft.yaml").read_text(encoding="utf-8")
            )
        review: list[str] = []
        fill(doc, a, rel, report, review)
        if report.count("block"):
            return report.emit()
    except rl.Unavailable as e:
        report.mark_unavailable("discovery", str(e))
        return report.emit()

    before = out.read_bytes() if out.exists() else None
    out.write_text(common.dump(doc), encoding="utf-8")
    r = validate()
    if r.returncode:
        if before is None:
            out.unlink()
        else:
            out.write_bytes(before)
        report.add("block", "rejected", out, reason=said(r))
        return report.emit()
    report.data["wrote"] = str(out)
    report.data["profile"] = a.profile or "simple"
    report.data["schema"] = schema_location()
    report.data["review"] = review or None
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
