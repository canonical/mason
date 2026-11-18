"""check-rock: one finding per rule, and the output contract."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "_shared" / "check-rock.py"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


cr = module(SCRIPT)

GOOD = {
    "name": "hello",
    "version": "2.12",
    "summary": "s",
    "description": "d",
    "license": "GPL-3.0",
    "base": "bare",
    "build-base": "ubuntu@24.04",
    "run-user": "_daemon_",
    "platforms": {"amd64": None},
    "services": {"hello": {"command": "/usr/bin/hello", "override": "replace", "startup": "enabled"}},
    "parts": {"hello": {"plugin": "nil", "stage-packages": ["base-files_base", "hello_bins"]}},
}
SLICES = {"base-files": ["base", "release-info"], "hello": ["bins", "copyright"]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def resolve(text):
        if text != "24.04":
            raise ValueError("unknown")
        return cr.rl.Release("24.04", "noble", True, True)

    monkeypatch.setattr(cr.rl, "resolve_release", resolve)
    monkeypatch.setattr(
        cr.rl, "slices_of", lambda rel, pkg: [f"{pkg}_{n}" for n in SLICES.get(pkg, [])] or None
    )


def run(doc):
    report = cr.common.Report(cr.CODES)
    cr.check(doc, "rockcraft.yaml", report)
    return report


def codes(doc):
    return sorted({f["code"] for items in run(doc).findings.values() for f in items})


def changed(**kw):
    doc = {**GOOD, **kw}
    return {k: v for k, v in doc.items() if v is not None}


def test_good_rock_is_clean():
    report = run(GOOD)
    assert report.findings == {}
    assert report.status == "passed"


@pytest.mark.parametrize(
    ("doc", "code"),
    [
        ([1, 2], "not-a-mapping"),
        (changed(summary=None), "missing-key"),
        (changed(color="red"), "unknown-key"),
        (changed(base="noble"), "bad-base"),
        (changed(**{"build-base": "ubuntu@99.04"}), "unknown-release"),
        (changed(**{"build-base": None}), "bare-needs-build-base"),
        (changed(version=2.12), "version-type"),
        (changed(version="2.12.1"), "version-granularity"),
        (changed(license="GPL-3.0-or-later"), "license-form"),
        (changed(**{"run-user": None}), "root-user"),
        (changed(platforms={"x86_64": None}), "bad-platform"),
        (changed(services={"s": {"command": "hello", "override": "replace"}}), "service-command"),
        (changed(services={"s": {"command": "/usr/bin/hello"}}), "service-override"),
        (changed(parts={"p": {"stage-packages": ["hello_bins", "curl"]}}), "mixed-stage"),
        (changed(parts={"p": {"stage-packages": ["curl"]}}), "debs-on-bare"),
        (changed(**{"package-repositories": [{"type": "apt", "ppa": "a/b"}]}), "ppa-on-bare"),
        (changed(parts={"p": {"stage-packages": ["hello_binz"]}}), "unknown-slice"),
    ],
)
def test_each_rule(doc, code):
    assert code in codes(doc)


def test_codes_all_covered():
    # every code the linter can emit has a case above
    cases = test_each_rule.pytestmark[0].args[1]
    assert {c for _, c in cases} == set(cr.CODES)


def test_extensions_generate_parts():
    assert "missing-key" not in codes(changed(parts=None, extensions=["flask-framework"]))


def test_source_tag_allows_patch_version():
    parts = {"p": {"plugin": "go", "source": "x", "source-tag": "v1.2.3"}}
    assert "version-granularity" not in codes(changed(version="1.2.3", parts=parts))


def test_unknown_slice_in_chisel_cut():
    script = "chisel cut --release ubuntu-24.04 --root $CRAFT_PART_INSTALL \\\n  hello_bins hello_nope\n"
    report = run(changed(parts={"p": {"plugin": "nil", "override-build": script}}))
    bad = [f for items in report.findings.values() for f in items if f["code"] == "unknown-slice"]
    assert [f["slice"] for f in bad] == ["hello_nope"]


def test_cut_slices():
    assert cr.cut_slices("chisel cut --root x \\\n  a_b c_d\necho e_f\n") == ["a_b", "c_d"]


def test_release_unavailable_still_reports(monkeypatch):
    def down(text):
        raise cr.rl.Unavailable("meta-release unreachable")

    monkeypatch.setattr(cr.rl, "resolve_release", down)
    assert run(GOOD).status == "unavailable"
    # findings beat unavailable: a blocker still fails the check
    report = run(changed(license="GPL-3+"))
    assert report.status == "failed"
    assert report.unavailable


def test_slices_unavailable(monkeypatch):
    def down(rel, pkg):
        raise cr.rl.Unavailable("chisel-releases unreachable")

    monkeypatch.setattr(cr.rl, "slices_of", down)
    assert run(GOOD).status == "unavailable"


def cli(*args, cwd=None):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd, check=False
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_usage():
    code, _, err = cli("--help")
    assert code == 2
    assert "Usage: check-rock.py" in err


def test_missing_file_is_unavailable(tmp_path):
    code, out, _ = cli(cwd=tmp_path)
    assert code == 3
    assert yaml.safe_load(out)["status"] == "unavailable"


def test_bad_yaml_fails(tmp_path):
    (tmp_path / "rockcraft.yaml").write_text("name: [\n")
    code, out, _ = cli(cwd=tmp_path)
    doc = yaml.safe_load(out)
    assert code == 1
    assert doc["status"] == "failed"
    assert "not-a-mapping" in str(doc["findings"])
