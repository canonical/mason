"""try-cut --base: cut each changed slice from the base ref and from the
worktree, and report what the change stopped installing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "_shared" / "try-cut.py"

# a stand-in for chisel cut: installs each requested slice's explicit content
# paths, following same-package essentials, and fails the way it is told to.
FAKE_CHISEL = f"""#!{sys.executable}
import pathlib, sys, yaml
args = sys.argv[1:]
if "--help" in args:
    print("--ignore=<what>")
    sys.exit(0)
release = pathlib.Path(args[args.index("--release") + 1])
root = pathlib.Path(args[args.index("--root") + 1])
if (release / "FAIL").exists():
    sys.stderr.write("error: " + (release / "FAIL").read_text())
    sys.exit(1)

def install(key, seen):
    if key in seen:
        return
    seen.add(key)
    pkg, _, name = key.partition("_")
    doc = yaml.safe_load((release / "slices" / f"{{pkg}}.yaml").read_text())
    body = doc["slices"][name] or {{}}
    for dep in body.get("essential") or []:
        if dep.partition("_")[0] == pkg:
            install(dep, seen)
    for path in body.get("contents") or {{}}:
        target = root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")

seen = set()
for key in [a for a in args if "_" in a and "/" not in a and not a.startswith("-")]:
    install(key, seen)
"""

BASE = """\
package: foo
slices:
  bins:
    contents:
      /usr/bin/foo:
      /usr/bin/foo-helper:
  copyright:
    contents:
      /usr/share/doc/foo/copyright:
"""

BAR = """\
package: bar
slices:
  bins:
    contents:
      /usr/bin/bar:
"""


@pytest.fixture
def checkout(tmp_path):
    """A chisel-releases checkout committed at BASE, with a fake chisel on PATH."""
    repo, bin_dir = tmp_path / "repo", tmp_path / "bin"
    (repo / "slices").mkdir(parents=True)
    bin_dir.mkdir()
    (bin_dir / "chisel").write_text(FAKE_CHISEL)
    (bin_dir / "chisel").chmod(0o755)
    (repo / "chisel.yaml").write_text("format: v3\n")
    (repo / "slices" / "foo.yaml").write_text(BASE)
    (repo / "slices" / "bar.yaml").write_text(BAR)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    git = [
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "-c",
        "commit.gpgsign=false",
    ]
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
        subprocess.run([*git, *cmd], cwd=repo, env=env, check=True, capture_output=True)
    return repo, env


def cut(checkout, *args, base="HEAD") -> tuple[int, dict]:
    """try-cut --base=<base> on the checkout; base=None is the bare --base."""
    repo, env = checkout
    flag = "--base" if base is None else f"--base={base}"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), flag, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in r.stderr, r.stderr
    leftovers = [p.name for p in repo.iterdir() if p.name.startswith("chisel-")]
    assert not leftovers, leftovers
    return r.returncode, yaml.safe_load(r.stdout)


def test_unchanged_checkout_compares_nothing(checkout) -> None:
    code, doc = cut(checkout)
    assert (code, doc["status"], doc["compared"]) == (0, "passed", []), doc


def test_dropped_path_is_lost(checkout) -> None:
    repo, _ = checkout
    (repo / "slices/foo.yaml").write_text(
        BASE.replace("      /usr/bin/foo-helper:\n", "")
    )
    code, doc = cut(checkout)
    assert (code, doc["status"]) == (0, "passed"), doc
    assert doc["findings"] == {
        "slices/foo.yaml": [
            {
                "sev": "warn",
                "code": "lost",
                "slice": "foo_bins",
                "path": "/usr/bin/foo-helper",
            }
        ]
    }
    assert {c["slice"] for c in doc["compared"]} == {"foo_bins", "foo_copyright"}


def test_subdivided_slice_loses_nothing(checkout) -> None:
    repo, _ = checkout
    (repo / "slices/foo.yaml").write_text(
        BASE.replace(
            "      /usr/bin/foo-helper:\n",
            "",
        ).replace(
            "  bins:\n",
            "  bins:\n    essential:\n      - foo_helper\n",
        )
        + "  helper:\n    contents:\n      /usr/bin/foo-helper:\n"
    )
    code, doc = cut(checkout)
    assert (code, doc["status"]) == (0, "passed") and "findings" not in doc, doc


def test_named_slices_only(checkout) -> None:
    repo, _ = checkout
    (repo / "slices/foo.yaml").write_text(
        BASE.replace("      /usr/bin/foo-helper:\n", "")
    )
    _, doc = cut(checkout, "foo_copyright")
    assert [c["slice"] for c in doc["compared"]] == ["foo_copyright"]
    assert "findings" not in doc, doc


def test_new_cut_failure_fails(checkout) -> None:
    repo, _ = checkout
    (repo / "slices/foo.yaml").write_text(BASE + "  extra:\n    contents:\n      /x:\n")
    (repo / "FAIL").write_text("slice foo_extra has a conflict\n")
    code, doc = cut(checkout)
    assert (code, doc["status"]) == (1, "failed"), doc
    assert {f["code"] for f in doc["findings"]["slices/foo.yaml"]} == {"cut-failed"}


def test_base_cut_uses_the_merge_base(checkout) -> None:
    # a slice added on the base after branching is neither cut nor compared
    repo, env = checkout
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]

    def run(*cmd):
        return subprocess.run(
            [*git, *cmd], cwd=repo, env=env, check=True, capture_output=True, text=True
        ).stdout.strip()

    run("branch", "base")
    run("checkout", "-q", "--detach")
    (repo / "slices/foo.yaml").write_text(
        BASE.replace("      /usr/bin/foo-helper:\n", "")
    )
    run("commit", "-qam", "drop the helper")
    work = run("rev-parse", "HEAD")
    run("checkout", "-q", "base")
    (repo / "slices/bar.yaml").write_text(BAR + "  extra:\n    contents:\n      /x:\n")
    run("commit", "-qam", "bar grows on the base")
    run("checkout", "-q", work)
    code, doc = cut(checkout, base="base")
    assert (code, doc["status"]) == (0, "passed"), doc
    assert doc["merge base"] and "caveat" not in doc
    assert [c["slice"] for c in doc["compared"]] == ["foo_bins", "foo_copyright"]
    assert list(doc["findings"]) == ["slices/foo.yaml"]


def test_bare_base_is_the_manifest_release(checkout) -> None:
    repo, env = checkout
    (repo / "chisel.yaml").write_text(
        "format: v3\narchives:\n  ubuntu:\n    version: 26.04\n"
    )
    subprocess.run(
        ["git", "branch", "ubuntu-26.04"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )
    (repo / "slices/foo.yaml").write_text(
        BASE.replace("      /usr/bin/foo-helper:\n", "")
    )
    code, doc = cut(checkout, base=None)
    assert (code, doc["status"], doc["base"]) == (0, "passed", "ubuntu-26.04"), doc
    assert list(doc["findings"]) == ["slices/foo.yaml"]


def test_bare_base_without_a_manifest_release_is_unavailable(checkout) -> None:
    code, doc = cut(checkout, base=None)
    assert (code, doc["status"]) == (3, "unavailable"), doc
    assert "--base=<ref>" in doc["unavailable"][0]["reason"]


def test_unknown_base_is_unavailable(checkout) -> None:
    repo, env = checkout
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--base=no-such-ref"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    doc = yaml.safe_load(r.stdout)
    assert (r.returncode, doc["status"]) == (3, "unavailable"), r.stdout
    assert doc["unavailable"][0]["check"] == "base"
