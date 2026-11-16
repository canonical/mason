#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""deps-recall: does the slices file keep ground truth's dependencies on other
packages' slices?

the cross-package essentials (`libc6_libs`, not the package's own slices) are
what a cut pulls in: a missing one breaks the rootfs at run time. scored as the
share of ground truth's set the produced file also declares, per target,
averaged. extra deps aren't penalised here -- an extra slice brings its own,
and ground truth is one acceptable answer, not the only one. a target whose
ground truth has none scores 1.0.
"""
from _lib import *


def _ext_deps(doc, pkg: str) -> set[str]:
    out: set[str] = set()

    def add(e):
        for name in e if isinstance(e, (list, dict)) else []:
            if isinstance(name, str) and not name.startswith(f"{pkg}_"):
                out.add(name)

    if isinstance(doc, dict):
        add(doc.get("essential"))
        for _, body in iter_bodies(doc):
            add(body.get("essential"))
    return out


def score() -> float:
    def f(t: str) -> float:
        got, want = produced(t), expected(t)
        if not has_slices(got) or want is None:
            return 0.0
        a, e = _ext_deps(got, t), _ext_deps(want, t)
        return len(a & e) / len(e) if e else 1.0
    return avg(f)


emit(score)
