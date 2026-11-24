"""draft-rock: init's file filled in from the options, then validated by rockcraft."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "rockcrafter" / "scripts" / "draft-rock.py"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


dr = module(SCRIPT)

# what `rockcraft init` 1.21 writes, trimmed
SIMPLE = """\
name: {name}
# see https://documentation.ubuntu.com/rockcraft/1/explanation/bases/
base: ubuntu@24.04 # the base environment for this rock
version: '0.1' # just for humans. Semantic versioning is recommended
summary: Single-line elevator pitch for your amazing rock # 79 char long summary
description: |
    This is {name}'s description.
platforms: # the platforms this rock should be built on and run on
    amd64:

parts:
    my-part:
        plugin: nil
"""
FLASK = """\
name: {name}
base: bare # as an alternative, an ubuntu base can be used
build-base: ubuntu@24.04 # build-base is required when the base is bare
version: "0.1" # just for humans. Semantic versioning is recommended
summary: A summary of your Flask application # 79 char long summary
description: |
  This is {name}'s description.
platforms:
  amd64:
extensions:
  - flask-framework
"""
PLUGINS = {"nil", "go", "rust"}

NOBLE = dr.rl.Release("24.04", "noble", True, True)
HELLO = {
    "Package": "hello",
    "Version": "2.10-3build2",
    "Description": "example package based on GNU hello\n The GNU hello program.\n .\n It greets.",
}
SLICES = {
    "hello": ["hello_bins", "hello_copyright"],
    "figlet": ["figlet_copyright", "figlet_fonts", "figlet_data"],
}


def expand_extensions() -> subprocess.CompletedProcess:
    """`rockcraft expand-extensions` on ./rockcraft.yaml, cut down to two of
    rockcraft's own rules."""
    doc = yaml.safe_load(Path("rockcraft.yaml").read_text())
    parts = (doc.get("parts") or {}).values()
    problems = [f"- plugin not registered: {p['plugin']!r}" for p in parts if p.get("plugin") not in PLUGINS]
    if doc.get("extensions") and "run-user" in doc:
        problems.append("- extra inputs are not permitted (in field 'run_user')")
    if problems:
        return subprocess.CompletedProcess([], 1, "", "Bad rockcraft.yaml content:\n" + "\n".join(problems) + "\n")
    return subprocess.CompletedProcess([], 0, "", "")


@pytest.fixture
def offline(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(dr.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(dr.rl, "resolve_release", lambda text: NOBLE)
    monkeypatch.setattr(dr.rl, "slices_of", lambda rel, pkg: SLICES.get(pkg))
    monkeypatch.setattr(
        dr.rl, "package", lambda pkg, rel, arch="amd64", ppa=None: {**HELLO, "Package": pkg} if pkg in SLICES else None
    )
    shipped = tmp_path / "rockcraft.json"
    shipped.write_text("{}")
    monkeypatch.setattr(dr.orientation, "SHIPPED_SCHEMA", shipped)
    monkeypatch.delenv("ROCKCRAFT_SCHEMA_URL", raising=False)
    monkeypatch.setattr(dr, "validate", expand_extensions)

    def init(a, rel, tmp):
        if a.profile not in (None, "simple", "flask-framework"):
            err = "Error: argument --profile: invalid choice\nTry 'rockcraft init -h' for help.\n"
            return subprocess.CompletedProcess([], 1, "", err)
        template = FLASK if a.profile == "flask-framework" else SIMPLE
        (tmp / "rockcraft.yaml").write_text(template.format(name=a.name))
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(dr, "init", init)
    return project


def draft(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["draft-rock.py", *args])
    code = dr.main()
    return code, yaml.safe_load(capsys.readouterr().out)


def rock(path: Path) -> dict:
    return yaml.safe_load((path / "rockcraft.yaml").read_text())


def test_archive_package(offline, monkeypatch, capsys):
    code, doc = draft(monkeypatch, capsys, "--name", "hello", "--package", "hello", "--service", "/usr/bin/hello -g hi")
    assert (code, doc["status"], doc["review"]) == (0, "passed", None)
    assert doc["schema"] == str(dr.orientation.SHIPPED_SCHEMA)
    r = rock(offline)
    assert (r["base"], r["build-base"], r["run-user"], r["version"]) == ("bare", "ubuntu@24.04", "_daemon_", "2.10")
    assert r["summary"] == "example package based on GNU hello"
    assert r["description"] == "The GNU hello program.\nIt greets.\n"
    assert r["parts"] == {"hello": {"plugin": "nil", "stage-packages": ["base-files_base", "hello_bins"]}}
    assert r["services"] == {"hello": {"override": "replace", "startup": "enabled", "command": "/usr/bin/hello -g hi"}}


def test_new_keys_sit_beside_inits(offline, monkeypatch, capsys):
    draft(monkeypatch, capsys, "--name", "hello", "--package", "hello", "--service", "/usr/bin/hello")
    assert list(rock(offline)) == [
        "name", "base", "build-base", "run-user", "version", "summary",
        "description", "platforms", "services", "parts",
    ]  # fmt: skip
    assert "description: |\n" in (offline / "rockcraft.yaml").read_text()


def test_slices_without_bins(offline, monkeypatch, capsys):
    draft(monkeypatch, capsys, "--name", "figlet", "--package", "figlet")
    stage = rock(offline)["parts"]["figlet"]["stage-packages"]
    assert stage == ["base-files_base", "figlet_fonts", "figlet_data"]


def test_ppa(offline, monkeypatch, capsys):
    code, _ = draft(monkeypatch, capsys, "--name", "hello", "--package", "hello", "--ppa", "o/n")
    r = rock(offline)
    assert code == 0
    assert r["base"] == "ubuntu@24.04" and "build-base" not in r
    assert r["package-repositories"] == [{"type": "apt", "ppa": "o/n", "priority": "always"}]
    assert r["parts"]["hello"]["stage-packages"] == ["hello"]


def test_unchiseled(offline, monkeypatch, capsys):
    draft(monkeypatch, capsys, "--name", "hello", "--package", "hello", "--unchiseled")
    r = rock(offline)
    assert (r["base"], r["parts"]["hello"]["stage-packages"]) == ("ubuntu@24.04", ["hello"])


def test_source_build(offline, monkeypatch, capsys):
    code, doc = draft(
        monkeypatch, capsys, "--name", "yq", "--source", "https://github.com/mikefarah/yq", "--plugin", "go",
        "--source-tag", "v4.44.3", "--slice", "base-files_base", "--slice", "ca-certificates_data",
    )  # fmt: skip
    r = rock(offline)
    assert code == 0
    assert r["version"] == "4.44.3"
    assert r["parts"] == {
        "yq": {"plugin": "go", "source": "https://github.com/mikefarah/yq", "source-type": "git", "source-tag": "v4.44.3"},
        "yq-runtime": {"plugin": "nil", "stage-packages": ["base-files_base", "ca-certificates_data"]},
    }
    assert doc["review"] == ["summary, description: still init's placeholders"]


def test_unpinned_source_without_runtime_is_reviewed(offline, monkeypatch, capsys):
    _, doc = draft(monkeypatch, capsys, "--name", "yq", "--source", "https://x.invalid/yq", "--plugin", "go")
    assert {r.split(":")[0] for r in doc["review"]} == {"summary, description", "version", "source", "runtime"}


def test_framework_profile(offline, monkeypatch, capsys):
    code, doc = draft(monkeypatch, capsys, "--name", "app", "--profile", "flask-framework", "--summary", "A Flask app")
    r = rock(offline)
    assert (code, doc["status"]) == (0, "passed")
    assert (r["extensions"], r["summary"]) == (["flask-framework"], "A Flask app")
    assert "parts" not in r and "run-user" not in r  # the extension sets the user


def test_framework_takes_no_parts(offline, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["draft-rock.py", "--name", "app", "--profile", "flask-framework", "--package", "hello"])
    assert dr.main() == 2


def test_rockcraft_rejects_the_draft(offline, monkeypatch, capsys):
    code, doc = draft(monkeypatch, capsys, "--name", "x", "--source", ".", "--plugin", "gox")
    finding = doc["findings"]["rockcraft.yaml"][0]
    assert (code, finding["code"], finding["reason"]) == (1, "rejected", "plugin not registered: 'gox'")
    assert not (offline / "rockcraft.yaml").exists()


def test_a_rejected_draft_puts_the_replaced_file_back(offline, monkeypatch, capsys):
    (offline / "rockcraft.yaml").write_text("name: mine\n")
    code, _ = draft(monkeypatch, capsys, "--name", "x", "--force", "--source", ".", "--plugin", "gox")
    assert code == 1
    assert (offline / "rockcraft.yaml").read_text() == "name: mine\n"


def test_init_failed(offline, monkeypatch, capsys):
    code, doc = draft(monkeypatch, capsys, "--name", "x", "--profile", "nope")
    finding = doc["findings"]["rockcraft.yaml"][0]
    assert (code, finding["code"]) == (1, "init-failed")
    assert finding["reason"].startswith("Error: argument --profile")


def test_package_not_found(offline, monkeypatch, capsys):
    code, doc = draft(monkeypatch, capsys, "--name", "x", "--package", "nope")
    assert (code, list(doc["codes"])) == (1, ["package-not-found"])
    assert not (offline / "rockcraft.yaml").exists()


def test_missing_slices(offline, monkeypatch, capsys):
    monkeypatch.setattr(dr.rl, "slices_of", lambda rel, pkg: None)
    code, doc = draft(monkeypatch, capsys, "--name", "hello", "--package", "hello")
    assert (code, list(doc["codes"])) == (1, ["missing-slices"])


def test_exists_without_force(offline, monkeypatch, capsys):
    (offline / "rockcraft.yaml").write_text("name: mine\n")
    code, doc = draft(monkeypatch, capsys, "--name", "hello")
    assert (code, list(doc["codes"])) == (1, ["exists"])
    assert (offline / "rockcraft.yaml").read_text() == "name: mine\n"
    code, _ = draft(monkeypatch, capsys, "--name", "hello", "--force")
    assert code == 0 and rock(offline)["name"] == "hello"


def test_no_rockcraft_is_unavailable(offline, monkeypatch, capsys):
    monkeypatch.setattr(dr.shutil, "which", lambda cmd: None)
    code, doc = draft(monkeypatch, capsys, "--name", "hello")
    assert (code, doc["status"]) == (3, "unavailable")


def test_archive_unreachable_is_unavailable(offline, monkeypatch, capsys):
    def down(*a, **kw):
        raise dr.rl.Unavailable("archive unreachable")

    monkeypatch.setattr(dr.rl, "package", down)
    code, doc = draft(monkeypatch, capsys, "--name", "hello", "--package", "hello")
    assert (code, doc["status"]) == (3, "unavailable")


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--name", "x", "--source", "."],
        ["--name", "x", "--plugin", "go"],
        ["--name", "x", "--source-tag", "v1"],
        ["--name", "x", "--ppa", "o/n"],
        ["--name", "x", "--bogus"],
    ],
)
def test_usage(offline, monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["draft-rock.py", *args])
    assert dr.main() == 2
    assert "Usage:" in capsys.readouterr().err


@pytest.mark.parametrize(("tag", "want"), [("v4.44.3", "4.44.3"), ("jq-1.7.1", "1.7.1"), ("nightly", "nightly")])
def test_tag_version(tag, want):
    assert dr.tag_version(tag) == want
