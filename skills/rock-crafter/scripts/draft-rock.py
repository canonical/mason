#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "spdx"]
# ///
"""draft-rock: write a first-draft rockcraft.yaml, deterministically.

Does the discovery -- versions, licence, build system, runtime slices -- so
the agent only makes the judgement calls. A fresh draft passes check-rock.py,
but for a licence it could not detect. It builds nothing, and cannot know a C project's library dependencies or a
service's configuration: what to review is listed under `review`.

What it decides:
  archive  version XX.YY, SPDX licence and description from the archive;
           slices: <pkg>_bins (else every non-copyright slice) + base-files_base
  ppa      chisel only reads the Ubuntu archive -> base ubuntu@XX.XX, the
           package as a whole deb, a package-repositories entry for the PPA
  source   shallow-clones the tag (default: the newest release tag); a rockcraft
           framework extension for local flask / django / fastapi / expressjs /
           spring-boot projects, else the build plugin (go, rust, uv / python,
           npm, maven, gradle, meson, cmake, autotools, make); version = the
           tag; licence from LICENSE / project metadata; runtime = the
           ecosystem's slices (interpreter versions read off the archive), all
           checked to exist -- any missing -> ubuntu@ base + whole debs
  always   run-user: _daemon_

Usage:
  draft-rock.py <pkg> [<pkg> ...] --release 24.04                  archive
  draft-rock.py <pkg> --ppa <owner>/<name> --release 24.04          PPA
  draft-rock.py <git-url | dir> [--tag <tag>] --release 24.04       source
  options: --service "<cmd> <args>" (absolute binary first), --name <rock>,
           --version <v>, --arch <arch> (default amd64), --unchiselled,
           --chisel-release <checkout> (slices not yet upstream), --force
           (overwrite an existing rockcraft.yaml)

Writes ./rockcraft.yaml only on success. Fails when a package does not
exist, an archive package has no slices (ask the user: author them, or
--unchiselled), or rockcraft.yaml already exists. Unavailable when the
archive, chisel-releases or the source repository cannot be reached.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import spdx

try:
    import _common as common
    import _rocklib as rl
except ImportError:
    import common
    import rocklib as rl


def short(text: str, limit: int = 78) -> str:
    """first sentence, cut at a word boundary under limit."""
    s = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].rstrip(".")
    if len(s) <= limit:
        return s
    return s[:limit].rsplit(" ", 1)[0].rstrip(",;:")


# what the agent should review in the draft, reported under `review`.
REVIEW: list[str] = []

CODES = {
    "package-not-found": "the package is not in the archive / PPA for this release and architecture",
    "missing-slices": "an archive package has no slices on the release: author them, or --unchiselled",
    "exists": "rockcraft.yaml already exists (--force to overwrite)",
    "clone-failed": "the source repository or tag cannot be cloned",
}


def note(msg: str) -> None:
    REVIEW.append(msg)


def licence(lic: str | None) -> str | None:
    """the detected licence if rockcraft knows it (`proprietary`, or an id of the
    SPDX list it reads); else nothing, and a note to set it."""
    known = {rec["id"].strip().lower() for rec in spdx.licenses()}
    if lic and (lic == "proprietary" or lic.strip().lower() in known):
        return lic
    found = f"{lic!r} is not an SPDX id rockcraft knows" if lic else "not detected"
    note(f"license: {found} -- set the SPDX id by hand")
    return None


# --- yaml emitter (deterministic, no pyyaml) -----------------------------------


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if (
        s == ""
        or re.search(r": | #|:$|^[\[\]{},&*!|>'\"%@`#?-]|^\s|\s$", s)
        or re.fullmatch(r"[\d.]+|true|false|null|yes|no|on|off", s, re.IGNORECASE)
    ):
        return json.dumps(s)
    return s


def emit(obj, indent: int = 0) -> list[str]:
    pad = "  " * indent
    out = []
    for k, v in obj.items():
        if k.startswith("#"):
            out.append(f"{pad}{v}")
        elif isinstance(v, dict):
            out.append(f"{pad}{k}:")
            out += emit(v, indent + 1) if v else []
        elif isinstance(v, list) and k == "after":
            out.append(f"{pad}{k}: [{', '.join(v)}]")
        elif isinstance(v, list):
            out.append(f"{pad}{k}:")
            for item in v:
                if isinstance(item, dict):
                    first, *rest = emit(item, indent + 2)
                    out.append(f"{pad}  - {first.strip()}")
                    out += rest
                else:
                    out.append(f"{pad}  - {_scalar(item)}")
        elif isinstance(v, str) and "\n" in v:
            out.append(f"{pad}{k}: |")
            out += [f"{pad}  {ln}" if ln else "" for ln in v.rstrip("\n").split("\n")]
        else:
            out.append(f"{pad}{k}: {_scalar(v)}")
    return out


# --- runtime slices ---------------------------------------------------------------


def resolve_runtime(
    rel: rl.Release, wanted: list[str], chisel_release: str | None
) -> list[str] | None:
    """keep the wanted slices that exist; None if any is missing."""
    ref = chisel_release or rel.branch
    have: dict[str, list[str] | None] = {}
    for s in wanted:
        pkg = s.split("_", 1)[0]
        if pkg not in have:
            have[pkg] = rl.slices_of(ref, pkg)
        if not have[pkg] or s not in have[pkg]:
            note(f"runtime slice {s} not on {ref}")
            return None
    return wanted


def interpreter(rel: rl.Release, meta_pkg: str) -> str | None:
    """the versioned package behind a metapackage, from the archive
    (python3 -> python3.12, default-jre-headless -> openjdk-21-jre-headless)."""
    st = rl.package(meta_pkg, rel)
    for d in rl.deps(st) if st else []:
        if re.fullmatch(r"python3\.\d+|openjdk-\d+-jre-headless", d):
            return d
    return None


# --- sources ------------------------------------------------------------------------


def is_source(arg: str) -> bool:
    return bool(re.match(r"(https?://|git@|ssh://)", arg)) or Path(arg).is_dir()


def latest_tag(url: str) -> str | None:
    r = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", url],
        capture_output=True,
        text=True,
        check=False,
    )
    tags = [
        ln.split("refs/tags/", 1)[1]
        for ln in r.stdout.splitlines()
        if "refs/tags/" in ln
    ]
    rel = [
        t
        for t in tags
        if re.search(r"\d+\.\d+", t)
        and not re.search(r"(rc|alpha|beta|pre|dev|test)", t, re.IGNORECASE)
    ]

    def key(t):
        return tuple(int(x) for x in re.findall(r"\d+", t)[:4])

    return max(rel, key=key) if rel else None


def tag_version(tag: str) -> str:
    m = re.search(r"\d+(?:\.\d+)+", tag)
    return m.group(0) if m else tag


def read(p: Path, limit: int = 200_000) -> str:
    try:
        return p.read_text(errors="replace")[:limit]
    except OSError:
        return ""


def detect(tree: Path, local: bool) -> tuple[str, str]:
    """('extension'|'plugin', name)."""
    f = {p.name.lower(): p for p in tree.iterdir() if p.is_file()}
    pyreq = read(tree / "requirements.txt") + read(tree / "pyproject.toml")
    pkg = read(tree / "package.json")
    jvm = (
        read(tree / "pom.xml")
        + read(tree / "build.gradle")
        + read(tree / "build.gradle.kts")
    )
    if local:
        if (tree / "manage.py").exists() or re.search(
            r"^django\b", pyreq, re.IGNORECASE | re.MULTILINE
        ):
            return "extension", "django-framework"
        if re.search(r"^fastapi\b", pyreq, re.IGNORECASE | re.MULTILINE):
            return "extension", "fastapi-framework"
        if re.search(r"^flask\b", pyreq, re.IGNORECASE | re.MULTILINE):
            return "extension", "flask-framework"
        if '"express"' in pkg:
            return "extension", "expressjs-framework"
        if "spring-boot" in jvm:
            return "extension", "spring-boot-framework"
    for names, plugin in (
        (("go.mod",), "go"),
        (("cargo.toml",), "rust"),
        (("uv.lock",), "uv"),
        (("pyproject.toml", "setup.py", "requirements.txt"), "python"),
        (("package.json",), "npm"),
        (("pom.xml",), "maven"),
        (("build.gradle", "build.gradle.kts"), "gradle"),
        (("meson.build",), "meson"),
        (("cmakelists.txt",), "cmake"),
        (("configure.ac", "configure", "configure.in"), "autotools"),
        (("makefile", "gnumakefile"), "make"),
    ):
        if any(n in f for n in names):
            return "plugin", plugin
    return "plugin", "nil"


def meta(tree: Path) -> dict:
    """name / description / licence / binaries from project metadata."""
    m: dict = {"bins": []}
    pj = read(tree / "package.json")
    if pj:
        try:
            d = json.loads(pj)
            lic = d.get("license")
            m.update(
                name=d.get("name"),
                description=d.get("description"),
                # the legacy {"type": <id>, "url": ...} form still turns up
                license=lic.get("type") if isinstance(lic, dict) else lic,
                node=re.sub(
                    r"[^\d.].*$",
                    "",
                    re.sub(
                        r"^[^\d]*", "", str((d.get("engines") or {}).get("node", ""))
                    ),
                ),
            )
            b = d.get("bin")
            m["bins"] = (
                list(b) if isinstance(b, dict) else ([d.get("name")] if b else [])
            )
        except ValueError:
            pass
    for f, sect in (("Cargo.toml", "package"), ("pyproject.toml", "project")):
        t = read(tree / f)
        if not t:
            continue
        block = re.search(rf"^\[{sect}\](.*?)(?=^\[|\Z)", t, re.MULTILINE | re.DOTALL)
        b = block.group(1) if block else ""
        for k in ("name", "description"):
            mm = re.search(rf'^{k}\s*=\s*"([^"]*)"', b, re.MULTILINE)
            if mm and not m.get(k):
                m[k] = mm.group(1)
        mm = re.search(
            r'^license\s*=\s*(?:"([^"]*)"|\{\s*text\s*=\s*"([^"]*)")', b, re.MULTILINE
        )
        if mm and not m.get("license"):
            m["license"] = mm.group(1) or mm.group(2)
        scripts = re.search(
            r"^\[project\.scripts\](.*?)(?=^\[|\Z)", t, re.MULTILINE | re.DOTALL
        )
        if scripts:
            m["bins"] += re.findall(r"^([\w.-]+)\s*=", scripts.group(1), re.MULTILINE)
        if f == "Cargo.toml":
            m["bins"] += re.findall(
                r'^\[\[bin\]\][^\[]*?^name\s*=\s*"([^"]+)"', t, re.MULTILINE | re.DOTALL
            ) or ([m["name"]] if m.get("name") else [])
    sp = read(tree / "setup.py") + read(tree / "setup.cfg")
    for k in ("name", "description"):
        mm = re.search(
            rf"""^\s*{k}\s*=\s*['"]([^'"\n]+)['"]""", sp, re.MULTILINE
        ) or re.search(rf"^{k}\s*=\s*([^\n]+)$", read(tree / "setup.cfg"), re.MULTILINE)
        if mm and not m.get(k):
            m[k] = mm.group(1).strip()
    gm = read(tree / "go.mod")
    if gm:
        mod = re.search(r"^module\s+(\S+)", gm, re.MULTILINE)
        if mod:
            last = mod.group(1).rstrip("/").split("/")[-1]
            m["name"] = m.get("name") or (
                mod.group(1).split("/")[-2] if re.fullmatch(r"v\d+", last) else last
            )
            m["bins"].append(m["name"])
        gv = re.search(r"^go\s+(\d+\.\d+)", gm, re.MULTILINE)
        m["go"] = gv.group(1) if gv else None
    pom = (
        read(tree / "pom.xml")
        + read(tree / "build.gradle")
        + read(tree / "build.gradle.kts")
    )
    jv = re.search(
        r"<(?:maven\.compiler\.release|java\.version|release)>(\d+)<|languageVersion(?:\.set\(|\s*=\s*)JavaLanguageVersion\.of\((\d+)\)",
        pom,
    )
    m["java"] = (jv.group(1) or jv.group(2)) if jv else None
    for lic in sorted(tree.glob("[LlCcUu][IiOoNn][CcPpLl]*")):
        if (
            re.match(r"(licen[cs]e|copying|unlicense)", lic.name, re.IGNORECASE)
            and lic.is_file()
        ):
            m["license_file"] = rl.license_from_text(read(lic))
            if m["license_file"]:
                break
    readme = next(
        (p for p in tree.glob("[Rr][Ee][Aa][Dd][Mm][Ee]*") if p.is_file()), None
    )
    if readme and not m.get("description"):
        for ln in read(readme).splitlines():
            s = re.sub(r"[*_`\[\]]|\(http\S*\)|<[^>]+>", "", ln).strip()
            if len(s) > 20 and not s.startswith(("#", "!", "=", "-", "|", "[")):
                m["description"] = s
                break
    return m


def source_parts(
    plugin: str, src: dict, tree: Path, m: dict, rel: rl.Release, name: str
):
    """(part, runtime slices wanted, runtime debs fallback, notes)."""
    part = {"plugin": plugin, **src}
    notes = []
    base_rt = ["base-files_base", "ca-certificates_data"]
    if plugin == "go":
        if m.get("go"):
            part["build-snaps"] = [f"go/{m['go']}/stable"]
            notes.append(
                f"build-snaps go/{m['go']}/stable from go.mod -- `snap info go` to confirm the track exists"
            )
        else:
            part["build-snaps"] = ["go/latest/stable"]
        part["build-environment"] = [{"CGO_ENABLED": "0"}]
        return part, base_rt, ["ca-certificates"], notes
    if plugin == "rust":
        return (
            part,
            [*base_rt, "libc6_libs", "libgcc-s1_libs"],
            ["ca-certificates"],
            notes,
        )
    if plugin in ("python", "uv"):
        py = interpreter(rel, "python3") or "python3"
        if plugin == "uv":
            part["build-snaps"] = ["astral-uv"]
        elif (tree / "requirements.txt").exists() and not (
            (tree / "pyproject.toml").exists() or (tree / "setup.py").exists()
        ):
            part["python-requirements"] = ["requirements.txt"]
        notes.append(f"interpreter {py} (the archive's python3 on {rel.version})")
        return (
            part,
            [*base_rt, f"{py}_standard", f"{py}-venv_ensurepip"],
            ["ca-certificates", "python3-venv"],
            notes,
        )
    if plugin == "npm":
        # the archive's nodejs: current for the release, and sliced
        part.update({"npm-include-node": False, "build-packages": ["nodejs", "npm"]})
        if m.get("node"):
            notes.append(
                f"package.json wants node {m['node']}+; using {rel.codename}'s nodejs"
            )
        return part, [*base_rt, "nodejs_bins"], ["ca-certificates", "nodejs"], notes
    if plugin in ("maven", "gradle"):
        jre = interpreter(rel, "default-jre-headless") or "default-jre-headless"
        if m.get("java"):
            want = f"openjdk-{m['java']}-jre-headless"
            jre = want if rl.package(want, rel) else jre
        jdk = jre.replace("-jre-", "-jdk-")
        part["build-packages"] = [jdk] + (["maven"] if plugin == "maven" else [])
        notes.append(f"java runtime {jre}; run with java -jar /jar/<app>.jar")
        return part, [*base_rt, f"{jre}_standard"], ["ca-certificates", jre], notes
    if plugin in ("cmake", "autotools", "meson", "make"):
        bp = {
            "cmake": ["cmake", "build-essential"],
            "meson": ["meson", "ninja-build", "build-essential"],
            "autotools": [
                "autoconf",
                "automake",
                "libtool",
                "pkg-config",
                "build-essential",
            ],
            "make": ["build-essential"],
        }[plugin]
        part["build-packages"] = bp
        notes.append(
            "C/C++: add -dev build-packages for its libraries, and the matching <lib>_libs slices "
            "to the runtime (check the built binary with ldd); autotools without a committed "
            "configure may need `autotools-bootstrap-parameters` or an override-build autoreconf"
        )
        return part, [*base_rt, "libc6_libs"], ["ca-certificates"], notes
    notes.append("no build system detected: plugin nil -- add an override-build")
    return part, base_rt, ["ca-certificates"], notes


# --- main -------------------------------------------------------------------------------


def main() -> int:
    report = common.Report(CODES)
    try:
        return draft(report)
    except rl.Unavailable as e:
        report.mark_unavailable("discovery", str(e))
        return report.emit()


def draft(report: common.Report) -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("sources", nargs="*")
    ap.add_argument("--release")
    ap.add_argument("--ppa")
    ap.add_argument("--tag")
    ap.add_argument("--version")
    ap.add_argument("--name")
    ap.add_argument("--service")
    ap.add_argument("--unchiselled", action="store_true")
    ap.add_argument("--chisel-release")
    ap.add_argument("--arch", default="amd64")
    ap.add_argument("--force", action="store_true")
    a, unknown = ap.parse_known_args()
    if unknown or not a.sources:
        return common.usage(__doc__.strip())
    try:
        rel = rl.resolve_release(a.release)
    except ValueError as e:
        return common.usage(str(e))
    report.data["release"] = f"{rel.version} ({rel.codename})"
    out = Path("rockcraft.yaml")
    if out.exists() and not a.force:
        report.add("block", "exists", out)
        return report.emit()

    doc: dict = {}
    parts: dict = {}
    extra_top: dict = {}
    runtime_wanted: list[str] = []
    runtime_debs: list[str] = []
    chiselled = not a.unchiselled

    if is_source(a.sources[0]):
        src_arg = a.sources[0]
        local = Path(src_arg).is_dir()
        with tempfile.TemporaryDirectory() as tmp:
            if local:
                tree = Path(src_arg)
                tag = a.tag
                src = {
                    "source": src_arg
                    if src_arg.startswith(("/", "."))
                    else f"./{src_arg}",
                    "source-type": "local",
                }
                if not a.version:
                    d = subprocess.run(
                        ["git", "-C", src_arg, "describe", "--tags", "--abbrev=0"],
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout.strip()
                    tag = tag or d or None
            else:
                tag = a.tag or latest_tag(src_arg)
                cmd = (
                    ["git", "clone", "-q", "--depth", "1"]
                    + (["--branch", tag] if tag else [])
                    + [src_arg, f"{tmp}/src"]
                )
                r = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if r.returncode:
                    err = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""
                    if re.search(
                        r"Could not resolve host|unable to access|timed out|Connection",
                        err,
                    ):
                        report.mark_unavailable("source", f"{src_arg}: {err}")
                    else:
                        report.add(
                            "block",
                            "clone-failed",
                            src_arg,
                            tag=tag,
                            reason=err or None,
                        )
                    return report.emit()
                tree = Path(tmp, "src")
                src = {"source": src_arg, "source-type": "git"}
                src.update({"source-tag": tag} if tag else {"source-depth": 1})
            m = meta(tree)
            kind, what = detect(tree, local)
            name = a.name or re.sub(
                r"[^a-z0-9-]+",
                "-",
                (
                    m.get("name")
                    or (
                        tree.resolve() if local else Path(src_arg.rstrip("/"))
                    ).name.removesuffix(".git")
                ).lower(),
            ).strip("-")
            version = a.version or (tag_version(tag) if tag else "0.1")
            lic = licence(rl.spdx(m.get("license")) or m.get("license_file"))
            report.data["source"] = common.Flow(url=src_arg, tag=tag)
            report.data[kind] = what
            report.data["version"] = version
            report.data["license"] = lic
            report.data["binaries"] = m["bins"] or None
            summary = short(m.get("description") or f"{name} built from source")
            if kind == "extension":
                note(
                    f"rockcraft extension {what}: it generates the parts and the service -- the project "
                    "must follow its layout (see the extension docs)"
                )
                doc = {
                    "name": name,
                    "version": version,
                    "summary": summary,
                    "description": summary,
                    "license": lic or "TODO-SPDX",
                    "base": "bare",
                    "build-base": rel.base,
                    "run-user": "_daemon_",
                    "platforms": {a.arch: {}},
                    "extensions": [what],
                }
                return write(doc, out, report)
            part, runtime_wanted, runtime_debs, notes = source_parts(
                what, src, tree, m, rel, name
            )
            for n in notes:
                note(n)
            parts[name] = part
            desc = m.get("description") or summary
    else:
        pkgs = a.sources
        entries = {}
        for p in pkgs:
            st = rl.package(p, rel, a.arch, ppa=a.ppa)
            if not st:
                report.add("block", "package-not-found", p, release=rel.codename, arch=a.arch,
                           ppa=a.ppa)  # fmt: skip
                return report.emit()
            entries[p] = st
        main = entries[pkgs[0]]
        bins, lic = rl.deb_facts(main)
        lic = licence(lic)
        version = a.version or rl.upstream_version(main["Version"])
        dl = main.get("Description", "").splitlines()
        summary = short(dl[0] if dl else pkgs[0])
        desc = (
            "\n".join(ln.strip() for ln in dl[1:] if ln.strip() and ln.strip() != ".")
            or summary
        )
        name = a.name or pkgs[0]
        report.data["package"] = common.Flow(name=pkgs[0], version=main["Version"])
        report.data["version"] = version
        report.data["license"] = lic
        report.data["binaries"] = bins or None
        report.data["depends"] = main.get("Depends") or None
        if a.ppa:
            note(
                "PPA packages can't be chiselled (chisel only reads the Ubuntu archive) -> ubuntu@ base, whole debs"
            )
            chiselled = False
            extra_top["package-repositories"] = [
                {"type": "apt", "ppa": a.ppa, "priority": "always"}
            ]
        if chiselled:
            ref = a.chisel_release or rel.branch
            missing, wanted = [], []
            for p in pkgs:
                have = rl.slices_of(ref, p)
                if have is None:
                    missing.append(p)
                    continue
                own = [s for s in have if s != f"{p}_copyright"]
                wanted += [f"{p}_bins"] if f"{p}_bins" in own else own
            if missing:
                for p in missing:
                    report.add("block", "missing-slices", p, release=ref)
                return report.emit()
            runtime_wanted = ["base-files_base", *wanted]
        else:
            runtime_debs = pkgs
        parts[name] = {"plugin": "nil"}

    # runtime: slices if they all exist, else ubuntu@ base + debs
    if chiselled and runtime_wanted:
        got = resolve_runtime(rel, runtime_wanted, a.chisel_release)
        if got is None:
            note("-> falling back to an unchiselled runtime (base ubuntu@, whole debs)")
            chiselled = False
        else:
            report.data["slices"] = got
            if a.chisel_release:
                part = parts[name]
                if part.get("plugin") == "nil" and "source" not in part:
                    part.update(
                        {
                            "source": a.chisel_release,
                            "source-type": "local",
                            "override-build": 'chisel cut --release ./ --root "${CRAFT_PART_INSTALL}" \\\n  '
                            + " \\\n  ".join(got)
                            + "\n",
                        }
                    )
                    parts = {
                        "# todo": "  # TODO: upstream the new slices to canonical/chisel-releases "
                        f"({rel.branch} + forward-ports), then move them to stage-packages",
                        **parts,
                    }
                else:
                    parts[f"{name}-runtime"] = {
                        "plugin": "nil",
                        "source": a.chisel_release,
                        "source-type": "local",
                        "override-build": 'chisel cut --release ./ --root "${CRAFT_PART_INSTALL}" \\\n  '
                        + " \\\n  ".join(got)
                        + "\n",
                    }
            elif parts[name].get("plugin") == "nil" and "source" not in parts[name]:
                parts[name]["stage-packages"] = got
            else:
                parts[f"{name}-runtime"] = {"plugin": "nil", "stage-packages": got}
    if not chiselled and runtime_debs:
        part = (
            parts[name]
            if parts[name].get("plugin") == "nil" and "source" not in parts[name]
            else None
        )
        if part is not None:
            part["stage-packages"] = runtime_debs
        else:
            parts[name]["stage-packages"] = runtime_debs

    doc = {
        "name": name,
        "title": name,
        "version": version,
        "summary": summary,
        "description": desc + "\n",
        "license": lic or "TODO-SPDX",
    }
    doc.update(
        {"base": "bare", "build-base": rel.base} if chiselled else {"base": rel.base}
    )
    doc.update({"run-user": "_daemon_", "platforms": {a.arch: {}}, **extra_top})
    if a.service:
        svc = a.service.split()[0].rsplit("/", 1)[-1]
        doc["services"] = {
            svc: {"override": "replace", "startup": "enabled", "command": a.service}
        }
    doc["parts"] = parts
    return write(doc, out, report)


def write(doc: dict, out: Path, report: common.Report) -> int:
    lines = []
    for k, v in doc.items():
        if k in ("services", "parts", "package-repositories", "extensions"):
            lines.append("")
        lines += emit({k: v})
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report.data["wrote"] = str(out)
    report.data["review"] = REVIEW or None
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
