"""Unavailable evidence must not produce a successful verification verdict."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "_shared"
REVIEW = ROOT / "skills/chisel-slice-reviewer/scripts/review-diff.py"
SDF = """\
package: foo
essential:
  - foo_copyright
slices:
  bins:
    contents:
      /usr/bin/foo:
  copyright:
    contents:
      /usr/share/doc/foo/copyright:
"""


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_review_runs_installed_checkers(tmp_path, monkeypatch, capsys):
    review = module(REVIEW)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chisel.yaml").write_text("format: v1\n")
    (tmp_path / "foo.yaml").write_text(SDF)
    task = tmp_path / "tests/spread/integration/foo/task.yaml"
    task.parent.mkdir(parents=True)
    task.write_text('summary: foo test\nexecute: chroot "$rootfs" foo --version\n')
    monkeypatch.setattr(review, "changed_slices", lambda base: ["foo.yaml"])
    original = review.run_check

    base = tmp_path / "base.yaml"
    base.write_text(SDF)

    def run_check(script, *args):
        if script == "_check-diff.py":
            return original(script, "base.yaml", "foo.yaml")
        return original(script, *args)

    monkeypatch.setattr(review, "run_check", run_check)
    assert review.main(["--base", "base"]) == 0
    assert "verdict: approve" in capsys.readouterr().out

    (tmp_path / "foo.yaml").write_text(SDF.replace("package: foo", "package: bar"))
    assert review.main(["--base", "base"]) == 1
    assert "verdict: request-changes" in capsys.readouterr().out

    (tmp_path / "foo.yaml").write_text(SDF)
    base.write_text("bad: [yaml")
    assert review.main(["--base", "base"]) == 2
    assert "verdict: incomplete" in capsys.readouterr().out


def test_review_missing_base_is_incomplete(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REVIEW), "--base", "missing"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unavailable" in result.stdout
    assert "verdict: incomplete" in result.stdout


@pytest.mark.parametrize("kind", ["missing", "crash-after-warning"])
def test_checker_crash_is_unavailable(tmp_path, monkeypatch, kind):
    review = module(REVIEW)
    monkeypatch.setattr(review, "HERE", tmp_path)
    if kind == "crash-after-warning":
        (tmp_path / "checker.py").write_text(
            'print("warn  example: existing finding")\nraise RuntimeError("broken")\n'
        )
    findings = review.run_check("checker.py")
    assert any(line.startswith("unavailable") for line in findings)


def test_unknown_format_blocks(tmp_path):
    sdf = tmp_path / "foo.yaml"
    sdf.write_text(SDF)
    result = subprocess.run(
        [sys.executable, str(SHARED / "check-slice.py"), str(sdf)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "block" in result.stdout
    assert "ok:" not in result.stdout


def test_diff_unreadable_base_is_an_error(tmp_path):
    old, new = tmp_path / "old.yaml", tmp_path / "new.yaml"
    old.write_text("bad: [yaml")
    new.write_text(SDF)
    result = subprocess.run(
        [sys.executable, str(SHARED / "check-diff.py"), str(old), str(new)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "error:" in result.stderr
    assert "ok:" not in result.stdout


def test_inaccessible_sdf_is_unavailable(monkeypatch, tmp_path):
    checker = module(SHARED / "check-test.py")

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_text", denied)
    rows = checker.check(tmp_path / "foo.yaml", None)
    assert rows[0][0] == "unavailable"


def test_cut_without_chisel_does_not_pass(tmp_path):
    result = subprocess.run(
        [shutil.which("bash"), str(SHARED / "try-cut"), "foo_bins"],
        env={**os.environ, "PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unavailable" in result.stderr
    assert not list(tmp_path.iterdir())


def test_partial_release_discovery_reports_access_refusal(monkeypatch):
    orientation = module(SHARED / "orientation.py")
    monkeypatch.setattr(
        orientation.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a, 0, "aaa\trefs/heads/ubuntu-40.04\nbbb\trefs/heads/ubuntu-40.10\n", ""
        ),
    )

    def manifest(url, revision):
        if revision == "bbb":
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return "format: v3\nmaintenance:\n  end-of-life: 2999-01-01\n"

    monkeypatch.setattr(orientation, "branch_manifest", manifest)
    lines, unavailable = orientation.live_releases("2040-01-01")
    doc = yaml.safe_load("\n".join(lines))
    assert unavailable
    assert "ubuntu-40.04" in doc["live releases"]
    assert doc["release discovery"]["status"] == "unavailable"
    assert "403" in doc["release discovery"]["reasons"][0]


def test_successful_empty_discovery_is_distinct(monkeypatch):
    orientation = module(SHARED / "orientation.py")
    monkeypatch.setattr(
        orientation.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""),
    )
    lines, unavailable = orientation.live_releases("2040-01-01")
    doc = yaml.safe_load("\n".join(lines))
    assert not unavailable
    assert doc["live releases"] == {}
    assert doc["release discovery"]["status"] == "passed"


def test_missing_maintenance_is_unknown(tmp_path, monkeypatch):
    orientation = module(SHARED / "orientation.py")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chisel.yaml").write_text("format: v3\n")
    doc = yaml.safe_load("\n".join(orientation.checkout("2040-01-01")))
    assert doc["maintained"] is None


def test_checkout_access_refusal_is_not_missing_checkout(tmp_path, monkeypatch):
    orientation = module(SHARED / "orientation.py")
    monkeypatch.chdir(tmp_path)

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_text", denied)
    doc = yaml.safe_load("\n".join(orientation.checkout("2040-01-01")))
    assert doc["checkout error"] == "access denied"
    assert "release" not in doc


def test_inaccessible_task_is_not_a_test_defect(tmp_path, monkeypatch):
    checker = module(SHARED / "check-test.py")
    sdf = tmp_path / "foo.yaml"
    sdf.write_text(SDF)
    monkeypatch.chdir(tmp_path)
    task = tmp_path / "tests/spread/integration/foo/task.yaml"
    task.parent.mkdir(parents=True)
    task.write_text("summary: foo\nexecute: foo\n")

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(checker, "task_sources", denied)
    rows = checker.check(sdf, None)
    assert rows[0][0] == "unavailable"
