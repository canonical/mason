"""rock-packages.py: what the archive and chisel-releases know about a rock's
packages. Offline: the archive, the PPA and chisel-releases are stubbed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "rock-create" / "scripts" / "rock-packages.py"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rp = module(SCRIPT)
rl = rp.rl

NOBLE = rl.Release("24.04", "noble", True, True)
HELLO = {
    "Package": "hello",
    "Version": "2.10-3build2",
    "Description": "example package based on GNU hello\n The GNU hello program.\n .\n It greets.",
    "Depends": "libc6 (>= 2.34)",
    "Filename": "pool/h/hello.deb",
    "_url": "http://archive/pool/h/hello.deb",
}
PYTHON = {
    "Package": "python3",
    "Version": "3.12.3-0ubuntu2",
    "Description": "interactive high-level object-oriented language",
    "Depends": "python3.12 (>= 3.12.3-0~), libpython3-stdlib (= 3.12.3-0ubuntu2)",
    "Filename": "pool/p/python3.deb",
    "_url": "http://archive/pool/p/python3.deb",
}
ARCHIVE = {"hello": HELLO, "python3": PYTHON}
SLICES = {"hello": ["hello_bins", "hello_copyright"]}


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asked = {"slices": []}

    def slices_of(ref, pkg):
        asked["slices"].append((ref, pkg))
        return SLICES.get(pkg)

    monkeypatch.setattr(rl, "resolve_release", lambda text: NOBLE)
    monkeypatch.setattr(rl, "slices_of", slices_of)
    monkeypatch.setattr(
        rl, "package", lambda pkg, rel, arch="amd64", ppa=None: ARCHIVE.get(pkg)
    )
    monkeypatch.setattr(rl, "deb_binaries", lambda st: ["/usr/bin/" + st["Package"]])
    return asked


def run(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["rock-packages.py", *args])
    code = rp.main()
    return code, yaml.safe_load(capsys.readouterr().out)


def test_an_archive_package_with_slices(offline, monkeypatch, capsys):
    code, doc = run(monkeypatch, capsys, "hello", "--release", "24.04")
    assert (code, doc["status"]) == (0, "passed")
    assert doc["release"] == {
        "version": "24.04",
        "codename": "noble",
        "base": "ubuntu@24.04",
        "slices from": "ubuntu-24.04",
    }
    assert doc["packages"]["hello"] == {
        "version": "2.10-3build2",
        "upstream version": "2.10",
        "summary": "example package based on GNU hello",
        "description": "The GNU hello program.\nIt greets.",
        "binaries": ["/usr/bin/hello"],
        "depends": ["libc6"],
        "slices": ["hello_bins", "hello_copyright"],
    }


def test_it_writes_nothing(offline, tmp_path, monkeypatch, capsys):
    run(monkeypatch, capsys, "hello", "--release", "24.04")
    assert list(tmp_path.iterdir()) == []


def test_a_metapackage_names_what_is_behind_it(offline, monkeypatch, capsys):
    _, doc = run(monkeypatch, capsys, "python3", "--release", "24.04")
    assert doc["packages"]["python3"]["depends"] == ["python3.12", "libpython3-stdlib"]


def test_missing_slices_block_and_the_rest_is_still_reported(
    offline, monkeypatch, capsys
):
    code, doc = run(monkeypatch, capsys, "hello", "python3", "--release", "24.04")
    assert (code, doc["status"]) == (1, "failed")
    assert list(doc["codes"]) == ["missing-slices"]
    assert list(doc["findings"]) == ["python3"]
    assert doc["packages"]["python3"]["slices"] is None
    assert doc["packages"]["hello"]["slices"] == ["hello_bins", "hello_copyright"]


def test_package_not_found(offline, monkeypatch, capsys):
    code, doc = run(monkeypatch, capsys, "nope", "hello", "--release", "24.04")
    assert (code, doc["status"]) == (1, "failed")
    assert list(doc["codes"]) == ["package-not-found"]
    assert list(doc["packages"]) == ["hello"]


def test_a_ppa_package_has_no_slices_to_look_for(offline, monkeypatch, capsys):
    code, doc = run(monkeypatch, capsys, "hello", "--ppa", "o/n", "--release", "24.04")
    assert (code, doc["status"]) == (0, "passed")
    assert doc["ppa"] == "o/n"
    assert "slices" not in doc["packages"]["hello"]
    assert "slices from" not in doc["release"]
    assert offline["slices"] == []


def test_slices_can_come_from_a_checkout(offline, monkeypatch, capsys):
    _, doc = run(
        monkeypatch, capsys, "hello", "--release", "24.04", "--chisel-release", "../cr"
    )
    assert doc["release"]["slices from"] == "../cr"
    assert offline["slices"] == [("../cr", "hello")]


def test_binaries_need_dpkg_deb(offline, monkeypatch, capsys):
    def no_dpkg(st):
        raise rl.Unavailable("dpkg-deb is not installed")

    monkeypatch.setattr(rl, "deb_binaries", no_dpkg)
    code, doc = run(monkeypatch, capsys, "hello", "python3", "--release", "24.04")
    # the defect found stays found, and the reason is given once
    assert code == 1
    assert [u["check"] for u in doc["unavailable"]] == ["binaries"]
    assert doc["packages"]["hello"]["binaries"] is None
    assert doc["packages"]["hello"]["slices"] == ["hello_bins", "hello_copyright"]


def test_unreachable_archive_is_unavailable(offline, monkeypatch, capsys):
    def down(*a, **kw):
        raise rl.Unavailable("package index unreachable")

    monkeypatch.setattr(rl, "package", down)
    code, doc = run(monkeypatch, capsys, "hello", "--release", "24.04")
    assert (code, doc["status"]) == (3, "unavailable")
    assert [u["check"] for u in doc["unavailable"]] == ["discovery"]


def test_unknown_release_is_a_usage_error(offline, monkeypatch, capsys):
    def unknown(text):
        raise ValueError(f"unknown Ubuntu release {text!r}")

    monkeypatch.setattr(rl, "resolve_release", unknown)
    monkeypatch.setattr(sys, "argv", ["rock-packages.py", "hello", "--release", "9.99"])
    assert rp.main() == 2
    assert "unknown Ubuntu release" in capsys.readouterr().err


@pytest.mark.parametrize("args", [[], ["--release", "24.04"], ["hello", "--nope"]])
def test_usage(offline, monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["rock-packages.py", *args])
    assert rp.main() == 2
    assert "Usage:" in capsys.readouterr().err
