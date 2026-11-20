"""pack-rock: failure diagnosis, slice fixes, and the pack flow with a fake rockcraft."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "_shared" / "pack-rock.py"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


pr = module(SCRIPT)

# real rockcraft 1.21 console output, trimmed
SLICE_LOG = """\
Logging execution to '/home/u/.local/state/rockcraft/log/rockcraft-1.log'
Launching managed ubuntu 24.04 instance...
Logging execution to '/tmp/inside-instance.log'
Pulling hello
Building hello
Staging hello
Failed to cut requested chisel slices: base-files_base, hello_binz
Detailed information: :: error: slice hello_binz not found
Full execution log: '/home/u/.local/state/rockcraft/log/rockcraft-1.log'
"""
SCRIPTLET_LOG = """\
Pulling app
\x1b[1mBuilding app\x1b[0m
:: + jq --version
:: /tmp/tmpab12/scriptlet.sh: line 6: jq: command not found
Failed to run the build script for part 'app'.
Full execution log: '/tmp/full.log'
"""
YAML_LOG = """\
Bad rockcraft.yaml content:
- extra inputs are not permitted (in field 'colour')
Full execution log: '/tmp/y.log'
"""


def test_diagnose_missing_slice():
    d = pr.diagnose(SLICE_LOG)
    assert d["category"] == "missing-chisel-slice"
    assert (d["step"], d["part"]) == ("STAGE", "hello")
    assert d["evidence"][0].startswith("Failed to cut requested chisel slices")
    assert d["log"] == "/home/u/.local/state/rockcraft/log/rockcraft-1.log"


def test_diagnose_scriptlet_strips_ansi():
    d = pr.diagnose(SCRIPTLET_LOG)
    assert d["category"] == "override-scriptlet-error"
    assert (d["step"], d["part"]) == ("BUILD", "app")
    assert d["log"] == "/tmp/full.log"


def test_diagnose_invalid_yaml_has_no_step():
    d = pr.diagnose(YAML_LOG)
    assert (d["category"], d["step"], d["part"]) == ("invalid-yaml", None, None)
    # nothing else names what rockcraft rejected
    assert d["evidence"] == ["Bad rockcraft.yaml content:", "- extra inputs are not permitted (in field 'colour')"]


def test_diagnose_invalid_yaml_keeps_every_rejection():
    listed = [f"- problem {i} (in field 'f{i}')" for i in range(8)]
    d = pr.diagnose("\n".join(["Bad rockcraft.yaml content:", *listed, "Full execution log: '/tmp/y.log'"]))
    assert d["evidence"] == ["Bad rockcraft.yaml content:", *listed]


def test_diagnose_other_categories_take_no_bullets():
    d = pr.diagnose("Staging hello\nFailed to organize\n- not a rejection\n")
    assert (d["category"], d["evidence"]) == ("organize-mismatch", ["Failed to organize"])


def test_diagnose_unknown_keeps_tail():
    d = pr.diagnose("\n".join(f"line {i}" for i in range(20)) + "\n")
    assert d["category"] == "unknown"
    assert d["evidence"] == [f"line {i}" for i in range(12, 20)]
    assert d["log"] is None


def test_diagnose_first_log_when_no_full_log():
    d = pr.diagnose("Logging execution to '/a.log'\nLogging execution to '/b.log'\n")
    assert d["log"] == "/a.log"


def test_every_category_has_a_code():
    assert set(pr.TAXONOMY) | {"unknown"} == set(pr.CODES)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("base: ubuntu@24.04\n", "ubuntu-24.04"),
        ("base: bare\nbuild-base: ubuntu@22.04\n", "ubuntu-22.04"),
        ('base: "bare"\nbuild-base: "ubuntu@26.04"\n', "ubuntu-26.04"),
        ("name: x\n", None),
    ],
)
def test_release_of(text, want):
    assert pr.release_of(text) == want


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "rockcraft.yaml").write_text("base: bare\nbuild-base: ubuntu@24.04\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_slice_fixes_closest(project, monkeypatch):
    have = {"hello": ["hello_bins", "hello_copyright"]}
    monkeypatch.setattr(pr.rl, "slices_of", lambda rel, pkg: have.get(pkg))
    evidence = [
        "Detailed information: :: error: slice hello_binz not found",
        'no slice definitions found for: "nope_bins"',
    ]
    report = pr.common.Report(pr.CODES)
    assert pr.slice_fixes(evidence, report) == {
        "hello_binz": "hello_bins",
        "nope_bins": "no slices for nope on ubuntu-24.04",
    }


def test_slice_fixes_package_with_no_slices(project, monkeypatch):
    monkeypatch.setattr(pr.rl, "slices_of", lambda rel, pkg: [])
    report = pr.common.Report(pr.CODES)
    fixes = pr.slice_fixes(["slice hello_binz not found"], report)
    assert fixes == {"hello_binz": "no slices for hello on ubuntu-24.04"}


def test_slice_fixes_unavailable(project, monkeypatch):
    def down(rel, pkg):
        raise pr.rl.Unavailable("chisel-releases unreachable")

    monkeypatch.setattr(pr.rl, "slices_of", down)
    report = pr.common.Report(pr.CODES)
    assert pr.slice_fixes(["slice hello_binz not found"], report) == {}
    assert report.status == "unavailable"


def fake_rockcraft(bindir: Path, output: str, code: int) -> None:
    (bindir / "out.txt").write_text(output)
    exe = bindir / "rockcraft"
    exe.write_text(f'#!/bin/sh\ncat "{bindir}/out.txt"\nexit {code}\n')
    exe.chmod(0o755)


def cli(cwd: Path, path: str):
    env = {**os.environ, "PATH": path}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=cwd, env=env, check=False
    )
    return proc.returncode, yaml.safe_load(proc.stdout) if proc.stdout else None


def test_no_rockcraft_yaml_is_unavailable(tmp_path):
    code, doc = cli(tmp_path, os.environ["PATH"])
    assert (code, doc["status"]) == (3, "unavailable")


def test_no_rockcraft_is_unavailable(tmp_path):
    (tmp_path / "rockcraft.yaml").write_text("name: x\n")
    code, doc = cli(tmp_path, str(tmp_path / "empty"))
    assert (code, doc["status"]) == (3, "unavailable")
    assert "not installed" in str(doc["unavailable"])


def test_failed_pack_is_diagnosed(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_rockcraft(bindir, SCRIPTLET_LOG, 1)
    (tmp_path / "rockcraft.yaml").write_text("name: x\n")
    code, doc = cli(tmp_path, f"{bindir}:{os.environ['PATH']}")
    assert (code, doc["status"]) == (1, "failed")
    finding = doc["findings"]["rockcraft.yaml"][0]
    assert (finding["code"], finding["step"], finding["part"]) == ("override-scriptlet-error", "BUILD", "app")
    assert doc["log"] == "/tmp/full.log"


# a throwaway identity, and none of the user's global config (hooks, signing)
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}  # fmt: skip


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **GIT_ENV})


def test_successful_pack_commits_nothing(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_rockcraft(bindir, "Packed hello_2.12_amd64.rock\n", 0)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "rockcraft.yaml").write_text("name: x\n")
    (proj / "README").write_text("a\n")
    git(proj, "init", "-q")
    git(proj, "add", "rockcraft.yaml", "README")
    git(proj, "commit", "-qm", "init")
    (proj / "rockcraft.yaml").write_text("name: y\n")
    (proj / "README").write_text("b\n")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=proj,
        env={**os.environ, **GIT_ENV, "PATH": f"{bindir}:{os.environ['PATH']}"}, check=False,
    )  # fmt: skip
    doc = yaml.safe_load(proc.stdout)
    assert (proc.returncode, doc["status"]) == (0, "passed")
    assert doc["rock"] == ["hello_2.12_amd64.rock"]
    assert "commit" not in doc

    def out(*args):
        return subprocess.run(["git", *args], cwd=proj, check=True, capture_output=True, text=True).stdout

    # the fix and the unrelated edit are both left for whoever made them
    assert len(out("log", "--oneline").splitlines()) == 1
    assert out("status", "--porcelain").splitlines() == [" M README", " M rockcraft.yaml"]


def test_usage():
    proc = subprocess.run([sys.executable, str(SCRIPT), "x"], capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "Usage: pack-rock.py" in proc.stderr
