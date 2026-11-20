"""orientation.py: one report of the ground every skill works on.

The network is stubbed: the three release sources (Ubuntu's meta-release, the
chisel-releases remote, rockcraft's published schema) are replaced on the
module. Run:

    uv run --with pyyaml --with pytest pytest tests/scripts/
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

SHARED = Path(__file__).resolve().parents[2] / "shared"
TODAY = "2040-01-01"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


orientation = module(SHARED / "orientation.py")
Flow = orientation.common.Flow
Failed = orientation.Failed

LIVE = "format: v3\nmaintenance:\n  end-of-life: 2999-01-01\n"
DEAD = "format: v1\nmaintenance:\n  end-of-life: 2001-01-01\n"
DATELESS = "format: chisel-v1\n"
UBUNTU = {
    "36.04": Flow(codename="lts-old", lts=True, supported=True),
    "38.04": Flow(codename="lts-new", lts=True, supported=True),
    "38.10": Flow(codename="interim", lts=False, supported=True),
    "30.04": Flow(codename="ancient", lts=True, supported=False),
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """An empty directory on a machine with every tool, and three sources that
    answer. A test changes what it needs to on the returned dict."""
    monkeypatch.chdir(tmp_path)
    w = {
        "ubuntu": dict(UBUNTU),
        "branches": {"ubuntu-36.04": LIVE, "ubuntu-38.04": LIVE},
        "rockcraft": "1.0.0",
        "bases": {
            "36.04": Flow(base=True, **{"build-base": True}),
            "38.04": Flow(base=True, **{"build-base": True}),
            "38.10": Flow(base=True, **{"build-base": True}),
        },
    }

    def answer(value):
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(orientation, "ubuntu_releases", lambda: answer(w["ubuntu"]))
    monkeypatch.setattr(
        orientation,
        "remote_branches",
        lambda url: {b: b for b in answer(w["branches"])},
    )
    monkeypatch.setattr(
        orientation, "branch_manifest", lambda url, rev: answer(w["branches"][rev])
    )
    monkeypatch.setattr(orientation, "rockcraft_version", lambda: answer(w["rockcraft"]))
    monkeypatch.setattr(orientation, "rockcraft_bases", lambda v: answer(w["bases"]))
    monkeypatch.setattr(
        orientation.common,
        "tools",
        lambda names: {t: Flow(present=True, version="1.0") for t in names},
    )
    return w


def report(monkeypatch, capsys, *args) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["orientation.py", *args])
    code = orientation.main()
    return code, yaml.safe_load(capsys.readouterr().out)


def checks(doc: dict) -> list[str]:
    return [u["check"] for u in doc.get("unavailable", [])]


# --- contexts ----------------------------------------------------------------


def test_an_empty_directory_has_no_context_and_passes(world, monkeypatch, capsys):
    code, doc = report(monkeypatch, capsys)
    assert (code, doc["status"]) == (0, "passed")
    assert "chisel-releases" not in doc and "rock" not in doc
    assert doc["git"] == {"repository": False}
    assert set(doc["tools"]) == set(orientation.TOOLS)


def test_a_checkout_reports_under_its_own_key(world, tmp_path, monkeypatch, capsys):
    (tmp_path / "chisel.yaml").write_text(
        "format: v3\narchives:\n  ubuntu:\n    version: 38.04\n"
        "    suites: [a, b]\n    components: [main]\n"
        "maintenance:\n  end-of-life: 2999-01-01\n"
    )
    (tmp_path / "slices").mkdir()
    (tmp_path / "slices" / "foo.yaml").write_text("package: foo\n")
    code, doc = report(monkeypatch, capsys)
    assert code == 0 and "rock" not in doc
    assert doc["chisel-releases"] == {
        "target base": "ubuntu-38.04",
        "base ref": None,
        "ubuntu version": "38.04",
        "manifest format": "v3",
        "suites": ["a", "b"],
        "components": ["main"],
        "end-of-life": "2999-01-01",
        "maintained": True,
        "existing slices": 1,
    }
    assert "manifest format" not in doc


def test_a_rock_reports_under_its_own_key(world, tmp_path, monkeypatch, capsys):
    (tmp_path / "rockcraft.yaml").write_text(
        'name: hello\nversion: "2.10"\nbase: bare\nbuild-base: ubuntu@38.04\n'
        "parts: {hello: {plugin: nil}}\n"
    )
    (tmp_path / "spread.yaml").write_text("project: hello\n")
    (tmp_path / "rockcraft-test.yaml").write_text("backends: {}\n")
    code, doc = report(monkeypatch, capsys)
    assert code == 0 and "chisel-releases" not in doc
    assert doc["rock"] == {
        "name": "hello",
        "version": "2.10",
        "base": "bare",
        "build-base": "ubuntu@38.04",
        "test suites": ["rockcraft-test.yaml", "spread.yaml"],
    }


def test_both_contexts_can_be_present(world, tmp_path, monkeypatch, capsys):
    (tmp_path / "chisel.yaml").write_text("format: v3\n")
    (tmp_path / "rockcraft.yaml").write_text("name: hello\n")
    _, doc = report(monkeypatch, capsys)
    assert doc["chisel-releases"]["manifest format"] == "v3"
    assert doc["rock"] == {"name": "hello", "test suites": []}


def test_a_rock_that_does_not_parse_is_still_a_rock(
    world, tmp_path, monkeypatch, capsys
):
    (tmp_path / "rockcraft.yaml").write_text("name: [unclosed\n")
    code, doc = report(monkeypatch, capsys)
    assert code == 0
    assert doc["rock"] == {"parses": False, "test suites": []}


def test_a_directory_by_that_name_is_not_the_context(
    world, tmp_path, monkeypatch, capsys
):
    (tmp_path / "rockcraft.yaml").mkdir()
    (tmp_path / "chisel.yaml").mkdir()
    code, doc = report(monkeypatch, capsys)
    assert code == 0
    assert "rock" not in doc and "chisel-releases" not in doc


def test_an_unreadable_context_is_unknown_and_the_other_still_reads(
    world, tmp_path, monkeypatch, capsys
):
    (tmp_path / "chisel.yaml").write_text("format: v3\n")
    (tmp_path / "rockcraft.yaml").write_text("name: hello\n")
    real = Path.read_text

    def denied(self, *args, **kwargs):
        if self.name == "chisel.yaml":
            raise PermissionError("access denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    code, doc = report(monkeypatch, capsys)
    assert code == 3 and checks(doc) == ["chisel-releases"]
    assert "access denied" in doc["unavailable"][0]["reason"]
    # present but unknown, which an absent key would not say
    assert doc["chisel-releases"] is None
    assert doc["rock"]["name"] == "hello"


def test_slices_that_cannot_be_listed_are_not_zero(
    world, tmp_path, monkeypatch, capsys
):
    (tmp_path / "chisel.yaml").write_text("format: v3\n")

    def denied(path):
        raise PermissionError("access denied")

    monkeypatch.setattr(orientation.os, "listdir", denied)
    code, doc = report(monkeypatch, capsys)
    assert code == 3 and checks(doc) == ["chisel-releases"]
    assert doc["chisel-releases"]["existing slices"] is None
    assert doc["chisel-releases"]["manifest format"] == "v3"


def test_missing_maintenance_is_unknown(world, tmp_path, monkeypatch, capsys):
    (tmp_path / "chisel.yaml").write_text("format: v3\n")
    _, doc = report(monkeypatch, capsys)
    assert doc["chisel-releases"]["maintained"] is None


# --- git ---------------------------------------------------------------------


def repo(path, branch="ubuntu-38.04"):
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
    return run


def test_a_repository_names_its_branch(world, tmp_path, monkeypatch, capsys):
    repo(tmp_path)
    _, doc = report(monkeypatch, capsys)
    # an unborn branch still has a name
    assert doc["git"] == {"repository": True, "branch": "ubuntu-38.04"}


def test_the_target_base_and_a_detached_head(world, tmp_path, monkeypatch, capsys):
    run = repo(tmp_path)
    (tmp_path / "chisel.yaml").write_text(
        "format: v3\narchives:\n  ubuntu:\n    version: 38.04\n"
    )
    run("add", "chisel.yaml")
    run("commit", "-q", "-m", "manifest")
    run("checkout", "-q", "--detach")
    code, doc = report(monkeypatch, capsys)
    assert code == 0
    assert doc["git"] == {"repository": True, "branch": None}
    assert doc["chisel-releases"]["target base"] == "ubuntu-38.04"
    assert doc["chisel-releases"]["base ref"] == "ubuntu-38.04"

    run("branch", "-D", "ubuntu-38.04")
    code, doc = report(monkeypatch, capsys)
    # a fact to act on, not a failure of orientation: check-diff says what to fetch
    assert code == 0 and doc["chisel-releases"]["base ref"] is None


def test_without_git_the_repository_is_unknown(world, monkeypatch, capsys):
    monkeypatch.undo()  # the real remote listing, which needs git
    real = orientation.shutil.which
    monkeypatch.setattr(
        orientation.shutil, "which", lambda t: None if t == "git" else real(t)
    )
    monkeypatch.setattr(orientation, "ubuntu_releases", lambda: dict(UBUNTU))
    monkeypatch.setattr(orientation, "rockcraft_version", lambda: None)
    code, doc = report(monkeypatch, capsys)
    assert doc["git"] == {"repository": None}
    # the missing tool is a fact; what could not be asked without it is not
    assert code == 3 and checks(doc) == ["release discovery"]
    assert "git is not installed" in doc["unavailable"][0]["reason"]


def test_a_git_query_that_cannot_run_is_unavailable(world, monkeypatch, capsys):
    def hangs(cmd, timeout=0):
        raise Failed("git rev-parse: timed out")

    monkeypatch.setattr(orientation, "run", hangs)
    code, doc = report(monkeypatch, capsys)
    assert code == 3 and checks(doc) == ["git"]
    assert doc["git"] == {"repository": None}


# --- releases ----------------------------------------------------------------


def test_each_release_shows_what_each_source_says(world, monkeypatch, capsys):
    code, doc = report(monkeypatch, capsys)
    assert code == 0
    assert list(doc["releases"]) == ["36.04", "38.04", "38.10"]
    assert doc["releases"]["38.04"] == {
        "ubuntu": {"codename": "lts-new", "lts": True, "supported": True},
        "chisel-releases": {
            "branch": "ubuntu-38.04",
            "format": "v3",
            "end-of-life": "2999-01-01",
            "maintained": True,
        },
        "rockcraft": {"base": True, "build-base": True},
    }
    # rockcraft takes it and Ubuntu supports it, but it has no branch
    assert list(doc["releases"]["38.10"]) == ["ubuntu", "rockcraft"]


def test_the_default_rock_base_is_the_newest_lts_rockcraft_takes(
    world, monkeypatch, capsys
):
    _, doc = report(monkeypatch, capsys)
    assert doc["default rock base"] == "ubuntu@38.04"

    # an LTS that rockcraft does not take yet is not the default
    del world["bases"]["38.04"]
    _, doc = report(monkeypatch, capsys)
    assert doc["default rock base"] == "ubuntu@36.04"


def test_without_rockcraft_there_is_no_rockcraft_column(world, monkeypatch, capsys):
    world["rockcraft"] = None
    code, doc = report(monkeypatch, capsys)
    assert (code, doc["status"]) == (0, "passed")
    assert all("rockcraft" not in row for row in doc["releases"].values())
    assert doc["default rock base"] is None


def test_a_rockcraft_without_a_published_schema_is_unavailable(
    world, monkeypatch, capsys
):
    world["bases"] = Failed("rockcraft 9.9: HTTP Error 404: Not Found")
    code, doc = report(monkeypatch, capsys)
    assert code == 3 and checks(doc) == ["rockcraft bases"]
    assert doc["default rock base"] is None
    assert doc["releases"]["38.04"]["chisel-releases"]["maintained"] is True


def test_an_unreachable_ubuntu_list_costs_only_its_column(world, monkeypatch, capsys):
    world["ubuntu"] = Failed("changelogs.ubuntu.com: timed out")
    code, doc = report(monkeypatch, capsys)
    assert code == 3 and checks(doc) == ["ubuntu releases"]
    assert list(doc["releases"]["38.04"]) == ["chisel-releases", "rockcraft"]
    assert doc["default rock base"] is None


def test_a_remote_that_cannot_be_listed_costs_only_its_column(
    world, monkeypatch, capsys
):
    world["branches"] = Failed("github.com: 403")
    code, doc = report(monkeypatch, capsys)
    assert code == 3 and checks(doc) == ["release discovery"]
    assert list(doc["releases"]["38.04"]) == ["ubuntu", "rockcraft"]
    assert doc["default rock base"] == "ubuntu@38.04"


def test_a_manifest_that_cannot_be_read_leaves_the_branch_listed(
    world, monkeypatch, capsys
):
    world["branches"]["ubuntu-38.10"] = Failed("HTTP Error 403: Forbidden")
    code, doc = report(monkeypatch, capsys)
    assert code == 3 and checks(doc) == ["release discovery"]
    assert "ubuntu-38.10" in doc["unavailable"][0]["reason"]
    assert doc["releases"]["38.10"]["chisel-releases"] == {
        "branch": "ubuntu-38.10",
        "format": None,
        "end-of-life": None,
        "maintained": None,
    }
    assert doc["releases"]["38.04"]["chisel-releases"]["maintained"] is True


def test_no_branches_at_all_is_a_passing_answer(world, monkeypatch, capsys):
    world["branches"] = {}
    code, doc = report(monkeypatch, capsys)
    assert code == 0
    assert all("chisel-releases" not in row for row in doc["releases"].values())


def test_an_end_of_life_branch_is_listed_as_unmaintained(world, monkeypatch, capsys):
    world["branches"]["ubuntu-30.04"] = DEAD
    code, doc = report(monkeypatch, capsys)
    assert code == 0
    assert doc["releases"]["30.04"]["chisel-releases"]["maintained"] is False
    assert doc["releases"]["30.04"]["ubuntu"]["supported"] is False


def test_a_dateless_interim_past_its_window_is_unmaintained():
    # interims get 9 months of support, so an old one that records no
    # end-of-life is past it
    facts = orientation.branch_facts("ubuntu-22.10", DATELESS, TODAY)
    assert facts == {
        "branch": "ubuntu-22.10",
        "format": "v1",
        "end-of-life": None,
        "maintained": False,
    }


@pytest.mark.parametrize("branch", ["ubuntu-38.04", "ubuntu-39.10"])
def test_a_dateless_branch_that_could_be_live_is_unknown(branch):
    # an LTS, or an interim still inside its support window
    facts = orientation.branch_facts(branch, DATELESS, TODAY)
    assert facts["maintained"] is None


def test_a_source_past_the_deadline_is_unavailable_and_the_rest_stands(
    world, monkeypatch, capsys
):
    def slow(url, rev):
        if rev == "ubuntu-38.04":
            time.sleep(1.0)
        return LIVE

    monkeypatch.setattr(orientation, "branch_manifest", slow)
    monkeypatch.setattr(orientation, "DEADLINE", 0.2)
    code, doc = report(monkeypatch, capsys)
    assert code == 3 and checks(doc) == ["release discovery"]
    assert "ubuntu-38.04: not read before the deadline" in str(doc["unavailable"])
    assert doc["releases"]["36.04"]["chisel-releases"]["maintained"] is True
    assert doc["releases"]["38.04"]["chisel-releases"]["maintained"] is None


# --- the sources themselves ---------------------------------------------------


def test_rockcraft_bases_are_read_at_the_installed_version(monkeypatch):
    asked = []
    schema = {
        "properties": {
            "base": {"enum": ["bare", "ubuntu@36.04", "ubuntu@38.04"]},
            "build-base": {
                "anyOf": [{"enum": ["ubuntu@38.04", "devel"]}, {"type": "null"}]
            },
        }
    }

    def fetch(url):
        asked.append(url)
        return json.dumps(schema)

    monkeypatch.setattr(orientation, "fetch", fetch)
    assert orientation.rockcraft_bases("1.2.3") == {
        "36.04": {"base": True},
        "38.04": {"base": True, "build-base": True},
    }
    assert asked == [
        "https://raw.githubusercontent.com/canonical/rockcraft/1.2.3/schema/rockcraft.json"
    ]


def test_a_schema_of_another_shape_is_a_failed_read(monkeypatch):
    monkeypatch.setattr(orientation, "fetch", lambda url: '{"properties": {}}')
    with pytest.raises(Failed):
        orientation.rockcraft_bases("1.2.3")


def test_the_rockcraft_version_is_taken_whole(monkeypatch):
    done = subprocess.CompletedProcess([], 0, "rockcraft 1.12.0.post3+g1a2b3c\n", "")
    monkeypatch.setattr(orientation.shutil, "which", lambda t: "/snap/bin/" + t)
    monkeypatch.setattr(orientation, "run", lambda cmd, timeout=0: done)
    # a build between two releases has no tag to read: it must not be rounded
    # down to the release before it
    assert orientation.rockcraft_version() == "1.12.0.post3+g1a2b3c"


def test_a_rockcraft_that_fails_to_state_its_version_is_a_failed_read(monkeypatch):
    done = subprocess.CompletedProcess([], 1, "Traceback in rockcraft 1.2.3\n", "")
    monkeypatch.setattr(orientation.shutil, "which", lambda t: "/snap/bin/" + t)
    monkeypatch.setattr(orientation, "run", lambda cmd, timeout=0: done)
    # whatever it printed, a command that failed has not stated its version
    with pytest.raises(Failed, match=r"failed \(exit 1\)"):
        orientation.rockcraft_version()


def test_the_ubuntu_list_marks_the_release_in_development(monkeypatch):
    stable = "Dist: new\nVersion: 38.04 LTS\nSupported: 1\n"
    devel = stable + "\nDist: next\nVersion: 38.10\nSupported: 0\n"
    monkeypatch.setattr(
        orientation,
        "fetch",
        lambda url: devel if url.endswith("-development") else stable,
    )
    assert orientation.ubuntu_releases() == {
        "38.04": {"codename": "new", "lts": True, "supported": True},
        "38.10": {
            "codename": "next",
            "lts": False,
            "supported": False,
            "development": True,
        },
    }


def test_takes_no_arguments(world, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["orientation.py", "--rock"])
    assert orientation.main() == 2
    assert "Usage" in capsys.readouterr().err
