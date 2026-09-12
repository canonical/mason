"""Archive lookup outcomes must distinguish absence from failed verification."""

from __future__ import annotations

import gzip
import importlib.util
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "_shared/deb-list.py"
OTHER_INDEX = gzip.compress(b"Package: other\nFilename: pool/other.deb\n\n")
FOUND_INDEX = gzip.compress(b"Package: foo\nFilename: pool/foo.deb\n\n")


@pytest.fixture
def deb_list(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("deb_list", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chisel.yaml").write_text("archives:\n  ubuntu:\n    suites: [noble]\n")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "foo", "amd64"])
    monkeypatch.setattr(module.shutil, "which", lambda tool: f"/bin/{tool}")
    return module


def test_absence_requires_successful_indexes(deb_list, monkeypatch, capsys):
    monkeypatch.setattr(deb_list, "_fetch", lambda url: OTHER_INDEX)
    assert deb_list.cli() == 1
    error = capsys.readouterr().err
    assert "absent from checked public indexes" in error
    assert "Ubuntu Pro archives were not checked" in error


def test_partial_lookup_does_not_establish_absence(deb_list, monkeypatch, capsys):
    def fetch(url):
        if "noble-updates/main/" in url:
            raise deb_list.ArchiveError("connection timed out")
        return OTHER_INDEX

    monkeypatch.setattr(deb_list, "_fetch", fetch)
    assert deb_list.cli() == 2
    error = capsys.readouterr().err
    assert "package absence not established" in error
    assert "connection timed out" in error


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("offline"),
        urllib.error.HTTPError(
            "http://mirror/Packages.gz",
            403,
            "Forbidden",
            {},
            None,
        ),
    ],
)
def test_fetch_failure_is_verification_error(deb_list, monkeypatch, capsys, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(deb_list.urllib.request, "urlopen", fail)
    assert deb_list.cli() == 2
    assert "package absence not established" in capsys.readouterr().err


@pytest.mark.parametrize(
    "data",
    [
        b"not gzip",
        gzip.compress(b"Package: foo\n\n"),
        gzip.compress(b"<html>mirror error</html>\n"),
        gzip.compress(b"Filename: pool/foo.deb\n\n"),
    ],
)
def test_bad_index_is_not_absence(deb_list, monkeypatch, capsys, data):
    monkeypatch.setattr(deb_list, "_fetch", lambda url: data)
    assert deb_list.cli() == 2
    assert "package absence not established" in capsys.readouterr().err


def test_download_failure_is_not_absence(deb_list, monkeypatch, capsys):
    def fetch(url):
        if url.endswith(".deb"):
            raise deb_list.ArchiveError("deb download failed")
        return FOUND_INDEX

    monkeypatch.setattr(deb_list, "_fetch", fetch)
    assert deb_list.cli() == 2
    assert "deb download failed" in capsys.readouterr().err


def test_missing_tools_are_reported_before_lookup(deb_list, monkeypatch, capsys):
    monkeypatch.setattr(deb_list.shutil, "which", lambda tool: None)
    monkeypatch.setattr(
        deb_list, "_fetch", lambda url: pytest.fail("unexpected lookup")
    )
    assert deb_list.cli() == 2
    assert "missing tools: dpkg-deb" in capsys.readouterr().err


def test_file_falls_back_to_bundled_classifier(deb_list, monkeypatch):
    # file(1) is optional: without it the sibling file.py (synced as _file.py)
    # is used, invoked through the running interpreter.
    assert deb_list.file_command() == ["file"]
    monkeypatch.setattr(deb_list.shutil, "which", lambda tool: None if tool == "file" else f"/bin/{tool}")
    cmd = deb_list.file_command()
    assert cmd[0] == deb_list.sys.executable
    assert cmd[1].endswith(("file.py", "_file.py")), cmd


def test_missing_manifest_is_not_absence(deb_list, tmp_path, capsys):
    (tmp_path / "chisel.yaml").unlink()
    assert deb_list.cli() == 2
    assert "could not read the release suite" in capsys.readouterr().err


def test_listing_includes_pre_depends(deb_list, monkeypatch, capsys):
    monkeypatch.setattr(
        deb_list, "_fetch", lambda url: b"deb" if url.endswith(".deb") else FOUND_INDEX
    )
    fields = {"Version": "1.0", "Depends": "libfoo", "Pre-Depends": "libc6"}
    monkeypatch.setattr(deb_list, "deb_field", lambda deb, field: fields[field])
    monkeypatch.setattr(deb_list, "deb_contents", lambda deb: [])
    monkeypatch.setattr(deb_list, "file_descriptions", lambda *args: [])
    monkeypatch.setattr(deb_list, "deb_postinst", lambda *args: None)
    assert deb_list.cli() == 0
    out = capsys.readouterr().out
    assert "Depends: libfoo" in out and "Pre-Depends: libc6" in out


def test_extraction_failure_is_not_absence(deb_list, monkeypatch, capsys):
    monkeypatch.setattr(
        deb_list, "_fetch", lambda url: b"deb" if url.endswith(".deb") else FOUND_INDEX
    )

    def fail(*args):
        raise subprocess.CalledProcessError(2, ["dpkg-deb", "-f"])

    monkeypatch.setattr(deb_list, "deb_field", fail)
    assert deb_list.cli() == 2
    assert "package verification failed" in capsys.readouterr().err
