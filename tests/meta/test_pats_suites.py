"""The pats ci runs one job per suite: which suites a change needs.

`.github/scripts/pats-suites.sh` turns the changed files of a pull request
into the json array the workflows fan out over. Run:

    uv run --with pyyaml --with pytest pytest tests/meta/
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "pats-suites.sh"

# the script reads pats.yaml with yq, as the ci runners have it.
pytestmark = pytest.mark.skipif(shutil.which("yq") is None, reason="needs yq")

CONFIG = """\
models:
  kind: agent
  items:
    ci-not-a-suite: {model: m}
suites:
  kind: suite
  items:
    slicer: {tasks: knockout}
    ci-chisel-slice: {tasks: knockout}
    ci-rock-create: {tasks: rock-create}
    ci-rock-create-debug: {tasks: rock-debug}
    ci-Bad_Name: {tasks: knockout}
"""

ROCK = ["ci-rock-create", "ci-rock-create-debug"]
EVERY = ["ci-chisel-slice", *ROCK]


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "pats.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def run(config: Path, *args: str, changed: list[str] | None = None):
    return subprocess.run(
        ["bash", str(SCRIPT), str(config), *args],
        input="".join(f"{f}\n" for f in changed or []),
        capture_output=True,
        text=True,
        check=False,
    )


def suites(config: Path, *args: str, changed: list[str] | None = None) -> list[str]:
    proc = run(config, *args, changed=changed)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize(
    ("changed", "want"),
    [
        # a skill picks its own suite, and only one that is declared
        (["skills/chisel-slice/SKILL.md"], ["ci-chisel-slice"]),
        # ... or every variant of it, ci-<skill>-<variant>
        (["skills/rock-create/kb/x.md", "skills/rock-create/SKILL.md"], ROCK),
        (["skills/chisel-slice/a", "skills/rock-create/b"], EVERY),
        (["skills/mason/SKILL.md"], []),
        # a suite that only starts like the skill's name is not its variant
        (["skills/rock-creat/SKILL.md"], []),
        # the eval and the pats ci move every score
        (["tests/skills/pats.yaml"], EVERY),
        ([".github/workflows/pats.yml"], EVERY),
        ([".github/scripts/pats-suites.sh"], EVERY),
        # nothing else does
        (["tests/skills/README.md"], []),
        (["README.md", "shared/common.py", "skills/README.md"], []),
        ([], []),
    ],
)
def test_changed_files_pick_suites(
    config: Path, changed: list[str], want: list[str]
) -> None:
    assert suites(config, changed=changed) == want


def test_all_is_every_declared_ci_suite(config: Path) -> None:
    assert suites(config, "--all") == EVERY


def test_a_suite_declared_twice_is_one_job(config: Path) -> None:
    more = "nightly:\n  kind: suite\n  items:\n    ci-chisel-slice: {tasks: denovo}\n"
    config.write_text(CONFIG + more, encoding="utf-8")
    assert suites(config, "--all") == EVERY


def test_output_is_one_line_for_github_output(config: Path) -> None:
    proc = run(config, "--all")
    assert proc.stdout == json.dumps(EVERY, separators=(",", ":")) + "\n"
    assert run(config, changed=["README.md"]).stdout == "[]\n"


@pytest.mark.parametrize(
    "args", [[], ["--help"], ["missing.yaml"], ["CONFIG", "--nope"]]
)
def test_usage_errors(config: Path, args: list[str]) -> None:
    argv = [str(config) if a == "CONFIG" else a for a in args]
    proc = subprocess.run(
        ["bash", str(SCRIPT), *argv],
        input="",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert proc.stderr.startswith("pats-suites: ")
    assert proc.stdout == ""
