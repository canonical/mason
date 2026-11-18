#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""pack-rock: run `rockcraft pack -v` in the project and turn a failure into a
diagnosis.

On success the rock file is reported, and -- in a git project where a tracked
rockcraft.yaml was edited -- the fix is committed (Conventional Commits).
On failure the first error (later ones usually cascade) is classified against
a fixed taxonomy; the finding names the failing step and part, the evidence
lines, and the fix strategy. For a misnamed slice it looks up the package's
real slices and names the closest one. It never edits rockcraft.yaml, and a
packed rock is not proof the rock runs.

Usage: pack-rock.py

Unavailable when rockcraft is not installed, or there is no ./rockcraft.yaml.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import _common as common
    import _rocklib as rl
except ImportError:
    import common
    import rocklib as rl

# rockcraft colours its console output; strip before matching.
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# category -> console patterns, first match wins. patterns are taken from real
# rockcraft 1.21 output; invalid-yaml comes first because it fails before any
# lifecycle step.
TAXONOMY = {
    "invalid-yaml": [
        r"Bad rockcraft\.yaml content", r"Project file 'rockcraft\.yaml' not found",
        r"Usage: rockcraft", r"unrecognized arguments",
    ],
    "missing-chisel-slice": [
        r"Failed to cut requested chisel slices", r"slice \S+ not found",
        r'slices of package "[^"]+" not found', r"no slice definitions found",
        r"requires \S+, but slice is missing",
    ],
    "missing-package": [
        r"Unable to locate package", r"Package '[^']+' (?:not found|has no installation candidate)",
        r"Couldn't find package",
    ],
    "source-fetch-failure": [
        r"Failed to pull", r"fatal: repository .* not found", r"Could not resolve host",
        r"Could not read from remote repository", r"Remote branch \S+ not found",
    ],
    "organize-mismatch": [r"Failed to organize", r"organize.*No such file"],
    "permission-error": [
        r"Permission denied", r"Operation not permitted", r"changing (?:ownership|permissions) of",
    ],
    "craftctl-misuse": [r"craftctl: (?:command )?not found"],
    "cyclic-dependency": [r"[Cc]yclic dependency", r"circular dependency"],
    "override-scriptlet-error": [
        r"Failed to run '?override-", r": command not found", r"scriptlet\.sh: line \d+",
    ],
    "plugin-build-failure": [
        r"make: \*\*\*", r"CMake Error", r"error: could not compile", r"npm ERR!",
        r"BUILD FAILURE", r"go: .*(?:cannot find|not found)", r"pip.*error",
    ],
}  # fmt: skip

# the fix strategy per category -- the `codes` legend of the report.
CODES = {
    "invalid-yaml": "rockcraft rejected the file or the command line; check-rock.py names every problem",
    "missing-chisel-slice": (
        "a slice name rockcraft could not cut: use the real name (`fix`); a package with no "
        "slices at all needs them authored, never whole debs on base: bare"
    ),
    "missing-package": "a deb name that does not exist for this release",
    "source-fetch-failure": "the part's source / source-tag / -branch / -commit cannot be fetched",
    "organize-mismatch": "organize: keys that do not match what the build installed",
    "permission-error": "permissions: entries -- numeric owner/group (_daemon_ = 584792), octal modes, real paths",
    "craftctl-misuse": "craftctl used outside an override-* scriptlet",
    "cyclic-dependency": "an `after:` edge closes a cycle",
    "override-scriptlet-error": "a scriptlet command failed; a missing tool goes in that part's build-packages",
    "plugin-build-failure": "the root compiler / linker error above the plugin failure; usually a missing -dev build-package",
    "unknown": "no known pattern: read the full log, then the build instance",
}

# the lifecycle line preceding the error names the failing step + part.
STEP = re.compile(r"\b(Pulling|Overlaying|Building|Staging|Priming) (\S+)")
STEP_NAME = {
    "Pulling": "PULL",
    "Overlaying": "OVERLAY",
    "Building": "BUILD",
    "Staging": "STAGE",
    "Priming": "PRIME",
}

# "Logging execution to '<path>'" at start, "Full execution log: '<path>'" on failure.
LOG = re.compile(r"(?:Full execution log|Logging execution to):? '([^']+)'")


def diagnose(text: str) -> dict:
    lines = [ANSI.sub("", ln) for ln in text.splitlines()]
    # host-side path: the final "Full execution log", else the first "Logging
    # execution to" (later ones are inside the build instance).
    logs = [(m.group(0), m.group(1)) for ln in lines if (m := LOG.search(ln))]
    log = next(
        (p for t, p in reversed(logs) if t.startswith("Full")),
        logs[0][1] if logs else None,
    )
    for cat, pats in TAXONOMY.items():
        hits = [i for i, ln in enumerate(lines) if any(re.search(p, ln) for p in pats)]
        if hits:
            step = part = None
            for ln in reversed(lines[: hits[0] + 1]):
                m = STEP.search(ln)
                if m:
                    step, part = STEP_NAME[m.group(1)], m.group(2)
                    break
            return {"category": cat, "step": step, "part": part,
                    "evidence": [lines[i].strip() for i in hits[:6]], "log": log}  # fmt: skip
    tail = [ln.strip() for ln in lines if ln.strip()][-8:]
    return {
        "category": "unknown",
        "step": None,
        "part": None,
        "evidence": tail,
        "log": log,
    }


def release_of(yaml_text: str) -> str | None:
    base = re.search(r"^base:\s*(\S+)", yaml_text, re.MULTILINE)
    bb = re.search(r"^build-base:\s*(\S+)", yaml_text, re.MULTILINE)
    v = bb if base and base.group(1).strip("\"'") == "bare" else base
    m = re.search(r"(\d\d\.\d\d)", v.group(1)) if v else None
    return f"ubuntu-{m.group(1)}" if m else None


def slice_fixes(evidence: list[str], report: common.Report) -> dict[str, str]:
    """misnamed slice -> the closest real slice of its package."""
    bad = set()
    for ln in evidence:
        bad.update(re.findall(r"slice ([a-z0-9.+-]+_[a-z0-9-]+) not found", ln))
        bad.update(re.findall(r'no slice definitions found for: "([^"]+)"', ln))
    rel = release_of(Path("rockcraft.yaml").read_text(encoding="utf-8"))
    fixes = {}
    for b in sorted(bad) if rel else []:
        pkg = b.split("_", 1)[0]
        try:
            have = rl.slices_of(rel, pkg)
        except rl.Unavailable as e:
            report.mark_unavailable("slices", str(e))
            break
        if have is None:
            fixes[b] = f"no slices for {pkg} on {rel}"
        else:
            fixes[b] = difflib.get_close_matches(b, have, n=1, cutoff=0)[0]
    return fixes


def commit() -> str | None:
    """commit a fix to a git-tracked rockcraft.yaml (+ other tracked files) --
    never the built .rock or untracked files; new projects are left alone."""
    if common.git(["rev-parse", "--git-dir"]) is None:
        return None
    if common.git(["ls-files", "--error-unmatch", "rockcraft.yaml"]) is None:
        return None
    if not (
        common.git(["status", "--porcelain", "--untracked-files=no"]) or ""
    ).strip():
        return None
    msg = "fix(rock): make rockcraft pack succeed"
    r = subprocess.run(
        ["git", "commit", "-qam", msg], capture_output=True, text=True, check=False
    )
    return msg if r.returncode == 0 else f"commit failed: {r.stderr.strip()}"


def main() -> int:
    if len(sys.argv) > 1:
        return common.usage(__doc__.strip())
    report = common.Report(CODES)
    if not Path("rockcraft.yaml").exists():
        report.mark_unavailable("pack", f"no rockcraft.yaml in {Path.cwd()}")
        return report.emit()
    if not shutil.which("rockcraft"):
        report.mark_unavailable(
            "pack", "rockcraft is not installed (snap install rockcraft --classic)"
        )
        return report.emit()

    r = subprocess.run(
        ["rockcraft", "pack", "-v"], capture_output=True, text=True, check=False
    )
    text = r.stdout + r.stderr
    if r.returncode == 0:
        report.data["rock"] = (
            re.findall(r"Packed (\S+\.rock)", ANSI.sub("", text)) or None
        )
        report.data["commit"] = commit()
        return report.emit()

    d = diagnose(text)
    fixes = (
        slice_fixes(d["evidence"], report)
        if d["category"] == "missing-chisel-slice"
        else {}
    )
    report.add("block", d["category"], "rockcraft.yaml", step=d["step"], part=d["part"],
               fix=", ".join(f"{k} -> {v}" for k, v in fixes.items()) or None)  # fmt: skip
    report.data["evidence"] = d["evidence"]
    report.data["log"] = d["log"]
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
