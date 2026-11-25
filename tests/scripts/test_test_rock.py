"""test-rock: suite lint, spread failure parsing, and the run with a fake rockcraft."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "rock-create" / "scripts" / "test-rock.py"


def module(path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


tr = module(SCRIPT)

# real rockcraft 1.21 `rockcraft test` output, trimmed
FAILED_RUN = """\
:: 2026-11-10 10:00:01 Executing craft:ubuntu-24.04:spread/general/greeting (1/2)...
:: 2026-11-10 10:00:09 Error executing craft:ubuntu-24.04:spread/general/broken (Nov101000-1) :
:: -----
:: + docker run --rm hello:latest exec hello
:: error: no such binary
:: -----
:: 2026-11-10 10:00:10 Successful tasks: 1
:: 2026-11-10 10:00:10 Failed tasks: 1
:: 2026-11-10 10:00:10 Aborted tasks: 0
"""
PASSED_RUN = """\
:: Successful tasks: 2
:: Failed tasks: 0
:: Aborted tasks: 0
Testing successful.
"""
ABORTED_RUN = """\
:: Successful tasks: 0
:: Failed tasks: 0
:: Aborted tasks: 2
"""
# spread's own lines for a failed prepare / restore script (spread/runner.go)
PREPARE_FAILED_RUN = """\
:: 2026-11-10 10:00:01 Preparing craft:ubuntu-24.04:spread/general/ (Nov101000-1)...
:: 2026-11-10 10:00:09 Error preparing craft:ubuntu-24.04:spread/general/ (Nov101000-1) :
:: -----
:: + sudo rockcraft.skopeo copy oci-archive:hello.rock docker-daemon:hello:latest
:: error: no such image
:: -----
:: 2026-11-10 10:00:10 Successful tasks: 0
:: 2026-11-10 10:00:10 Aborted tasks: 2
:: 2026-11-10 10:00:10 Failed suite prepare: 1
::     - craft:ubuntu-24.04:spread/general/
"""
RESTORE_FAILED_RUN = """\
:: 2026-11-10 10:00:09 Error restoring craft:ubuntu-24.04:spread/general/greeting (Nov101000-1) :
:: -----
:: + docker rm web
:: Error: no such container
:: -----
:: 2026-11-10 10:00:10 Successful tasks: 1
:: 2026-11-10 10:00:10 Aborted tasks: 0
:: 2026-11-10 10:00:10 Failed task restore: 1
"""


def test_failures_block_between_rules():
    lines = FAILED_RUN.splitlines()
    assert tr.failures(lines) == {
        "craft:ubuntu-24.04:spread/general/broken": [
            "+ docker run --rm hello:latest exec hello",
            "error: no such binary",
        ]
    }


def test_failures_none():
    assert tr.failures(PASSED_RUN.splitlines()) == {}


def test_failures_by_verb():
    lines = PREPARE_FAILED_RUN.splitlines()
    assert tr.failures(lines) == {}
    assert list(tr.failures(lines, "preparing")) == ["craft:ubuntu-24.04:spread/general/"]


@pytest.fixture
def suite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rockcraft-test.yaml").write_text("backends: {}\n")
    task = tmp_path / "spread" / "general" / "greeting" / "task.yaml"
    task.parent.mkdir(parents=True)
    task.write_text("execute: |\n  docker run --rm hello:latest exec hello\n")
    return tmp_path


def lint_codes():
    report = tr.common.Report(tr.CODES)
    tr.lint(report)
    return [f["code"] for items in report.findings.values() for f in items]


def test_lint_clean(suite):
    assert lint_codes() == []


def test_lint_no_suite(suite):
    (suite / "rockcraft-test.yaml").unlink()
    assert lint_codes() == ["no-suite"]


def test_lint_deprecated_spread_yaml(suite):
    (suite / "rockcraft-test.yaml").rename(suite / "spread.yaml")
    assert lint_codes() == ["deprecated-spread-yaml"]


def test_lint_both_suite_files(suite):
    # rockcraft reads rockcraft-test.yaml first: a spread.yaml beside it is not its suite
    (suite / "spread.yaml").write_text("project: other\n")
    assert lint_codes() == []


def test_lint_placeholder(suite):
    task = suite / "spread" / "general" / "todo" / "task.yaml"
    task.parent.mkdir()
    task.write_text(f"execute: |\n  # {tr.PLACEHOLDER}\n")
    assert lint_codes() == ["placeholder"]


def run(suite: Path, output: str | None, code: int = 0):
    bindir = suite / "bin"
    bindir.mkdir()
    if output is not None:
        (bindir / "out.txt").write_text(output)
        exe = bindir / "rockcraft"
        exe.write_text(f'#!/bin/sh\ncat "{bindir}/out.txt"\nexit {code}\n')
        exe.chmod(0o755)
    path = f"{bindir}:{os.environ['PATH']}" if output is not None else str(bindir)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=suite,
        env={**os.environ, "PATH": path}, check=False,
    )  # fmt: skip
    return proc.returncode, yaml.safe_load(proc.stdout)


def test_run_passed(suite):
    code, doc = run(suite, PASSED_RUN)
    assert (code, doc["status"]) == (0, "passed")
    assert doc["tasks"] == {"passed": 2, "failed": 0, "aborted": 0}


def test_run_failed(suite):
    code, doc = run(suite, FAILED_RUN, 1)
    assert (code, doc["status"]) == (1, "failed")
    assert doc["tasks"] == {"passed": 1, "failed": 1, "aborted": 0}
    finding = doc["findings"]["craft:ubuntu-24.04:spread/general/broken"][0]
    assert finding["code"] == "task-failed"
    assert "no such binary" in finding["output"]


def test_run_aborted_is_unavailable(suite):
    code, doc = run(suite, ABORTED_RUN, 1)
    assert (code, doc["status"]) == (3, "unavailable")


def test_run_prepare_failed(suite):
    code, doc = run(suite, PREPARE_FAILED_RUN, 1)
    assert (code, doc["status"]) == (1, "failed")
    finding = doc["findings"]["craft:ubuntu-24.04:spread/general/"][0]
    assert (finding["code"], finding["step"]) == ("setup-failed", "preparing")
    assert "no such image" in finding["output"]
    # the aborted tasks are explained by the finding, not a second unavailable check
    assert "unavailable" not in doc
    assert doc["tasks"] == {"passed": 0, "failed": 0, "aborted": 2}


def test_run_restore_failed(suite):
    code, doc = run(suite, RESTORE_FAILED_RUN, 1)
    assert (code, doc["status"]) == (1, "failed")
    finding = doc["findings"]["craft:ubuntu-24.04:spread/general/greeting"][0]
    assert (finding["code"], finding["step"]) == ("setup-failed", "restoring")


def test_run_prepare_offline_is_unavailable(suite):
    out = PREPARE_FAILED_RUN.replace("error: no such image", "error: unable to contact snap store")
    code, doc = run(suite, out, 1)
    assert (code, doc["status"]) == (3, "unavailable")
    assert "findings" not in doc
    assert ["network" in u["reason"] for u in doc["unavailable"]] == [True]


def test_run_no_verdict_is_unavailable(suite):
    code, doc = run(suite, "Failed to launch the test instance\n", 1)
    assert (code, doc["status"]) == (3, "unavailable")
    assert "Failed to launch" in str(doc["unavailable"])


def test_no_rockcraft_is_unavailable(suite):
    code, doc = run(suite, None)
    assert (code, doc["status"]) == (3, "unavailable")


def test_lint_blocks_before_running(suite):
    (suite / "rockcraft-test.yaml").unlink()
    code, doc = run(suite, None)
    assert (code, doc["status"]) == (1, "failed")


def test_usage():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "Usage: test-rock.py" in proc.stderr
