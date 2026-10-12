#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""check-slice: deterministic static linter for chisel slice definition files.

Checks the mechanical conventions reviewers and CI enforce -- the rules that do
NOT need judgement or a rootfs cut. Use it two ways:

  - authoring: self-check an SDF while writing it (chisel-slicer).
  - review:    the deterministic first pass of a review (chisel-slice-reviewer),
               so the agent only spends judgement on deps, tests, and design.

It does NOT replace `chisel cut` (installability) or spread tests
(functionality). It only checks the SDF text. yamllint cosmetics (line
length <= 100, blank-line count, indent) are also NOT covered -- CI's lint
job runs yamllint separately.

Usage:
  check-slice.py <slice.yaml> [<slice2.yaml> ...] [--format N | --branch NAME]

Format detection (needed for version-gated fields hint/prefer/v3-essential and
essential-as-map): --format wins, else --branch reads that branch's own
chisel.yaml from the local git object store, else the format: field of
./chisel.yaml, else unknown (gated checks are skipped, noted).

Output: the YAML report described in common.py. A block finding is a hard
gate -- chisel won't parse it, or CI/lint fails -- and fails the check; a warn
one is something reviewers reliably reject; an info one is a nit. An unknown
format makes the check unavailable, since the version-gated checks cannot run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    import _common as common
except ImportError:
    import common

CODES = {
    "yml-extension": "chisel reads only .yaml files and silently ignores this one",
    "bad-filename": "chisel rejects the whole release when an SDF name breaks its rule",
    "no-package": "an SDF needs a top-level package: field",
    "package-mismatch": "package: must match the file name",
    "unsorted": "entries must be in bytewise order; ci lints slice essentials and contents",
    "no-slices": "not a slice definition file: there is no slices: map",
    "no-copyright-slice": "reviewers expect every SDF to ship a copyright slice",
    "no-copyright": "the copyright slice ships neither the copyright file nor a shared-copyright doc dir",
    "copyright-not-essential": "the package-wide essential should hold <pkg>_copyright, so every slice ships it",
    "bad-slice-name": "chisel rejects slice names that break its rule (parse error)",
    "slice-name": "reviewers reject this slice name; use the suggested one",
    "hint-format": "hint: is a v3+ branch convention; chisel parses it but v1/v2 branches do not use it",
    "hint-too-long": "chisel caps hint: at 40 characters (parse error)",
    "hint-unprintable": "hint: must be one line of printable characters (parse error)",
    "hint-style": "validate-hints ci: sentence case, no leading article, no trailing punctuation, single spaces, letters, digits and . , ; ( ) only",
    "clutter": "a minimal rootfs ships no man pages, shell completions or doc metadata",
    "doc-clutter": "ship only copyright, notice and licence files from /usr/share/doc",
    "relative-path": "content paths must be absolute",
    "generate-value": "generate: takes only the value manifest (parse error)",
    "generate-path": "a generate: path ends in /** and holds no other wildcard (parse error)",
    "generate-options": "a generate: path takes no option but arch: (parse error)",
    "glob-options": "a wildcard path takes only until: and arch: (parse error); name the path instead",
    "make-path": "make: true needs a path ending in / (parse error)",
    "prefer-self": "prefer: must name another package (parse error)",
    "prefer-format": "prefer: is a v2+ branch convention; chisel older than 1.2.0 ignores it silently",
    "bad-arch": "arch names are Debian ones: amd64 arm64 armhf i386 ppc64el riscv64 s390x (parse error)",
    "v3-essential": "v3-essential is rejected on v3 (parse error); fold it into the essential: map",
    "essential-map": "map-form essential needs format v3 (parse error)",
    "essential-list": "v3 needs map-form essential (parse error: 'essential expects a map')",
    "not-utf8": "the file is not valid UTF-8",
    "yaml-error": "the file does not parse as YAML",
    "not-a-mapping": "the top level of an SDF must be a mapping",
}

# known-bad slice names reviewers reject, mapped to the right one. by-function
# and per-binary names (e.g. printing-text, ls-bin, journal) are legitimate, so
# only these exact mistakes are flagged -- not "anything off a fixed vocabulary".
BAD_SLICE_NAMES = {
    "bin": "bins",
    "lib": "libs",
    "all": "core",
    "configs": "config",
    "rules": "udev-rules",
    "license": "copyright",
    "notice": "copyright",
}

# base-files really does own bin/lib (they build the /bin and /lib trees, not
# executables), and fonts-ubuntu is the one legitimate umbrella `all`.
BAD_NAME_EXEMPT = {"base-files": {"bin", "lib"}, "fonts-ubuntu": {"all"}}

# Debian arch names -- always lowercase, never x86_64/aarch64. (arch-list order
# is not enforced: real SDFs use a priority order, not alphabetical.)
VALID_ARCHES = {"amd64", "arm64", "armhf", "i386", "ppc64el", "riscv64", "s390x"}

# chisel's own slice-name rule (internal/setup: SnameExp) -- no trailing or
# doubled hyphens, which a plain charset class would let through.
SNAME_RE = re.compile(r"^[a-z](?:-?[a-z0-9]){2,}$")

# chisel's SDF filename rule (internal/setup: FnameExp). a non-matching .yaml
# basename fails the whole release parse; a non-.yaml file is silently ignored.
FNAME_RE = re.compile(r"^[a-z0-9](?:-?[.a-z0-9+]){1,}\.yaml$")

# paths a minimal rootfs never needs -- see kb/_slice-conventions.md "Exclude by Default".
CLUTTER = {
    "man pages": ("/usr/share/man/", "/usr/man/"),
    "shell completions": (
        "/usr/share/bash-completion/",
        "/usr/share/fish/",
        "/usr/share/zsh/",
        "/etc/bash_completion.d/",
    ),
    "doc-base/lintian metadata": ("/usr/share/doc-base/", "/usr/share/lintian/"),
}

# legal files that legitimately live under /usr/share/doc alongside copyright
# (not clutter). basename stem, uppercased, after stripping a text/compress suffix.
LEGAL_DOC = {
    "COPYRIGHT",
    "NOTICE",
    "LICENSE",
    "LICENCE",
    "THIRDPARTYNOTICES",
    "THIRD-PARTY-NOTICES",
}


def is_legal_doc(basename: str) -> bool:
    stem = basename
    for suf in (".gz", ".xz", ".bz2", ".txt", ".md", ".rst"):
        if stem.lower().endswith(suf):
            stem = stem[: -len(suf)]
    return stem.upper() in LEGAL_DOC


class Findings:
    """One file's findings, added to the report shared by every file checked."""

    def __init__(self, report: common.Report, file: str) -> None:
        self.report = report
        self.file = file

    def block(self, code: str, **fields: Any) -> None:
        self.report.add("block", code, self.file, **fields)

    def warn(self, code: str, **fields: Any) -> None:
        self.report.add("warn", code, self.file, **fields)


def slices_of(doc: Any) -> dict:
    s = doc.get("slices") if isinstance(doc, dict) else None
    return s if isinstance(s, dict) else {}


def is_sorted(keys: list) -> bool:
    strs = [k for k in keys if isinstance(k, str)]
    return strs == sorted(strs)


def check_filename(doc: Any, path: Path, f: Findings) -> None:
    if path.name.endswith(".yml"):
        f.block("yml-extension")
    elif not FNAME_RE.match(path.name):
        f.block("bad-filename", rule=FNAME_RE.pattern)
    stem = path.name[:-5] if path.name.endswith(".yaml") else path.stem
    pkg = doc.get("package") if isinstance(doc, dict) else None
    if not isinstance(pkg, str) or not pkg:
        f.block("no-package")
    elif pkg != stem:
        f.block("package-mismatch", package=pkg, **{"file-stem": stem})


def check_essential_sorted(doc: Any, f: Findings) -> None:
    # per-slice essential + contents sorting is the CI lint gate (LC_COLLATE=C,
    # sort -C). the top-level essential is not CI-gated, but keep it sorted for
    # consistency -- so warn, don't block.
    if isinstance(doc.get("essential"), list) and not is_sorted(doc["essential"]):
        f.warn("unsorted", field="essential")
    for name, body in slices_of(doc).items():
        ess = body.get("essential") if isinstance(body, dict) else None
        keys = (
            ess if isinstance(ess, list) else list(ess) if isinstance(ess, dict) else []
        )
        if not is_sorted(keys):
            f.block("unsorted", slice=name, field="essential")


def check_slices(doc: Any, fmt: int | None, f: Findings) -> None:
    slices = slices_of(doc)
    if not slices:
        f.block("no-slices")
        return
    pkg = doc.get("package") if isinstance(doc.get("package"), str) else ""

    # copyright: a strong convention, not a CI parse/lint gate (some merged
    # library SDFs skip it), so warn. it ships either the copyright file
    # directly, or the doc dir as a symlink to another package's (shared).
    cp = slices.get("copyright")
    if not isinstance(cp, dict):
        f.warn("no-copyright-slice")
    elif pkg:
        contents = cp.get("contents") if isinstance(cp.get("contents"), dict) else {}
        docdir = f"/usr/share/doc/{pkg}"
        if not any(
            k in contents for k in (f"{docdir}/copyright", docdir, docdir + "/")
        ):
            f.warn("no-copyright", slice="copyright", expected=f"{docdir}/copyright")
    ess = doc.get("essential")
    if (
        pkg
        and not (isinstance(ess, list) and f"{pkg}_copyright" in ess)
        and not (isinstance(ess, dict) and f"{pkg}_copyright" in ess)
    ):
        f.warn("copyright-not-essential", expected=f"{pkg}_copyright")

    for name, body in slices.items():
        if not isinstance(name, str) or not SNAME_RE.match(name):
            f.block("bad-slice-name", slice=name, rule=SNAME_RE.pattern)
        if not isinstance(body, dict):
            continue
        check_slice_body(name, body, pkg, fmt, f)


# validate-hints allows only these chars; chisel core caps length at 40 and
# rejects non-printable. see kb/_slice-definition-format.md "hint: style".
_HINT_ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,;()"
)


def check_hint(name: str, hint: Any, f: Findings) -> None:
    if not isinstance(hint, str):
        return
    at = {"slice": name, "field": "hint"}
    # chisel core (parse errors):
    if len(hint) > 40:
        f.block("hint-too-long", **at, length=len(hint))
    if "\n" in hint or any(not c.isprintable() for c in hint):
        f.block("hint-unprintable", **at)
    # validate-hints CI style (noun phrase; the finite-verb rule needs NLP, skipped):
    if hint[:1].islower():
        f.warn("hint-style", **at, rule="case")
    if re.match(r"(?i)^(a|an|the)\b", hint):
        f.warn("hint-style", **at, rule="article")
    if hint[-1:] in {".", ",", ";", ":", "!", "?", " "}:
        f.warn("hint-style", **at, rule="punctuation")
    if "  " in hint or hint != hint.strip():
        f.warn("hint-style", **at, rule="spacing")
    stray = sorted(set(hint) - _HINT_ALLOWED - {"\n"})
    if stray:
        f.warn("hint-style", **at, rule="chars", chars=stray)


def check_slice_body(
    name: str, body: dict, pkg: str, fmt: int | None, f: Findings
) -> None:
    if name in BAD_SLICE_NAMES and name not in BAD_NAME_EXEMPT.get(pkg, ()):
        f.warn("slice-name", slice=name, use=BAD_SLICE_NAMES[name])

    if "hint" in body:
        # chisel validates hint under every format -- the v3+ rule is branch
        # convention, not a parse error, so warn rather than block.
        if fmt is not None and fmt < 3:
            f.warn("hint-format", slice=name, field="hint", format=f"v{fmt}")
        check_hint(name, body["hint"], f)

    contents = body.get("contents")
    if not isinstance(contents, dict):
        return
    keys = list(contents.keys())
    if not is_sorted(keys):
        f.block("unsorted", slice=name, field="contents")
    for path, entry in contents.items():
        check_path(name, path, entry, pkg, fmt, f)


# options chisel rejects on a glob path: everything that defines content, plus
# prefer. only until: and arch: survive. (internal/setup: "invalid wildcard options")
GLOB_INCOMPATIBLE = ("copy", "make", "text", "symlink", "mode", "mutable", "prefer")

# a generate: path is stricter still -- arch: is the only companion it takes.
GENERATE_INCOMPATIBLE = GLOB_INCOMPATIBLE + ("until",)


def check_path_kind(sname: str, path: str, entry: dict, f: Findings) -> None:
    """The three path-shape rules chisel enforces at parse time."""
    at = {"slice": sname, "path": path}
    if entry.get("generate") is not None:
        if entry.get("generate") != "manifest":
            f.block("generate-value", **at)
        if not path.endswith("/**") or "*" in path[:-3] or "?" in path:
            f.block("generate-path", **at)
        bad = [k for k in GENERATE_INCOMPATIBLE if k in entry]
        if bad:
            f.block("generate-options", **at, options=bad)
        return

    if "*" in path or "?" in path:
        bad = [k for k in GLOB_INCOMPATIBLE if k in entry]
        if bad:
            f.block("glob-options", **at, options=bad)

    if entry.get("make") and not path.endswith("/"):
        f.block("make-path", **at)


def check_path(
    sname: str, path: Any, entry: Any, pkg: str, fmt: int | None, f: Findings
) -> None:
    at = {"slice": sname, "path": path}
    if not isinstance(path, str) or not path.startswith("/"):
        f.block("relative-path", **at)
        return
    for label, prefixes in CLUTTER.items():
        if any(path.startswith(p) for p in prefixes):
            f.warn("clutter", **at, kind=label)
    if path.startswith("/usr/share/doc/"):
        docdir = f"/usr/share/doc/{pkg}"
        base = path.rstrip("/").rsplit("/", 1)[-1]
        # exempt the package's own doc dir (shared-copyright symlink) and legal files.
        if pkg and path.rstrip("/") != docdir and not is_legal_doc(base):
            f.warn("doc-clutter", **at)

    if not isinstance(entry, dict):
        return

    check_path_kind(sname, path, entry, f)

    prefer = entry.get("prefer")
    if prefer is not None:
        # not format-gated in chisel; naming your own package is a parse error.
        if prefer == pkg:
            f.block("prefer-self", **at)
        if fmt is not None and fmt < 2:
            f.warn("prefer-format", **at, format=f"v{fmt}")
    arch = entry.get("arch")
    archs = (
        [arch] if isinstance(arch, str) else arch if isinstance(arch, list) else None
    )
    if archs is not None:
        bad = [a for a in archs if a not in VALID_ARCHES]
        if bad:
            f.block("bad-arch", **at, arch=bad)


def check_v3_essential(doc: Any, fmt: int | None, f: Findings) -> None:
    # essential shape is format-gated both ways: map on v1/v2 is a parse error,
    # list on v3 is a parse error ("essential expects a map"). v3-essential is
    # the pre-v3 backport (needs chisel>=1.3.0): valid on v1/v2, a hard parse
    # error on v3 (top-level or per-slice).
    if fmt is None:
        return
    version = f"v{fmt}"
    bodies = [({}, doc)]
    bodies += [
        ({"slice": n}, b) for n, b in slices_of(doc).items() if isinstance(b, dict)
    ]
    for at, body in bodies:
        if "v3-essential" in body and fmt >= 3:
            f.block("v3-essential", **at, field="v3-essential", format=version)
        ess = body.get("essential")
        if isinstance(ess, dict) and fmt < 3:
            f.block("essential-map", **at, field="essential", format=version)
        elif isinstance(ess, list) and fmt >= 3:
            f.block("essential-list", **at, field="essential", format=version)


def format_of_branch(branch: str) -> int | None:
    """Resolve a branch's format from *its own* chisel.yaml, read out of the local
    git object store -- no hardcoded branch->format table, no network. A static
    linter reads the reviewed revision: `git show <ref>:chisel.yaml`, trying
    the local ref then origin/<ref> (in a fresh clone the target release is often
    only a remote-tracking ref, which is exactly the cross-branch case --branch
    serves). None if the ref/file/format can't be found, which blocks: the
    version-gated checks cannot run. Pass --format N to force it."""
    for ref in (branch, f"origin/{branch}"):
        try:
            r = subprocess.run(
                ["git", "show", f"{ref}:chisel.yaml"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode == 0:
            m = re.search(r"^format:\s*\"?v?(\d+)", r.stdout, re.MULTILINE)
            return int(m.group(1)) if m else None
    return None


def detect_format(argv_fmt: int | None, argv_branch: str | None) -> int | None:
    if argv_fmt is not None:
        return argv_fmt
    if argv_branch:
        return format_of_branch(argv_branch)
    cy = Path("chisel.yaml")
    if cy.exists():
        try:
            doc = yaml.safe_load(cy.read_text(encoding="utf-8"))
            v = str(doc.get("format", "")) if isinstance(doc, dict) else ""
            m = re.search(r"(\d+)", v)
            if m:
                return int(m.group(1))
        except (yaml.YAMLError, OSError):
            pass
    return None


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that errors on duplicate mapping keys (safe_load keeps the
    last one silently, so a pasted-twice contents path is invisible to it --
    but CI's yamllint fails on it)."""


def _no_dup_keys(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.YAMLError(
                f"duplicate mapping key {key!r} (line {key_node.start_mark.line + 1})"
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup_keys
)


def check_file(path: Path, fmt: int | None, report: common.Report) -> None:
    f = Findings(report, str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        f.block("not-utf8")
        return
    except OSError as e:
        report.mark_unavailable("read", f"{path}: {e}")
        return
    try:
        doc = yaml.load(text, Loader=_StrictLoader)
    except yaml.YAMLError as e:
        f.block("yaml-error", error=str(e).splitlines()[0])
        return
    if not isinstance(doc, dict):
        f.block("not-a-mapping")
        return
    check_filename(doc, path, f)
    check_essential_sorted(doc, f)
    check_slices(doc, fmt, f)
    check_v3_essential(doc, fmt, f)


USAGE = "usage: check-slice.py <slice.yaml> [...] [--format N | --branch NAME]"


def main(argv: list[str]) -> int:
    files: list[str] = []
    fmt_arg: int | None = None
    branch_arg: str | None = None

    def parse_fmt(value: str) -> int:
        # accept "3", "v3", "chisel-v3" -- orientation prints "v1"-style strings.
        m = re.search(r"(\d+)", value)
        if not m:
            print(f"check-slice.py: bad --format value {value!r}", file=sys.stderr)
            raise SystemExit(common.usage(USAGE))
        return int(m.group(1))

    it = iter(argv)
    for a in it:
        if a in ("--format", "--branch"):
            value = next(it, None)
            if value is None:
                print(f"check-slice.py: {a} needs a value", file=sys.stderr)
                return common.usage(USAGE)
            if a == "--format":
                fmt_arg = parse_fmt(value)
            else:
                branch_arg = value
        elif a.startswith("--format="):
            fmt_arg = parse_fmt(a.split("=", 1)[1])
        elif a.startswith("--branch="):
            branch_arg = a.split("=", 1)[1]
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            files.append(a)
    if not files:
        return common.usage(USAGE)

    fmt = detect_format(fmt_arg, branch_arg)
    report = common.Report(CODES)
    if fmt is None:
        report.mark_unavailable(
            "format",
            "unknown, so hint/prefer/v3-essential/essential-shape checks were skipped; "
            "run inside the target checkout or pass --format N",
        )
    for name in files:
        check_file(Path(name), fmt, report)
    return report.emit()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
