"""The output contract every helper shares, as implemented by _shared/common.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

SHARED = Path(__file__).resolve().parents[2] / "_shared"
CODES = {"removed": "gone from a published slice", "moved": "still installed"}


@pytest.fixture
def common():
    spec = importlib.util.spec_from_file_location("common", SHARED / "common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def emitted(report, capsys) -> tuple[int, str, dict]:
    code = report.emit()
    out = capsys.readouterr().out
    return code, out, yaml.safe_load(out)


def test_no_findings_passes(common, capsys) -> None:
    code, _, doc = emitted(common.Report(CODES), capsys)
    assert code == 0
    assert doc == {"status": "passed", "counts": {}}


def test_warnings_pass_and_are_counted(common, capsys) -> None:
    report = common.Report(CODES)
    report.add("warn", "removed", "foo.yaml", slice="bins", path="/usr/bin/foo")
    report.add(
        "info", "moved", "foo.yaml", slice="bins", path="/usr/bin/bar", to="foo_bar"
    )
    code, _, doc = emitted(report, capsys)
    assert code == 0
    assert doc["status"] == "passed"
    assert doc["counts"] == {"warn": 1, "info": 1}
    assert doc["findings"] == {
        "foo.yaml": [
            {"sev": "warn", "code": "removed", "slice": "bins", "path": "/usr/bin/foo"},
            {
                "sev": "info",
                "code": "moved",
                "slice": "bins",
                "path": "/usr/bin/bar",
                "to": "foo_bar",
            },
        ]
    }
    assert doc["codes"] == CODES


def test_block_fails(common, capsys) -> None:
    report = common.Report(CODES)
    report.add("block", "removed", "foo.yaml")
    code, _, doc = emitted(report, capsys)
    assert (code, doc["status"]) == (1, "failed")


def test_unavailable_exits_3(common, capsys) -> None:
    report = common.Report(CODES)
    report.add("warn", "removed", "foo.yaml")
    report.mark_unavailable("cut", "chisel not installed")
    code, _, doc = emitted(report, capsys)
    assert (code, doc["status"]) == (3, "unavailable")
    assert doc["unavailable"] == [{"check": "cut", "reason": "chisel not installed"}]


def test_a_block_outranks_unavailable(common, capsys) -> None:
    # a defect found is established even when another check could not run
    report = common.Report(CODES)
    report.add("block", "removed", "foo.yaml")
    report.mark_unavailable("cut", "chisel not installed")
    code, _, doc = emitted(report, capsys)
    assert (code, doc["status"]) == (1, "failed")
    assert doc["unavailable"]


def test_worst_first_and_only_used_codes(common, capsys) -> None:
    report = common.Report({**CODES, "unused": "never reported"})
    report.add("info", "moved", "b.yaml")
    report.add("warn", "removed", "b.yaml")
    report.add("info", "moved", "a.yaml")
    _, _, doc = emitted(report, capsys)
    assert list(doc["findings"]) == ["a.yaml", "b.yaml"]
    assert [f["sev"] for f in doc["findings"]["b.yaml"]] == ["warn", "info"]
    assert "unused" not in doc["codes"]


def test_unknown_code_or_severity_is_a_bug(common) -> None:
    report = common.Report(CODES)
    with pytest.raises(KeyError):
        report.add("warn", "nope", "foo.yaml")
    with pytest.raises(ValueError):
        report.add("unavailable", "removed", "foo.yaml")


def test_finding_is_one_line(common, capsys) -> None:
    report = common.Report(CODES)
    long_path = "/usr/include/*-linux-*/gnu/" + "x" * 200 + ".h"
    report.add(
        "warn", "removed", "foo.yaml", path=long_path, was={"arch": ["amd64", "s390x"]}
    )
    _, out, doc = emitted(report, capsys)
    lines = [ln for ln in out.splitlines() if "removed" in ln and "sev" in ln]
    assert len(lines) == 1 and lines[0].lstrip().startswith("- {"), out
    assert doc["findings"]["foo.yaml"][0]["path"] == long_path


@pytest.mark.parametrize(
    "value", ["1.10", "2027-07-15", "yes", "null", "a: b", "*glob", "#x", "", "01"]
)
def test_values_survive_the_round_trip(common, capsys, value) -> None:
    report = common.Report(CODES)
    report.add("warn", "removed", "foo.yaml", path=value)
    report.data["version"] = value
    _, _, doc = emitted(report, capsys)
    assert doc["findings"]["foo.yaml"][0]["path"] == value
    assert doc["version"] == value


def test_reporter_keys_follow_the_contract(common, capsys) -> None:
    report = common.Report({})
    report.data["package"] = "foo"
    report.data["tools"] = {"uv": common.Flow(present=True, version="0.1")}
    code, out, doc = emitted(report, capsys)
    assert code == 0
    assert list(doc) == ["status", "package", "tools"]
    assert "uv: {present: true, version: '0.1'}" in out


def test_merge(common, capsys) -> None:
    report = common.Report({})
    report.merge(
        {
            "status": "failed",
            "findings": {"foo.yaml": [{"sev": "block", "code": "removed"}]},
            "codes": {"removed": "gone"},
        }
    )
    report.merge(
        {
            "status": "unavailable",
            "unavailable": [{"check": "cut", "reason": "no chisel"}],
        }
    )
    code, _, doc = emitted(report, capsys)
    assert code == 1
    assert doc["counts"] == {"block": 1}
    assert doc["codes"] == {"removed": "gone"}
    assert doc["unavailable"] == [{"check": "cut", "reason": "no chisel"}]


def test_usage_goes_to_stderr(common, capsys) -> None:
    assert common.usage("usage: foo.py <bar>") == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "usage: foo.py" in captured.err


def test_imports_as_either_name(tmp_path) -> None:
    # a skill ships the copy as _common.py, the _shared source is common.py
    import subprocess

    (tmp_path / "_common.py").write_text((SHARED / "common.py").read_text())
    (tmp_path / "tool.py").write_text(
        "import sys\nsys.path.insert(0, sys.argv[1])\nimport _common\nprint(_common.EXIT)\n"
    )
    r = subprocess.run(
        [sys.executable, str(tmp_path / "tool.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


def test_lists_indent_under_their_key(common, capsys) -> None:
    report = common.Report(CODES)
    report.add("warn", "removed", "foo.yaml", path="/usr/bin/foo")
    _, out, _ = emitted(report, capsys)
    assert "\n  foo.yaml:\n    - {sev: warn" in out, out


def test_multiline_text_is_a_literal_block(common, capsys) -> None:
    script = "#!/bin/sh\nset -e\necho 'hi: there'\n"
    report = common.Report({})
    report.data["postinst"] = script
    _, out, doc = emitted(report, capsys)
    assert "postinst: |" in out, out
    assert doc["postinst"] == script
