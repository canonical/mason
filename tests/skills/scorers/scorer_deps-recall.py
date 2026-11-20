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

a ground-truth dep also counts as kept when the produced deps together ship
all its paths, following essentials across packages (`coreutils_bins` for
`coreutils_cat`, both via coreutils-from-gnu on 26.04). that needs the
providers' slices files, which bin/stage saves in <target>.providers/; without
them only exact names count.
"""
import re

import yaml
from _lib import *


def _paths(dep: str, providers: dict, seen: set[str]) -> set[str]:
    """paths a cut of <pkg>_<slice> installs, as far as the providers show."""
    if dep in seen:
        return set()
    seen.add(dep)
    pkg, _, name = dep.partition("_")
    slices = (providers.get(pkg) or {}).get("slices")
    body = (slices.get(name) if isinstance(slices, dict) else None) or {}
    out = set(body.get("contents") or {})
    for e in body.get("essential") or []:
        if isinstance(e, str):
            out |= _paths(e, providers, seen)
    return out


def _glob(p: str) -> re.Pattern:
    rx = re.escape(p).replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.compile(rx + "$")


def _kept(dep: str, got: set[str], have: set[str], pats: list[re.Pattern], providers: dict) -> bool:
    if dep in got:
        return True
    need = _paths(dep, providers, set())
    return bool(need) and all(n in have or any(r.match(n) for r in pats) for n in need)


def _providers(t: str) -> dict:
    out = {}
    for p in sorted((OUT / f"{t}.providers").glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text())
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            out[p.stem] = doc
    return out


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
        prov = _providers(t)
        have: set[str] = set()
        for d in a:
            have |= _paths(d, prov, set())
        pats = [_glob(h) for h in have if "*" in h or "?" in h]
        return sum(_kept(d, a, have, pats, prov) for d in e) / len(e) if e else 1.0
    return avg(f)


emit(score)
