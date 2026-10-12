"""Archive lookup outcomes must distinguish absence from failed verification."""

from __future__ import annotations

import gzip
import importlib.util
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "_shared/deb-list.py"
OTHER_INDEX = gzip.compress(b"Package: other\nFilename: pool/other.deb\n\n")
FOUND_INDEX = gzip.compress(b"Package: foo\nFilename: pool/foo.deb\n\n")


@pytest.fixture
def deb_list(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("deb_list", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chisel.yaml").write_text("archives:\n  ubuntu:\n    suites: [noble]\n")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "foo", "amd64"])
    monkeypatch.setattr(module.shutil, "which", lambda tool: f"/bin/{tool}")
    return module


def listed(deb_list, capsys) -> tuple[int, dict]:
    code = deb_list.cli()
    return code, yaml.safe_load(capsys.readouterr().out)


def unavailable(deb_list, capsys) -> str:
    code, doc = listed(deb_list, capsys)
    assert (code, doc["status"]) == (3, "unavailable"), doc
    return " ".join(u["reason"] for u in doc["unavailable"])


def test_absence_requires_successful_indexes(deb_list, monkeypatch, capsys):
    monkeypatch.setattr(deb_list, "_fetch", lambda url: OTHER_INDEX)
    code, doc = listed(deb_list, capsys)
    assert (code, doc["status"]) == (1, "failed")
    [absent] = doc["findings"]["foo"]
    assert (absent["code"], absent["arch"], absent["suite"]) == (
        "absent",
        "amd64",
        "noble",
    )
    assert "ubuntu pro archives are not checked" in doc["codes"]["absent"]


def test_partial_lookup_does_not_establish_absence(deb_list, monkeypatch, capsys):
    def fetch(url):
        if "noble-updates/main/" in url:
            raise deb_list.ArchiveError("connection timed out")
        return OTHER_INDEX

    monkeypatch.setattr(deb_list, "_fetch", fetch)
    reason = unavailable(deb_list, capsys)
    assert "package absence not established" in reason
    assert "connection timed out" in reason


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
    assert "package absence not established" in unavailable(deb_list, capsys)


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
    assert "package absence not established" in unavailable(deb_list, capsys)


def test_download_failure_is_not_absence(deb_list, monkeypatch, capsys):
    def fetch(url):
        if url.endswith(".deb"):
            raise deb_list.ArchiveError("deb download failed")
        return FOUND_INDEX

    monkeypatch.setattr(deb_list, "_fetch", fetch)
    assert "deb download failed" in unavailable(deb_list, capsys)


def test_missing_tools_are_reported_before_lookup(deb_list, monkeypatch, capsys):
    monkeypatch.setattr(deb_list.shutil, "which", lambda tool: None)
    monkeypatch.setattr(
        deb_list, "_fetch", lambda url: pytest.fail("unexpected lookup")
    )
    assert "dpkg-deb" in unavailable(deb_list, capsys)


def test_file_falls_back_to_bundled_classifier(deb_list, monkeypatch, tmp_path):
    # file(1) is optional: without it the bundled file.py (synced as _file.py)
    # describes each path instead.
    text = tmp_path / "text"
    text.write_text("plain\n")
    monkeypatch.setattr(deb_list.shutil, "which", lambda tool: None)
    assert deb_list.classify([str(text)]) == ["ASCII text"]


def test_missing_manifest_is_not_absence(deb_list, tmp_path, capsys):
    (tmp_path / "chisel.yaml").unlink()
    assert "could not read the release suite" in unavailable(deb_list, capsys)


def test_listing_includes_pre_depends(deb_list, monkeypatch, capsys):
    monkeypatch.setattr(
        deb_list, "_fetch", lambda url: b"deb" if url.endswith(".deb") else FOUND_INDEX
    )
    fields = {"Version": "1.10", "Depends": "libfoo", "Pre-Depends": "libc6"}
    monkeypatch.setattr(deb_list, "deb_field", lambda deb, field: fields[field])
    monkeypatch.setattr(
        deb_list, "deb_contents", lambda deb: [("/usr/bin/foo", "0755", "root/root")]
    )
    monkeypatch.setattr(deb_list, "file_descriptions", lambda *args: ["ELF 64-bit"])
    monkeypatch.setattr(deb_list, "deb_postinst", lambda *args: "#!/bin/sh\nexit 0\n")
    code, doc = listed(deb_list, capsys)
    assert (code, doc["status"]) == (0, "passed"), doc
    assert (doc["package"], doc["version"], doc["arch"]) == ("foo", "1.10", "amd64")
    assert (doc["depends"], doc["pre-depends"]) == ("libfoo", "libc6")
    assert doc["files"] == [
        {
            "path": "/usr/bin/foo",
            "mode": "0755",
            "owner": "root/root",
            "type": "ELF 64-bit",
        }
    ]
    assert doc["postinst"] == "#!/bin/sh\nexit 0\n"


def test_extraction_failure_is_not_absence(deb_list, monkeypatch, capsys):
    monkeypatch.setattr(
        deb_list, "_fetch", lambda url: b"deb" if url.endswith(".deb") else FOUND_INDEX
    )

    def fail(*args):
        raise subprocess.CalledProcessError(2, ["dpkg-deb", "-f"])

    monkeypatch.setattr(deb_list, "deb_field", fail)
    assert "dpkg-deb" in unavailable(deb_list, capsys)
