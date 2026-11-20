"""draft-rock: the yaml emitter, source discovery, and offline drafts that check-rock accepts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "rock-crafter" / "scripts" / "draft-rock.py"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


dr = module(SCRIPT)
cr = module(ROOT / "_shared" / "check-rock.py")

NOBLE = dr.rl.Release("24.04", "noble", True, True)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("GNU Hello. It prints a greeting.", "GNU Hello"),
        ("one two three four", "one two"),
    ],
)
def test_short(text, want):
    assert dr.short(text, limit=12 if "four" in text else 78) == want


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("plain", "plain"),
        ("2.12", '"2.12"'),
        ("yes", '"yes"'),
        ("", '""'),
        ("a: b", '"a: b"'),
        ("_daemon_", "_daemon_"),
        ("*glob", '"*glob"'),
        (True, "true"),
    ],
)
def test_scalar(value, want):
    assert dr._scalar(value) == want


def test_emit_round_trips():
    doc = {
        "name": "hello",
        "version": "2.12",
        "description": "line one\nline two\n",
        "platforms": {"amd64": {}},
        "parts": {
            "b": {"plugin": "nil", "after": ["a"], "stage-packages": ["hello_bins"]},
        },
        "package-repositories": [{"type": "apt", "ppa": "o/n"}],
    }
    assert yaml.safe_load("\n".join(dr.emit(doc)) + "\n") == {**doc, "platforms": {"amd64": None}}


@pytest.mark.parametrize(
    ("tag", "want"), [("v1.24.3", "1.24.3"), ("release-2.0", "2.0"), ("nightly", "nightly")]
)
def test_tag_version(tag, want):
    assert dr.tag_version(tag) == want


def test_latest_tag_skips_prereleases(monkeypatch):
    out = "\n".join(
        f"abc\trefs/tags/{t}" for t in ["v1.9.0", "v1.10.0", "v1.11.0-rc1", "v2.0.0-beta", "docs", "v1.10.1"]
    )

    class R:
        stdout = out

    monkeypatch.setattr(dr.subprocess, "run", lambda *a, **kw: R)
    assert dr.latest_tag("https://example.invalid/x.git") == "v1.10.1"


def test_is_source(tmp_path):
    assert dr.is_source("https://github.com/mikefarah/yq")
    assert dr.is_source("git@github.com:o/r.git")
    assert dr.is_source(str(tmp_path))
    assert not dr.is_source("hello")


def tree(tmp_path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return tmp_path


@pytest.mark.parametrize(
    ("files", "local", "want"),
    [
        ({"go.mod": "module x\n"}, False, ("plugin", "go")),
        ({"Cargo.toml": ""}, False, ("plugin", "rust")),
        ({"pyproject.toml": "", "uv.lock": ""}, False, ("plugin", "uv")),
        ({"requirements.txt": "flask\n"}, False, ("plugin", "python")),
        ({"requirements.txt": "flask\n"}, True, ("extension", "flask-framework")),
        ({"requirements.txt": "Django>=5\n"}, True, ("extension", "django-framework")),
        ({"package.json": '{"dependencies": {"express": "4"}}'}, True, ("extension", "expressjs-framework")),
        ({"CMakeLists.txt": ""}, False, ("plugin", "cmake")),
        ({"Makefile": ""}, False, ("plugin", "make")),
        ({"README": ""}, False, ("plugin", "nil")),
    ],
)
def test_detect(tmp_path, files, local, want):
    assert dr.detect(tree(tmp_path, files), local) == want


def test_meta_go(tmp_path):
    m = dr.meta(tree(tmp_path, {
        "go.mod": "module github.com/mikefarah/yq/v4\n\ngo 1.22\n",
        "LICENSE": "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\n",
        "README.md": "# yq\n\na lightweight and portable command-line YAML processor\n",
    }))  # fmt: skip
    assert (m["name"], m["go"], m["bins"]) == ("yq", "1.22", ["yq"])
    assert m["license_file"] == "MIT"
    assert m["description"] == "a lightweight and portable command-line YAML processor"


def test_meta_python(tmp_path):
    m = dr.meta(tree(tmp_path, {
        "pyproject.toml": '[project]\nname = "tool"\ndescription = "does things"\n'
        'license = {text = "Apache-2.0"}\n\n[project.scripts]\ntool = "tool:main"\n',
    }))  # fmt: skip
    assert (m["name"], m["description"], m["license"], m["bins"]) == ("tool", "does things", "Apache-2.0", ["tool"])


def test_meta_npm(tmp_path):
    pj = {"name": "srv", "description": "a server", "license": "MIT", "bin": {"srv": "x.js"}, "engines": {"node": ">=20.1"}}
    m = dr.meta(tree(tmp_path, {"package.json": json.dumps(pj)}))
    assert (m["name"], m["license"], m["bins"], m["node"]) == ("srv", "MIT", ["srv"], "20.1")


def test_meta_npm_legacy_licence_object(tmp_path):
    pj = {"name": "srv", "license": {"type": "MIT", "url": "https://x"}}
    assert dr.meta(tree(tmp_path, {"package.json": json.dumps(pj)}))["license"] == "MIT"


def test_licence_must_be_one_rockcraft_knows(monkeypatch):
    monkeypatch.setattr(dr, "REVIEW", [])
    assert (dr.licence("MIT"), dr.licence("proprietary")) == ("MIT", "proprietary")
    assert dr.REVIEW == []
    assert (dr.licence("BSD"), dr.licence(None)) == (None, None)
    assert ["'BSD'" in dr.REVIEW[0], "not detected" in dr.REVIEW[1]] == [True, True]


# --- whole drafts, offline -------------------------------------------------------

HELLO = {
    "Package": "hello",
    "Version": "2.10-3build2",
    "Description": "example package based on GNU hello\n The GNU hello program.\n .\n It greets.",
    "Depends": "libc6 (>= 2.34)",
    "Filename": "pool/h/hello.deb",
    "_url": "http://archive/pool/h/hello.deb",
}
SLICES = {"hello": ["hello_bins", "hello_copyright"], "base-files": ["base-files_base"]}


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dr, "REVIEW", [])
    for rl in (dr.rl, cr.rl):
        monkeypatch.setattr(rl, "resolve_release", lambda text: NOBLE)
        monkeypatch.setattr(rl, "slices_of", lambda rel, pkg: SLICES.get(pkg))
    monkeypatch.setattr(dr.rl, "package", lambda pkg, rel, arch="amd64", ppa=None: HELLO if pkg == "hello" else None)
    monkeypatch.setattr(dr.rl, "deb_facts", lambda st: (["/usr/bin/hello"], "GPL-3.0"))
    return tmp_path


def draft(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["draft-rock.py", *args])
    code = dr.main()
    return code, yaml.safe_load(capsys.readouterr().out)


def check_codes(path: Path) -> list[str]:
    report = cr.common.Report(cr.CODES)
    cr.check(yaml.safe_load(path.read_text()), str(path), report)
    return [f["code"] for items in report.findings.values() for f in items]


def test_archive_draft_passes_check(offline, monkeypatch, capsys):
    code, doc = draft(monkeypatch, capsys, "hello", "--release", "24.04", "--service", "/usr/bin/hello -g hi")
    assert (code, doc["status"]) == (0, "passed")
    rock = yaml.safe_load((offline / "rockcraft.yaml").read_text())
    assert rock["version"] == "2.10"
    assert (rock["base"], rock["build-base"], rock["run-user"]) == ("bare", "ubuntu@24.04", "_daemon_")
    assert rock["parts"]["hello"]["stage-packages"] == ["base-files_base", "hello_bins"]
    assert rock["services"]["hello"]["command"] == "/usr/bin/hello -g hi"
    assert check_codes(offline / "rockcraft.yaml") == []


def test_unknown_licence_drafts_the_placeholder(offline, monkeypatch, capsys):
    monkeypatch.setattr(dr.rl, "deb_facts", lambda st: (["/usr/bin/hello"], "BSD"))
    code, doc = draft(monkeypatch, capsys, "hello", "--release", "24.04")
    assert (code, doc["license"]) == (0, None)
    assert any("'BSD'" in note for note in doc["review"])
    # the one thing a fresh draft does not pass check-rock on
    assert check_codes(offline / "rockcraft.yaml") == ["license-unknown"]


def test_source_dot_is_named_after_its_directory(offline, monkeypatch, capsys):
    proj = offline / "my-tool"
    proj.mkdir()
    (proj / "Makefile").write_text("all:\n")
    monkeypatch.chdir(proj)
    code, _ = draft(monkeypatch, capsys, ".", "--release", "24.04", "--version", "1.0")
    assert code == 0
    assert yaml.safe_load((proj / "rockcraft.yaml").read_text())["name"] == "my-tool"


def test_ppa_draft_is_unchiselled(offline, monkeypatch, capsys):
    code, _ = draft(monkeypatch, capsys, "hello", "--ppa", "o/n", "--release", "24.04")
    assert code == 0
    rock = yaml.safe_load((offline / "rockcraft.yaml").read_text())
    assert rock["base"] == "ubuntu@24.04"
    assert rock["package-repositories"][0]["ppa"] == "o/n"
    assert rock["parts"]["hello"]["stage-packages"] == ["hello"]
    assert check_codes(offline / "rockcraft.yaml") == []


def test_package_not_found(offline, monkeypatch, capsys):
    code, doc = draft(monkeypatch, capsys, "nope", "--release", "24.04")
    assert (code, doc["status"]) == (1, "failed")
    assert "package-not-found" in doc["codes"]
    assert not (offline / "rockcraft.yaml").exists()


def test_missing_slices(offline, monkeypatch, capsys):
    monkeypatch.setattr(dr.rl, "slices_of", lambda rel, pkg: None)
    code, doc = draft(monkeypatch, capsys, "hello", "--release", "24.04")
    assert (code, list(doc["codes"])) == (1, ["missing-slices"])


def test_exists_without_force(offline, monkeypatch, capsys):
    (offline / "rockcraft.yaml").write_text("name: mine\n")
    code, doc = draft(monkeypatch, capsys, "hello", "--release", "24.04")
    assert (code, list(doc["codes"])) == (1, ["exists"])
    assert (offline / "rockcraft.yaml").read_text() == "name: mine\n"


def test_unavailable(offline, monkeypatch, capsys):
    def down(*a, **kw):
        raise dr.rl.Unavailable("archive unreachable")

    monkeypatch.setattr(dr.rl, "package", down)
    code, doc = draft(monkeypatch, capsys, "hello", "--release", "24.04")
    assert (code, doc["status"]) == (3, "unavailable")


def test_usage(offline, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["draft-rock.py"])
    assert dr.main() == 2
    assert "Usage:" in capsys.readouterr().err
