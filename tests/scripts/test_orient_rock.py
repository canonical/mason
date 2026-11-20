"""orient-rock.py: what the machine and the project offer before a rock is built."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "rockcrafter" / "scripts" / "orient-rock.py"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


orient = module(SCRIPT)
rl = orient.rl

RELEASES = [
    rl.Release("22.04", "jammy", True, True),
    rl.Release("23.10", "mantic", False, False),
    rl.Release("24.04", "noble", True, True),
    rl.Release("25.10", "questing", False, True),
]


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine with every tool, and an empty project directory."""
    monkeypatch.chdir(tmp_path)
    have = {t: orient.common.Flow(present=True, version="1.0") for t in orient.TOOLS}
    monkeypatch.setattr(orient.common, "tools", lambda names: dict(have))
    monkeypatch.setattr(rl, "releases", lambda: RELEASES)
    monkeypatch.setattr(orient.common, "git", lambda args: None)
    return have


def run(monkeypatch, capsys, *args) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["orient-rock.py", *args])
    code = orient.main()
    return code, yaml.safe_load(capsys.readouterr().out)


def test_an_empty_project_on_a_ready_machine(machine, monkeypatch, capsys):
    code, doc = run(monkeypatch, capsys)
    assert code == 0 and doc["status"] == "passed"
    assert doc["tools"]["rockcraft"] == {"present": True, "version": "1.0"}
    assert doc["project"] == {
        "rockcraft.yaml": None,
        "test suite": None,
        "git repository": False,
    }
    assert doc["releases"]["default"] == "24.04"
    assert [r["version"] for r in doc["releases"]["supported"]] == [
        "22.04",
        "24.04",
        "25.10",
    ]


def test_without_rockcraft_is_unavailable(machine, monkeypatch, capsys):
    machine["rockcraft"] = orient.common.Flow(present=False, version=None)
    code, doc = run(monkeypatch, capsys)
    assert code == 3 and doc["status"] == "unavailable"
    assert [u["check"] for u in doc["unavailable"]] == ["rockcraft"]
    # the rest of the report still stands
    assert doc["releases"]["default"] == "24.04"


def test_another_missing_tool_does_not_block(machine, monkeypatch, capsys):
    machine["docker"] = orient.common.Flow(present=False, version=None)
    code, doc = run(monkeypatch, capsys)
    assert code == 0 and doc["tools"]["docker"]["present"] is False


def test_an_existing_rock_is_reported(machine, tmp_path, monkeypatch, capsys):
    (tmp_path / "rockcraft.yaml").write_text(
        'name: hello\nversion: "2.10"\nbase: bare\nbuild-base: ubuntu@24.04\n'
        "parts: {hello: {plugin: nil}}\n"
    )
    (tmp_path / "rockcraft-test.yaml").write_text("backends: {}\n")
    monkeypatch.setattr(orient.common, "git", lambda args: "true\n")
    _, doc = run(monkeypatch, capsys)
    assert doc["project"] == {
        "rockcraft.yaml": {
            "name": "hello",
            "version": "2.10",
            "base": "bare",
            "build-base": "ubuntu@24.04",
        },
        "test suite": "rockcraft-test.yaml",
        "git repository": True,
    }


def test_a_deprecated_suite_is_named(machine, tmp_path, monkeypatch, capsys):
    (tmp_path / "spread.yaml").write_text("project: hello\n")
    _, doc = run(monkeypatch, capsys)
    assert doc["project"]["test suite"] == "spread.yaml"


def test_a_file_that_does_not_parse_is_still_a_rock(
    machine, tmp_path, monkeypatch, capsys
):
    (tmp_path / "rockcraft.yaml").write_text("name: [unclosed\n")
    code, doc = run(monkeypatch, capsys)
    assert code == 0
    assert doc["project"]["rockcraft.yaml"] == "present, does not parse"


def test_unreachable_release_list_is_unavailable(machine, monkeypatch, capsys):
    def down():
        raise rl.Unavailable("Ubuntu release list unreachable")

    monkeypatch.setattr(rl, "releases", down)
    code, doc = run(monkeypatch, capsys)
    assert code == 3
    assert [u["check"] for u in doc["unavailable"]] == ["releases"]
    assert doc["tools"]["rockcraft"]["present"] is True


def test_takes_no_arguments(machine, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["orient-rock.py", "hello"])
    assert orient.main() == 2
    assert "Usage" in capsys.readouterr().err
