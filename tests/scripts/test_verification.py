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


def test_missing_base_is_unavailable(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SHARED / "check-diff.py"), "--base=missing"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    doc = yaml.safe_load(result.stdout)
    assert (result.returncode, doc["status"]) == (3, "unavailable")
    assert [u["check"] for u in doc["unavailable"]] == ["base"]


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


def test_expired_interim_without_end_of_life_is_not_live(monkeypatch):
    # interims get 9 months of support, so an old one with no maintenance
    # section is past it -- nothing about the live list is left unknown
    doc = discover(monkeypatch, {"ubuntu-40.04": LIVE, "ubuntu-22.10": "format: v1\n"})
    assert doc["status"] == "passed", doc
    assert list(doc["live releases"]) == ["ubuntu-40.04"]


@pytest.mark.parametrize("branch", ["ubuntu-38.04", "ubuntu-39.10"])
def test_unknown_end_of_life_is_unavailable(monkeypatch, branch):
    # an LTS, or an interim still inside its support window, could be live
    doc = discover(monkeypatch, {"ubuntu-40.04": LIVE, branch: "format: v3\n"})
    assert doc["status"] == "unavailable", doc
    assert branch in doc["unavailable"][0]["reason"]


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


MANIFEST = "format: v3\narchives:\n  ubuntu:\n    version: 26.04\n"


def release_checkout(path, branch="ubuntu-26.04"):
    """A chisel-releases-like repo: the manifest committed on `branch`, the
    worktree detached on a commit that adds slices/foo.yaml."""
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "HOME": str(path),
        "PATH": os.environ["PATH"],
    }

    def run(*args):
        subprocess.run(
            ["git", *args], cwd=path, env=env, check=True, capture_output=True
        )

    run("init", "-q", "-b", branch)
    (path / "chisel.yaml").write_text(MANIFEST)
    run("add", "chisel.yaml")
    run("commit", "-q", "-m", "manifest")
    run("checkout", "-q", "--detach")
    (path / "slices").mkdir()
    (path / "slices/foo.yaml").write_text(SDF)
    run("add", "slices/foo.yaml")
    run("commit", "-q", "-m", "foo")
    return run


def check_diff(cwd, *args):
    result = subprocess.run(
        [sys.executable, str(SHARED / "check-diff.py"), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, yaml.safe_load(result.stdout)


def test_diff_derives_the_base_from_the_manifest(tmp_path):
    release_checkout(tmp_path)
    code, doc = check_diff(tmp_path)
    assert (code, doc["status"]) == (0, "passed"), doc
    assert doc["base"] == "ubuntu-26.04"
    assert doc["changed"] == ["slices/foo.yaml"]


def test_diff_prefers_the_remote_tracking_base(tmp_path):
    run = release_checkout(tmp_path)
    run("update-ref", "refs/remotes/origin/ubuntu-26.04", "ubuntu-26.04")
    _, doc = check_diff(tmp_path)
    assert doc["base"] == "origin/ubuntu-26.04", doc


def test_diff_unfetched_base_is_unavailable(tmp_path):
    run = release_checkout(tmp_path)
    run("branch", "-D", "ubuntu-26.04")
    code, doc = check_diff(tmp_path)
    assert (code, doc["status"]) == (3, "unavailable")
    [problem] = doc["unavailable"]
    assert problem["check"] == "base"
    assert (
        "git fetch origin ubuntu-26.04:refs/remotes/origin/ubuntu-26.04"
        in problem["reason"]
    )
    assert "base" not in doc


def test_diff_without_manifest_needs_an_explicit_base(tmp_path):
    code, doc = check_diff(tmp_path)
    assert (code, doc["status"]) == (3, "unavailable")
    assert "--base" in doc["unavailable"][0]["reason"]


def test_diff_compares_at_the_merge_base(tmp_path):
    # the base moved on after branching: its new SDF is not this change's removal
    run = release_checkout(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    run("checkout", "-q", "ubuntu-26.04")
    (tmp_path / "slices").mkdir(exist_ok=True)
    (tmp_path / "slices/bar.yaml").write_text(SDF.replace("foo", "bar"))
    run("add", "slices/bar.yaml")
    run("commit", "-q", "-m", "bar on the base")
    run("checkout", "-q", "--detach", head)
    code, doc = check_diff(tmp_path)
    assert (code, doc["status"]) == (0, "passed"), doc
    assert doc["changed"] == ["slices/foo.yaml"]
    assert doc["merge base"] and "caveat" not in doc
    assert "findings" not in doc


def test_diff_without_a_merge_base_compares_the_tip(tmp_path):
    run = release_checkout(tmp_path)
    run("checkout", "-q", "--orphan", "rootless")
    run("commit", "-q", "-m", "unrelated history")
    code, doc = check_diff(tmp_path)
    assert (code, doc["status"]) == (0, "passed"), doc
    assert doc["merge base"] is None
    assert "tip of ubuntu-26.04" in doc["caveat"]


def test_diff_explicit_base_wins(tmp_path):
    run = release_checkout(tmp_path)
    run("branch", "other", "ubuntu-26.04")
    _, doc = check_diff(tmp_path, "--base=other")
    assert doc["base"] == "other"


def test_orientation_reports_the_target_base(tmp_path, monkeypatch):
    orientation = module(SHARED / "orientation.py")
    run = release_checkout(tmp_path)
    monkeypatch.chdir(tmp_path)
    report = module(SHARED / "common.py").Report({})
    orientation.checkout("2040-01-01", report)
    assert (report.data["target base"], report.data["base ref"]) == (
        "ubuntu-26.04",
        "ubuntu-26.04",
    )
    assert report.data["branch"] is None
    assert not report.unavailable

    run("branch", "-D", "ubuntu-26.04")
    report = module(SHARED / "common.py").Report({})
    orientation.checkout("2040-01-01", report)
    # a fact to act on, not a failure of orientation: check-diff says what to fetch
    assert report.data["base ref"] is None
    assert not report.unavailable
