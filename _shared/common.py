"""common: the output contract of mason's helper scripts.

Every helper prints one YAML document on stdout; stderr carries only free-form
diagnostics (a wrapped tool's own output, tracebacks, usage errors). The
document opens with `status`:

  passed        the check ran and found nothing that blocks
  failed        something blocks
  unavailable   a check could not establish a result; `unavailable` lists why

and the exit code follows it: 0 passed, 1 failed, 3 unavailable, 2 for a usage
error. A block outranks unavailable: a defect found stays found.

Checkers report findings grouped by file, worst first, one line each:

  findings:
    slices/foo.yaml:
      - {sev: warn, code: removed, slice: bins, path: /usr/bin/foo}

`sev` is block, warn or info; `code` names the kind of finding and `codes`
explains, once, each code that occurs. Reporters put their facts under keys of
their own after the contract keys.

A skill ships this file as _common.py next to its helpers, while _shared/ keeps
it as common.py, so a helper imports whichever of the two is beside it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

PASSED, FAILED, UNAVAILABLE = "passed", "failed", "unavailable"
EXIT = {PASSED: 0, FAILED: 1, UNAVAILABLE: 3}
USAGE = 2
SEVERITIES = ("block", "warn", "info")


class Flow(dict):
    """A mapping dumped on a single line."""


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        # indent a list under its key rather than level with it
        return super().increase_indent(flow, False)


def _str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str)
_Dumper.add_representer(
    Flow,
    lambda dumper, data: dumper.represent_mapping(
        "tag:yaml.org,2002:map", data, flow_style=True
    ),
)


def dump(doc: dict[str, Any]) -> str:
    return yaml.dump(
        doc,
        Dumper=_Dumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=1 << 30,
    )


class Report:
    def __init__(self, codes: dict[str, str]) -> None:
        self.codes = dict(codes)
        self.findings: dict[str, list[Flow]] = {}
        self.unavailable: list[Flow] = []
        self.data: dict[str, Any] = {}

    def add(self, sev: str, code: str, file: Any, **fields: Any) -> None:
        if sev not in SEVERITIES:
            raise ValueError(f"unknown severity {sev!r}")
        if code not in self.codes:
            raise KeyError(f"undeclared finding code {code!r}")
        finding = Flow(sev=sev, code=code)
        finding.update((k, v) for k, v in fields.items() if v is not None)
        self.findings.setdefault(str(file), []).append(finding)

    def mark_unavailable(self, check: str, reason: str) -> None:
        self.unavailable.append(Flow(check=check, reason=reason))

    def merge(self, doc: dict[str, Any]) -> None:
        """Fold in another helper's parsed document."""
        codes = doc.get("codes") or {}
        for file, items in (doc.get("findings") or {}).items():
            for item in items:
                self.codes.setdefault(item["code"], codes.get(item["code"], ""))
                fields = {k: v for k, v in item.items() if k not in ("sev", "code")}
                self.add(item["sev"], item["code"], file, **fields)
        for entry in doc.get("unavailable") or []:
            self.mark_unavailable(entry["check"], entry["reason"])

    def count(self, sev: str) -> int:
        return sum(f["sev"] == sev for items in self.findings.values() for f in items)

    @property
    def status(self) -> str:
        if self.count("block"):
            return FAILED
        return UNAVAILABLE if self.unavailable else PASSED

    def document(self) -> dict[str, Any]:
        doc: dict[str, Any] = {"status": self.status}
        if self.unavailable:
            doc["unavailable"] = list(self.unavailable)
        if self.codes:
            doc["counts"] = Flow(
                (s, self.count(s)) for s in SEVERITIES if self.count(s)
            )
        rank = {s: i for i, s in enumerate(SEVERITIES)}
        findings = {
            file: sorted(self.findings[file], key=lambda f: rank[f["sev"]])
            for file in sorted(self.findings)
        }
        if findings:
            doc["findings"] = findings
            used = dict.fromkeys(
                f["code"] for items in findings.values() for f in items
            )
            doc["codes"] = {code: self.codes[code] for code in used}
        doc.update(self.data)
        return doc

    def emit(self) -> int:
        sys.stdout.write(dump(self.document()))
        return EXIT[self.status]


def usage(text: str) -> int:
    print(text, file=sys.stderr)
    return USAGE


def git(args: list[str]) -> str | None:
    """stdout of a git command, or None when git is missing or the command fails."""
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


_UBUNTU_VERSION = re.compile(
    r"^[ \t]+version:[ \t]*['\"]?([0-9]+\.[0-9]+)", re.MULTILINE
)


def target_base(manifest: str | Path = "chisel.yaml") -> str | None:
    """The branch this checkout's work targets: ubuntu-<version>, the archive
    version read off the manifest. None without a readable manifest, which in
    chisel-releases means a branch with no slices on it."""
    try:
        text = Path(manifest).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _UBUNTU_VERSION.search(text)
    return f"ubuntu-{m.group(1)}" if m else None


def base_ref(base: str) -> str | None:
    """The spelling of `base` this checkout resolves: its remote-tracking ref
    on any remote (origin first), else the local branch. None when nothing
    here can be diffed against."""
    tracking = (
        git(["for-each-ref", "--format=%(refname:short)", f"refs/remotes/*/{base}"])
        or ""
    ).split()
    tracking.sort(key=lambda ref: (not ref.startswith("origin/"), ref))
    for ref in [*tracking, base]:
        if git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]) is not None:
            return ref
    return None


def fetch_hint(base: str) -> str:
    """The fetch that makes base_ref resolve. The explicit refspec matters: a
    checkout whose remote tracks one branch only, as CI checkouts do, would
    otherwise fetch into FETCH_HEAD and leave no ref behind."""
    remotes = (git(["remote"]) or "").split()
    remote = "origin" if "origin" in remotes or not remotes else remotes[0]
    return (
        f"{base} is not fetched; "
        f"git fetch {remote} {base}:refs/remotes/{remote}/{base} brings it"
    )
