"""Unavailable evidence must not produce a successful verification verdict."""

from __future__ import annotations

import importlib.util
import os
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
    # a helper imports its common module from its own directory
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
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

    def verdict() -> tuple[int, dict]:
        code = review.main(["--base", "base"])
        return code, yaml.safe_load(capsys.readouterr().out)

    code, doc = verdict()
    assert (code, doc["status"], doc["verdict"]) == (0, "passed", "approve"), doc

    (tmp_path / "foo.yaml").write_text(SDF.replace("package: foo", "package: bar"))
    code, doc = verdict()
    assert (code, doc["status"], doc["verdict"]) == (1, "failed", "request-changes")
    assert "package-mismatch" in {f["code"] for f in doc["findings"]["foo.yaml"]}

    (tmp_path / "foo.yaml").write_text(SDF)
    base.write_text("bad: [yaml")
    code, doc = verdict()
    assert (code, doc["status"], doc["verdict"]) == (3, "unavailable", "incomplete")


def test_review_missing_base_is_incomplete(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REVIEW), "--base", "missing"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    doc = yaml.safe_load(result.stdout)
    assert result.returncode == 3
    assert (doc["status"], doc["verdict"]) == ("unavailable", "incomplete")


@pytest.mark.parametrize("kind", ["missing", "crash-after-warning"])
def test_checker_crash_is_unavailable(tmp_path, monkeypatch, kind):
    review = module(REVIEW)
    monkeypatch.setattr(review, "HERE", tmp_path)
    if kind == "crash-after-warning":
        (tmp_path / "checker.py").write_text(
            'print("status: passed")\nraise RuntimeError("broken")\n'
        )
    doc = review.run_check("checker.py")
    assert doc["status"] == "unavailable"
    assert doc["unavailable"][0]["check"] == "checker.py"


def test_unknown_format_is_unavailable(tmp_path):
    sdf = tmp_path / "foo.yaml"
    sdf.write_text(SDF)
    result = subprocess.run(
        [sys.executable, str(SHARED / "check-slice.py"), str(sdf)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    doc = yaml.safe_load(result.stdout)
    assert result.returncode == 3
    assert doc["status"] == "unavailable"
    assert [u["check"] for u in doc["unavailable"]] == ["format"]


def test_diff_unreadable_base_is_unavailable(tmp_path):
    old, new = tmp_path / "old.yaml", tmp_path / "new.yaml"
    old.write_text("bad: [yaml")
    new.write_text(SDF)
    result = subprocess.run(
        [sys.executable, str(SHARED / "check-diff.py"), str(old), str(new)],
        capture_output=True,
        text=True,
        check=False,
    )
    doc = yaml.safe_load(result.stdout)
    assert result.returncode == 3
    assert doc["status"] == "unavailable"
    assert [u["check"] for u in doc["unavailable"]] == ["base"]


def test_inaccessible_sdf_is_unavailable(monkeypatch, tmp_path):
    checker = module(SHARED / "check-test.py")

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_text", denied)
    report = checker.check(tmp_path / "foo.yaml", None)
    assert report.status == "unavailable"
    assert not report.findings


def cut(tmp_path, *args, chisel=None):
    """try-cut run from a scratch release dir, with PATH holding only a fake chisel."""
    bin_dir, release = tmp_path / "bin", tmp_path / "release"
    bin_dir.mkdir()
    release.mkdir()
    if chisel is not None:
        fake = bin_dir / "chisel"
        fake.write_text(f"#!{sys.executable}\n{chisel}")
        fake.chmod(0o755)
    result = subprocess.run(
        [sys.executable, str(SHARED / "try-cut.py"), *args],
        cwd=release,
        env={**os.environ, "PATH": str(bin_dir)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert not list(release.iterdir()), "the temp root is left behind"
    return result.returncode, yaml.safe_load(result.stdout), result.stderr


FAKE_CHISEL = """\
import pathlib, sys
args = sys.argv[1:]
if "--help" in args:
    print("--ignore=<what>  ignore release checks")
    sys.exit(0)
sys.stderr.write("fetching things...\\n")
{body}
"""


def test_cut_without_chisel_is_unavailable(tmp_path):
    code, doc, _ = cut(tmp_path, "foo_bins")
    assert code == 3
    assert doc["status"] == "unavailable"
    assert doc["unavailable"][0]["check"] == "cut"


def test_cut_reports_what_it_installed(tmp_path):
    body = (
        'root = pathlib.Path(args[args.index("--root") + 1])\n'
        '(root / "usr/bin").mkdir(parents=True)\n'
        '(root / "usr/bin/foo").write_text("x")\n'
        'print(" ".join(args))\n'
    )
    code, doc, err = cut(
        tmp_path, "--arch", "arm64", "foo_bins", chisel=FAKE_CHISEL.format(body=body)
    )
    assert code == 0, err
    assert doc["status"] == "passed"
    assert (doc["arch"], doc["slices"], doc["files"]) == ("arm64", ["foo_bins"], 1)
    # chisel's own output goes to stderr, stdout is the report
    assert "fetching things" in err and "--ignore=unstable" in err


@pytest.mark.parametrize(
    ("error", "status"),
    [
        ("slice foo_bins has conflicting paths", "failed"),
        (
            "cannot talk to archive: dial tcp: lookup archive.ubuntu.com: no such host",
            "unavailable",
        ),
        (
            "main/binary-amd64/Packages is missing from stonking main component digests",
            "unavailable",
        ),
    ],
)
def test_cut_failure_is_classified(tmp_path, error, status):
    body = f'sys.stderr.write("error: {error}\\n")\nsys.exit(1)\n'
    code, doc, err = cut(tmp_path, "foo_bins", chisel=FAKE_CHISEL.format(body=body))
    assert (code, doc["status"]) == ({"failed": 1, "unavailable": 3}[status], status), (
        err
    )
    if status == "failed":
        [finding] = doc["findings"]["foo_bins"]
        reason = finding["error"]
    else:
        reason = doc["unavailable"][0]["reason"]
    assert error in reason


def test_cut_usage_error(tmp_path):
    code, doc, err = cut(tmp_path)
    assert code == 2 and doc is None and "usage" in err


def discover(monkeypatch, branches, today="2040-01-01"):
    """orientation's release discovery over fake branches: name -> chisel.yaml,
    or an exception to raise when that branch's manifest is read."""
    orientation = module(SHARED / "orientation.py")
    refs = "".join(
        f"{n}{i}\trefs/heads/{b}\n"
        for i, (b, n) in enumerate(zip(branches, "abcdefgh"))
    )
    monkeypatch.setattr(
        orientation.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, refs, ""),
    )
    by_rev = {
        f"{n}{i}": v for i, (n, v) in enumerate(zip("abcdefgh", branches.values()))
    }

    def manifest(url, revision):
        value = by_rev[revision]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(orientation, "branch_manifest", manifest)
    report = module(SHARED / "common.py").Report({})
    orientation.live_releases(today, report)
    return report.document()


LIVE = "format: v3\nmaintenance:\n  end-of-life: 2999-01-01\n"


def test_partial_release_discovery_reports_access_refusal(monkeypatch):
    doc = discover(
        monkeypatch,
        {
            "ubuntu-40.04": LIVE,
            "ubuntu-40.10": urllib.error.HTTPError("u", 403, "Forbidden", {}, None),
        },
    )
    assert "ubuntu-40.04" in doc["live releases"]
    assert doc["status"] == "unavailable"
    [problem] = doc["unavailable"]
    assert problem["check"] == "release discovery" and "403" in problem["reason"]


def test_successful_empty_discovery_is_distinct(monkeypatch):
    doc = discover(monkeypatch, {})
    assert doc["status"] == "passed"
    assert doc["live releases"] == {}


def test_missing_maintenance_is_unknown(tmp_path, monkeypatch):
    orientation = module(SHARED / "orientation.py")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chisel.yaml").write_text("format: v3\n")
    report = module(SHARED / "common.py").Report({})
    orientation.checkout("2040-01-01", report)
    assert report.data["maintained"] is None


def test_checkout_access_refusal_is_not_missing_checkout(tmp_path, monkeypatch):
    orientation = module(SHARED / "orientation.py")
    monkeypatch.chdir(tmp_path)

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_text", denied)
    report = module(SHARED / "common.py").Report({})
    orientation.checkout("2040-01-01", report)
    [problem] = report.unavailable
    assert problem["check"] == "checkout" and "access denied" in problem["reason"]
    assert "branch" not in report.data


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
    report = checker.check(sdf, None)
    assert report.status == "unavailable"
    assert not report.findings


@pytest.mark.parametrize(
    "args",
    [
        ["check-slice.py", "missing.yaml", "--format", "3"],
        ["check-diff.py", "missing.yaml", "also-missing.yaml"],
    ],
)
def test_missing_input_is_unavailable_not_a_defect(tmp_path, args):
    # an input that cannot be read says nothing about the SDF under review
    result = subprocess.run(
        [sys.executable, str(SHARED / args[0]), *args[1:]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    doc = yaml.safe_load(result.stdout)
    assert (result.returncode, doc["status"]) == (3, "unavailable"), result.stdout
    assert "findings" not in doc
