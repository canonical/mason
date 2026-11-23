"""check-rock: one finding per rule, and the output contract."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "rockcrafter" / "scripts" / "check-rock.py"


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
KEYS = (
    "name", "title", "version", "summary", "description", "license", "base",
    "build-base", "run-user", "platforms", "services", "checks",
    "entrypoint-service", "entrypoint-command", "environment", "parts",
    "package-repositories", "extensions", "adopt-info", "contact", "issues",
    "source-code",
)  # fmt: skip
# rockcraft takes 26.10 here, and chisel-releases has no branch for it yet
BASES = ["ubuntu@22.04", "ubuntu@24.04", "ubuntu@26.10"]
BRANCHES = {"ubuntu-22.04", "ubuntu-24.04"}


def schema(extra_keys=(), required=("name", "summary", "description", "base", "platforms", "parts")):
    """A rockcraft schema cut down to the parts the linter reads."""
    props = {k: {} for k in (*KEYS, *extra_keys)}
    props["base"] = {"enum": ["bare", *BASES]}
    props["build-base"] = {"anyOf": [{"enum": [*BASES, "devel"]}, {"type": "null"}]}
    return {"properties": props, "required": list(required), "additionalProperties": False}


def with_build_base(spec):
    result = schema()
    result["properties"]["build-base"] = spec
    return result


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def slices_of(rel, pkg):
        if rel == "ubuntu-99.04":
            raise ValueError("unknown release")
        return [f"{pkg}_{n}" for n in SLICES.get(pkg, [])] or None

    monkeypatch.setattr(cr.rl, "slices_of", slices_of)
    monkeypatch.setattr(cr.rl, "has_branch", lambda branch: branch in BRANCHES)
    monkeypatch.setattr(cr.orientation, "rockcraft_version", lambda: "1.0.0")
    monkeypatch.setattr(cr.orientation, "rockcraft_schema", lambda version: schema())


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
        (changed(parts={"p": {"override-build": "chisel cut --release ubuntu-99.04 hello_bins"}}), "unknown-release"),
        (changed(**{"build-base": None}), "bare-needs-build-base"),
        (changed(version=2.12), "version-type"),
        (changed(version="2.12.1"), "version-granularity"),
        (changed(parts={"p": "nil"}), "bad-type"),
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


@pytest.mark.parametrize(
    "extra",
    [
        {"entrypoint-command": "/usr/bin/hello [ -g hi ]"},
        {"contact": "a@b.c", "issues": "https://x/issues", "source-code": "https://x"},
        {"license": None},
        {"summary": "", "description": ""},
        {"version": None, "adopt-info": "hello"},
        {"build-base": "devel"},
        {"platforms": {"my-label": {"build-on": ["amd64"], "build-for": ["amd64"]}}},
    ],
)
def test_what_rockcraft_accepts_is_clean(extra):
    assert run(changed(**extra)).findings == {}


def test_license_is_left_to_rockcraft():
    assert run(changed(license="not-an-spdx-id")).findings == {}


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"name": ""}, "missing-key"),
        ({"version": None}, "missing-key"),
        ({"platforms": {"my-label": None}}, "bad-platform"),
        ({"platforms": ["amd64"]}, "bad-type"),
        ({"services": ["s"]}, "bad-type"),
        ({"services": {"s": "run"}}, "bad-type"),
        ({"parts": ["p"]}, "bad-type"),
        ({"parts": {"p": {"plugin": "nil", "stage-packages": "hello_bins"}}}, "bad-type"),
        ({"parts": {"p": {"plugin": "nil", "stage-packages": ""}}}, "bad-type"),
    ],
)
def test_what_rockcraft_rejects_blocks(extra, code):
    report = run(changed(**extra))
    assert code in {f["code"] for items in report.findings.values() for f in items}
    assert report.status == "failed"


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
    # a cut ends with its command, even inside an indented block
    assert cr.cut_slices("if true; then\n  chisel cut --root x a_b\n  cp foo_bar baz_qux\nfi\n") == ["a_b"]


def test_cuts_carry_their_release():
    script = "chisel cut --release ubuntu-24.04 --root x a_b && chisel cut --release=./ --root y c_d\n# chisel cut e_f\n"
    assert cr.cuts(script) == [("ubuntu-24.04", ["a_b"]), ("./", ["c_d"])]
    assert cr.cuts("chisel cut --root x a_b") == [(None, ["a_b"])]


FORK = {"plugin": "nil", "source": "https://github.com/u/chisel-releases.git", "source-type": "git"}


def test_cut_from_a_fork_is_not_checked():
    # the slices a fork adds are not upstream: nothing here can read them
    script = 'chisel cut --release ./ --root "$CRAFT_PART_INSTALL" \\\n  base-files_base \\\n  figlet_bins\n'
    assert run(changed(parts={"slices": {**FORK, "override-build": script}})).findings == {}


def test_cut_from_a_checkout_is_checked_against_it(tmp_path, monkeypatch):
    sub = tmp_path / "sub"
    sub.mkdir()
    for tree in (tmp_path, sub):
        (tree / "chisel.yaml").write_text("format: v1\n")
    have = {(str(tmp_path), "figlet"): ["figlet_bins"], (str(sub), "figlet"): ["figlet_new"], ("ubuntu-24.04", "hello"): ["hello_bins"]}
    monkeypatch.setattr(cr.rl, "slices_of", lambda rel, pkg: have.get((rel, pkg)))

    def unknown(release, slices):
        script = f'chisel cut --release "{release}" --root x {slices}\n'
        parts = {
            "new": {"plugin": "nil", "source": str(tmp_path), "source-type": "local", "override-build": script},
            "old": {"plugin": "nil", "stage-packages": ["hello_bins", "hello_nope"]},
        }
        report = run(changed(parts=parts))
        return sorted((f["slice"], f["release"]) for items in report.findings.values() for f in items)

    # the checkout governs its own part's cut, the release everything else
    upstream = ("hello_nope", "ubuntu-24.04")
    assert unknown("./", "figlet_bins figlet_nope") == [("figlet_nope", str(tmp_path)), upstream]
    assert unknown("$CRAFT_PART_SRC", "figlet_bins") == [upstream]
    assert unknown("./sub", "figlet_new") == [upstream]
    assert unknown("${CRAFT_PART_SRC}/sub", "figlet_bins") == [("figlet_bins", str(sub)), upstream]


@pytest.mark.parametrize("part", [{}, {"source": "."}])
def test_cut_from_no_checkout_falls_back_to_the_release(part):
    # no chisel.yaml to read: a local tree that is not a checkout, or no source
    script = "chisel cut --release ./ --root x hello_nope\n"
    assert "unknown-slice" in codes(changed(parts={"p": {"plugin": "nil", **part, "override-build": script}}))


def test_cut_naming_an_unknown_release(monkeypatch):
    def slices_of(rel, pkg):
        if rel != "ubuntu-24.04":
            raise ValueError("unknown Ubuntu release")
        return [f"{pkg}_base", f"{pkg}_bins"]

    monkeypatch.setattr(cr.rl, "slices_of", slices_of)
    script = "chisel cut --release=ubuntu-99.04 --root x base-files_base\n"
    assert codes(changed(parts={"p": {"plugin": "nil", "override-build": script}})) == ["unknown-release"]


# --- what the installed rockcraft accepts ---------------------------------------


def test_keys_follow_the_installed_version(monkeypatch):
    doc = changed(**{"build-slices": ["base-files_base"]})
    assert codes(doc) == ["unknown-key"]
    monkeypatch.setattr(
        cr.orientation, "rockcraft_schema", lambda v: schema(extra_keys=["build-slices"])
    )
    assert codes(doc) == []


def test_required_keys_follow_the_installed_version(monkeypatch):
    doc = changed(title=None, summary=None)
    assert [f["key"] for f in run(doc).findings["rockcraft.yaml"]] == ["summary"]
    monkeypatch.setattr(
        cr.orientation, "rockcraft_schema", lambda v: schema(required=["name", "title"])
    )
    assert [f["key"] for f in run(doc).findings["rockcraft.yaml"]] == ["title"]


def test_version_is_required_whatever_the_schema_says():
    # the schema does not list it: craft-application asks for it after validation
    assert "version" not in schema()["required"]
    findings = run(changed(version=None)).findings["rockcraft.yaml"]
    assert [(f["code"], f["key"]) for f in findings] == [("missing-key", "version")]
    assert run(changed(version=None, **{"adopt-info": "hello"})).findings == {}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("base", "ubuntu@25.04"),  # a real release this rockcraft does not take
        ("base", "noble"),
        ("base", "devel"),  # a build-base only
        ("build-base", "ubuntu@25.04"),
        ("build-base", "bare"),
        ("base", 24.04),
    ],
)
def test_a_base_the_installed_rockcraft_does_not_take(key, value):
    extra = {key: value} if key == "base" else {"base": "bare", key: value}
    [finding] = [
        f for f in run(changed(**extra)).findings["rockcraft.yaml"] if f["code"] == "bad-base"
    ]
    assert (finding["key"], finding["value"]) == (key, str(value))
    assert "ubuntu@24.04" in finding["accepted"]


def test_an_accepted_base_needs_no_ubuntu_release_list(monkeypatch):
    def never(text):
        raise AssertionError("the release list was asked")

    monkeypatch.setattr(cr.rl, "resolve_release", never)
    assert run(changed(base="ubuntu@22.04", parts={"p": {"stage-packages": ["hello"]}})).findings == {}
    assert run(GOOD).status == "passed"


def test_a_refused_build_base_does_not_hide_the_slices_of_a_good_base():
    # an unchiseled rock is built from `base`: its slices are still checked
    doc = changed(
        base="ubuntu@24.04",
        **{"build-base": "ubuntu@25.04"},
        parts={"p": {"stage-packages": ["hello_binz"]}},
    )
    assert codes(doc) == ["bad-base", "unknown-slice"]
    # a chiseled one is built from `build-base`: refused, there is no branch to ask
    assert codes(changed(**{"build-base": "ubuntu@25.04"}, parts={"p": {"stage-packages": ["hello_binz"]}})) == ["bad-base"]


def test_slices_are_looked_up_on_the_base_named(monkeypatch):
    asked = []
    monkeypatch.setattr(cr.rl, "slices_of", lambda rel, pkg: asked.append(rel) or [f"{pkg}_bins", f"{pkg}_base"])
    run(changed(**{"build-base": "ubuntu@22.04"}))
    assert set(asked) == {"ubuntu-22.04"}


@pytest.mark.parametrize(
    ("version", "reason"),
    [(None, "not installed"), (cr.orientation.Failed("rockcraft --version: timed out"), "timed out")],
)
def test_without_a_rockcraft_version_the_schema_checks_do_not_run(monkeypatch, version, reason):
    def installed():
        if isinstance(version, Exception):
            raise version
        return version

    monkeypatch.setattr(cr.orientation, "rockcraft_version", installed)
    report = run(changed(color="red", summary=None, base="noble"))
    assert report.findings == {} and report.status == "unavailable"
    # with nothing to refuse `noble`, the slices staged on it go unchecked too
    problem, unchecked = report.unavailable
    assert problem["check"] == "rockcraft schema" and reason in problem["reason"]
    assert unchecked["check"] == "slices" and "noble" in unchecked["reason"]


def test_a_schema_that_cannot_be_read_is_unavailable_and_the_rest_still_runs(monkeypatch):
    def down(version):
        raise cr.orientation.Failed("rockcraft 1.0.0: HTTP Error 404: Not Found")

    monkeypatch.setattr(cr.orientation, "rockcraft_schema", down)
    assert run(GOOD).status == "unavailable"
    # findings beat unavailable: a blocker still fails the check
    report = run(changed(version=2.12, parts={"p": {"stage-packages": ["hello_binz"]}}))
    assert report.status == "failed" and report.unavailable
    assert codes(changed(version=2.12, parts={"p": {"stage-packages": ["hello_binz"]}})) == [
        "unknown-slice",
        "version-type",
    ]


@pytest.mark.parametrize(
    "broken",
    [
        {"properties": [], "required": []},
        {"properties": {"base": {"enum": ["bare"]}}, "required": []},  # no build-base
        {**schema(), "required": None},
        {**schema(), "required": "name"},  # not four keys named n, a, m, e
        {**schema(), "required": [[]]},
        {**schema(), "additionalProperties": True},  # an unlisted key is then no rejection
        {k: v for k, v in schema().items() if k != "additionalProperties"},
        with_build_base({"anyOf": [{"type": "string"}]}),  # no list at all
        # a list beside an open alternative is only part of what is accepted
        with_build_base({"anyOf": [{"enum": ["ubuntu@24.04"]}, {"type": "string"}]}),
        with_build_base({"anyOf": [{"enum": []}, {"type": "null"}]}),
        with_build_base({"enum": ["ubuntu@24.04"]}),
    ],
)
def test_a_schema_of_another_shape_is_not_an_empty_allow_list(monkeypatch, broken):
    monkeypatch.setattr(cr.orientation, "rockcraft_schema", lambda v: broken)
    report = run(changed(color="red", base="noble"))
    assert report.findings == {} and report.status == "unavailable"
    assert [u["check"] for u in report.unavailable] == ["rockcraft schema", "slices"]


def test_the_real_reader_at_the_installed_version(tmp_path, monkeypatch):
    """The script end to end: a rockcraft on PATH that states its version, and
    the schema published for exactly that version behind the redirect."""
    import json
    import os

    fake = tmp_path / "bin" / "rockcraft"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho 'rockcraft 7.8.9'\n")
    fake.chmod(0o755)
    (tmp_path / "7.8.9.json").write_text(json.dumps(schema(extra_keys=["only-in-7"])))
    doc = changed(**{"only-in-7": True, "color": "red"}, parts={"p": {"plugin": "nil"}})
    (tmp_path / "rockcraft.yaml").write_text(yaml.safe_dump(doc))
    env = {
        **os.environ,
        "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}",
        "ROCKCRAFT_SCHEMA_URL": (tmp_path / "{version}.json").as_uri().replace("%7B", "{").replace("%7D", "}"),
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=tmp_path, env=env, check=False
    )
    out = yaml.safe_load(proc.stdout)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert out["findings"] == {"rockcraft.yaml": [{"sev": "block", "code": "unknown-key", "key": "color"}]}

    # another version has no schema behind that url: nothing is assumed for it
    fake.write_text("#!/bin/sh\necho 'rockcraft 7.9.0.post1'\n")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=tmp_path, env=env, check=False
    )
    out = yaml.safe_load(proc.stdout)
    assert proc.returncode == 3 and "findings" not in out, proc.stdout
    assert [u["check"] for u in out["unavailable"]] == ["rockcraft schema"]
    assert "7.9.0.post1" in out["unavailable"][0]["reason"]


# --- where the slices are looked up ---------------------------------------------


def test_a_base_without_a_branch_is_one_finding_not_one_per_slice():
    doc = changed(**{"build-base": "ubuntu@26.10"})
    assert run(doc).findings == {
        "rockcraft.yaml": [{"sev": "block", "code": "unknown-release", "release": "ubuntu-26.10"}]
    }
    # an unchiseled rock asks chisel-releases for nothing
    assert run(changed(base="ubuntu@26.10", parts={"p": {"stage-packages": ["hello"]}})).findings == {}


def test_a_branch_that_cannot_be_asked_about_is_unavailable(monkeypatch):
    def down(branch):
        raise cr.rl.Unavailable("chisel-releases unreachable")

    monkeypatch.setattr(cr.rl, "has_branch", down)
    report = run(GOOD)
    assert report.findings == {} and report.status == "unavailable"
    assert [u["check"] for u in report.unavailable] == ["slices"]


def test_devel_names_no_release_and_says_its_slices_went_unchecked():
    report = run(changed(**{"build-base": "devel"}))
    assert report.findings == {} and report.status == "unavailable"
    [problem] = report.unavailable
    assert problem["check"] == "slices" and "devel" in problem["reason"]


def test_devel_with_no_slices_to_look_up_passes():
    report = run(changed(**{"build-base": "devel"}, parts={"p": {"plugin": "nil"}}))
    assert report.findings == {} and report.status == "passed"


def test_a_cut_that_names_its_release_is_checked_whatever_the_base():
    script = "chisel cut --release ubuntu-24.04 --root x hello_binz"
    report = run(changed(**{"build-base": "devel"}, parts={"p": {"override-build": script}}))
    assert [f["code"] for f in report.findings["rockcraft.yaml"]] == ["unknown-slice"]
    # nothing was left unchecked: the cut said where to look
    assert report.unavailable == []


def test_a_refused_base_is_not_also_an_unchecked_one():
    report = run(changed(**{"build-base": "ubuntu@25.04"}))
    assert codes(changed(**{"build-base": "ubuntu@25.04"})) == ["bad-base"]
    assert report.unavailable == []


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
