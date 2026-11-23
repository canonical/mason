"""rocklib: release resolution, Packages parsing, versions, slices."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "rockcrafter" / "scripts"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = result  # dataclasses look their module up
    spec.loader.exec_module(result)
    return result


rl = module(SCRIPTS / "rocklib.py")

RELEASES = [
    rl.Release("22.04", "jammy", True, True),
    rl.Release("24.04", "noble", True, True),
    rl.Release("25.10", "questing", False, True),
    rl.Release("26.04", "resolute", True, True),
    rl.Release("20.04", "focal", True, False),
]


@pytest.fixture
def known(monkeypatch):
    monkeypatch.setattr(rl, "_meta_release", lambda: list(RELEASES))


def test_releases_sorted_by_version(known):
    assert [r.version for r in rl.releases()] == ["20.04", "22.04", "24.04", "25.10", "26.04"]


def test_release_properties():
    r = rl.Release("24.04", "noble", True, True)
    assert (r.branch, r.base) == ("ubuntu-24.04", "ubuntu@24.04")


@pytest.mark.parametrize(
    "text", ["noble", "NOBLE", "24.04", "ubuntu-24.04", "ubuntu@24.04", "ubuntu:24.04", "ubuntu/24.04"]
)
def test_resolve_release_forms(known, text):
    assert rl.resolve_release(text).codename == "noble"


def test_resolve_release_default_is_newest_supported_lts(known):
    assert rl.resolve_release(None).version == "26.04"
    assert rl.resolve_release("").version == "26.04"


def test_resolve_release_unknown(known):
    with pytest.raises(ValueError, match="unknown Ubuntu release"):
        rl.resolve_release("99.04")


def test_resolve_release_unreachable(monkeypatch):
    monkeypatch.setattr(rl, "_meta_release", list)
    with pytest.raises(rl.Unavailable):
        rl.resolve_release("noble")


def test_meta_release_parses(monkeypatch):
    stable = b"Dist: noble\nVersion: 24.04.3 LTS\nSupported: 1\n\nDist: oracular\nVersion: 24.10\nSupported: 0\n"
    dev = b"Dist: resolute\nVersion: 26.04 LTS\nSupported: 0\n"
    monkeypatch.setattr(rl, "cached", lambda url, **kw: dev if "development" in url else stable)
    assert rl._meta_release() == [
        rl.Release("24.04", "noble", True, True),
        rl.Release("24.10", "oracular", False, False),
        rl.Release("26.04", "resolute", True, True),
    ]


PACKAGES = b"""Package: aaa
Version: 1.0-1
Filename: pool/a/aaa.deb

Package: hello
Version: 2.10-3build2
Depends: libc6 (>= 2.34), foo:any | bar
Description: hi
 continued line
Filename: pool/h/hello.deb

Package: hello-doc
Version: 2.10-3
"""


def test_stanza_finds_package():
    st = rl._stanza(PACKAGES, "hello")
    assert st["Version"] == "2.10-3build2"
    assert st["Description"] == "hi\n continued line"


def test_stanza_first_and_missing():
    assert rl._stanza(PACKAGES, "aaa")["Version"] == "1.0-1"
    assert rl._stanza(PACKAGES, "hell") is None
    assert rl._stanza(PACKAGES, "zzz") is None


def test_deps_first_alternative_without_constraints():
    assert rl.deps(rl._stanza(PACKAGES, "hello")) == ["libc6", "foo"]
    assert rl.deps({}) == []


@pytest.mark.parametrize(
    ("debver", "short", "full"),
    [
        ("2:1.24.0-2ubuntu7", "1.24", "1.24.0"),
        ("2.10-3build2", "2.10", "2.10"),
        ("3.12.3-0ubuntu2", "3.12", "3.12.3"),
        ("20240101+ds-1", "20240101", "20240101"),
    ],
)
def test_upstream_version(debver, short, full):
    assert rl.upstream_version(debver) == short
    assert rl.upstream_version(debver, full=True) == full


def test_deb_binaries_without_dpkg_deb_is_unavailable(monkeypatch):
    monkeypatch.setattr(rl.shutil, "which", lambda name: None)
    monkeypatch.setattr(rl, "fetch", lambda url: pytest.fail("fetched a .deb it cannot read"))
    with pytest.raises(rl.Unavailable, match="dpkg-deb"):
        rl.deb_binaries({"Package": "hello", "_url": "http://archive/hello.deb"})


def test_slice_names():
    sdf = """package: hello
essential:
  - hello_copyright
slices:
  bins:
    essential:
      - libc6_libs
    contents:
      /usr/bin/hello:
  copyright: # license
    contents:
      /usr/share/doc/hello/copyright:
v3-essential:
  nope:
"""
    assert rl.slice_names(sdf) == ["bins", "copyright"]
    assert rl.slice_names("package: x\n") == []


def test_has_branch_reads_the_manifest(monkeypatch):
    asked = []

    def cached(url, **kw):
        asked.append(url)
        return b"format: v1\n" if "ubuntu-24.04" in url else None

    monkeypatch.setattr(rl, "cached", cached)
    monkeypatch.setattr(rl, "fetch_failed", lambda url: False)
    assert rl.has_branch("ubuntu-24.04") is True
    # a 404 on the manifest is the branch not being there
    assert rl.has_branch("ubuntu-26.10") is False
    assert asked[0].endswith("/chisel-releases/ubuntu-24.04/chisel.yaml")


def test_has_branch_unreachable_is_not_absence(monkeypatch):
    monkeypatch.setattr(rl, "cached", lambda url, **kw: None)
    monkeypatch.setattr(rl, "fetch_failed", lambda url: True)
    with pytest.raises(rl.Unavailable):
        rl.has_branch("ubuntu-24.04")
