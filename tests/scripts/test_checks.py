"""pytest regression net for the skill's deterministic checkers.

Exercises the scripts under _shared/ -- the sources the skills ship copies of -- on inline
fixtures via subprocess, so this tests the real CLI, not imported internals. The
subprocessed scripts need pyyaml, which must be present under the runner's
interpreter. Run:

    uv run --with pyyaml --with pytest pytest tests/scripts/
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "_shared"


def run(script: str, *args: str) -> str:
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout + r.stderr


def write(d: Path, name: str, text: str) -> str:
    p = d / name
    p.write_text(text, encoding="utf-8")
    return str(p)


CLEAN = """\
package: foo
essential:
  - foo_copyright
slices:
  bins:
    essential:
      - libc6_libs
    contents:
      /usr/bin/foo:
  copyright:
    contents:
      /usr/share/doc/foo/copyright:
"""

# unsorted contents + unsorted essential + a man page + hint (invalid on v1).
DIRTY = """\
package: foo
essential:
  - foo_copyright
slices:
  bins:
    essential:
      - libc6_libs
      - base-files_base
    hint: Some tool
    contents:
      /usr/bin/zzz:
      /usr/bin/aaa:
      /usr/share/man/man1/foo.1:
  copyright:
    contents:
      /usr/share/doc/foo/copyright:
"""


CLEAN_V3 = """\
package: foo
essential:
  foo_copyright:
slices:
  bins:
    essential:
      libc6_libs:
    contents:
      /usr/bin/foo:
  copyright:
    contents:
      /usr/share/doc/foo/copyright:
"""


def test_check_slice() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # list-form essential is the v1/v2 shape; the map form is v3's.
        out = run("check-slice.py", write(d, "foo.yaml", CLEAN), "--format", "1")
        assert "ok:" in out and "block" not in out, out
        out = run("check-slice.py", write(d, "foo.yaml", CLEAN_V3), "--format", "3")
        assert "ok:" in out and "block" not in out, out
        # COVER: shape-vs-format gates both ways -- list on v3 and map on v1 are
        # chisel parse errors the linter must block.
        out = run("check-slice.py", write(d, "foo.yaml", CLEAN), "--format", "3")
        assert "essential must be a map on v3" in out, out
        out = run("check-slice.py", write(d, "foo.yaml", CLEAN_V3), "--format", "1")
        assert "essential-as-map is v3+ only" in out, out

        out = run("check-slice.py", write(d, "foo.yaml", DIRTY), "--format", "1")
        assert "contents paths not sorted" in out, out
        assert "essential entries not sorted" in out, out
        assert "man pages" in out, out
        # chisel does not gate hint: on format -- it is branch convention, so a
        # v1 branch gets a warning, never a block.
        assert "hint: is a v3+ branch convention" in out, out
        assert "block" not in out.split("bins.hint")[1].split("\n")[0], out

        # COVER: the path-shape rules chisel enforces at parse time. each is a
        # block on its own, and none of them fire on a well-formed path.
        def path_sdf(entry: str) -> str:
            return (
                "package: foo\nessential:\n  foo_copyright:\nslices:\n  bins:\n"
                f"    contents:\n      {entry}\n"
                "  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"
            )

        for entry, expected in [
            ("/usr/bin/*: {mode: 0755}", "wildcard path cannot set"),
            ("/usr/lib/foo: {make: true}", "make: true requires the path to end in /"),
            (
                "/var/lib/chisel/**: {generate: manifest, until: mutate}",
                "only arch: is allowed",
            ),
            (
                "/var/lib/chisel/*/**: {generate: manifest}",
                "must end in /** and hold no other wildcard",
            ),
            ("/x: {prefer: foo}", "names its own package"),
        ]:
            out = run(
                "check-slice.py", write(d, "foo.yaml", path_sdf(entry)), "--format", "3"
            )
            assert expected in out, (entry, out)

        for entry in [
            "/usr/bin/*: {arch: [amd64]}",
            "/usr/lib/foo/: {make: true}",
            "/var/lib/chisel/**: {generate: manifest}",
            "/x: {prefer: otherpkg}",
        ]:
            out = run(
                "check-slice.py", write(d, "foo.yaml", path_sdf(entry)), "--format", "3"
            )
            assert "block" not in out, (entry, out)

        # base-files really does own bin/ and lib/ -- exempt from the name warning.
        bf = (
            "package: base-files\nessential:\n  base-files_copyright:\nslices:\n"
            "  bin:\n    contents:\n      /bin:\n"
            "  copyright:\n    contents:\n      /usr/share/doc/base-files/copyright:\n"
        )
        out = run("check-slice.py", write(d, "base-files.yaml", bf), "--format", "3")
        assert "use 'bins'" not in out, out

        # filename must match package.
        out = run("check-slice.py", write(d, "bar.yaml", CLEAN), "--format", "3")
        assert "!= filename stem" in out, out

        # hint validation (v3): a good hint is clean; length/style are checked.
        def hint_sdf(h):
            return f"package: foo\nessential:\n  foo_copyright:\nslices:\n  bins:\n    hint: {h}\n    contents:\n      /usr/bin/foo:\n  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"

        out = run(
            "check-slice.py",
            write(d, "foo.yaml", hint_sdf("System log viewer")),
            "--format",
            "3",
        )
        assert "hint" not in out, out  # valid hint, no findings
        out = run(
            "check-slice.py",
            write(
                d,
                "foo.yaml",
                hint_sdf("The tool that manages absolutely everything here."),
            ),
            "--format",
            "3",
        )
        assert "caps it at 40" in out, out  # length is a parse-error block
        assert "start with an article" in out, out  # style warn

        # v3-essential is a v1/v2 backport; a chisel parse error on v3.
        v3e = "package: foo\nslices:\n  bins:\n    v3-essential:\n      libc6_libs: {arch: [amd64]}\n    contents:\n      /usr/bin/foo:\n  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"
        out = run("check-slice.py", write(d, "foo.yaml", v3e), "--format", "3")
        assert "v3-essential is rejected on v3" in out, out
        # ...but fine on v1 (no finding).
        out = run("check-slice.py", write(d, "foo.yaml", v3e), "--format", "1")
        assert "v3-essential" not in out, out


def test_branch_format_from_git() -> None:
    # --branch resolves format from that branch's chisel.yaml in the local git
    # object store (no hardcoded table, no network). Build a throwaway repo whose
    # committed chisel.yaml is v3, then lint a list-form SDF against --branch.
    import os

    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "chisel.yaml").write_text("format: v3\n", encoding="utf-8")
        (d / "foo.yaml").write_text(CLEAN, encoding="utf-8")  # list-form essential

        def git(*a: str) -> None:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(d),
                    "-c",
                    "user.name=t",
                    "-c",
                    "user.email=t@t",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "commit.gpgsign=false",
                    *a,
                ],
                check=True,
                capture_output=True,
                env=env,
            )

        git("init", "-q", "-b", "ubuntu-99.10")
        git("add", "-A")
        git("commit", "-qm", "base")

        def lint(branch: str) -> str:
            r = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "check-slice.py"),
                    "foo.yaml",
                    "--branch",
                    branch,
                ],
                cwd=str(d),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            return r.stdout + r.stderr

        # v3 resolved from the committed chisel.yaml -> list-form essential blocks.
        assert "essential must be a map on v3" in lint("ubuntu-99.10"), lint(
            "ubuntu-99.10"
        )
        # an unknown ref resolves to no format -> gated checks cannot run: block.
        out = lint("ubuntu-00.00")
        assert "essential must be a map on v3" not in out, out
        assert "block" in out and "format unknown" in out, out


def test_branch_format_origin_fallback() -> None:
    # the real cross-branch case: the target release is only a remote-tracking
    # ref (no local branch), so format_of_branch must fall back to origin/<branch>.
    import os

    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }

    def git(cwd: Path, *a: str) -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(cwd),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                *a,
            ],
            check=True,
            capture_output=True,
            env=env,
        )

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        origin, clone = d / "origin", d / "clone"
        origin.mkdir()
        # origin default branch 'main' (no chisel.yaml) + ubuntu-88.04 at format v3.
        git(origin, "init", "-q", "-b", "main")
        (origin / "README").write_text("x", encoding="utf-8")
        git(origin, "add", "-A")
        git(origin, "commit", "-qm", "main")
        git(origin, "checkout", "-q", "-b", "ubuntu-88.04")
        (origin / "chisel.yaml").write_text("format: v3\n", encoding="utf-8")
        git(origin, "add", "-A")
        git(origin, "commit", "-qm", "v3 branch")
        git(
            origin, "checkout", "-q", "main"
        )  # leave HEAD on main so the clone omits ubuntu-88.04
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(clone)],
            check=True,
            capture_output=True,
            env=env,
        )
        (clone / "foo.yaml").write_text(CLEAN, encoding="utf-8")  # list-form essential

        # precondition: no LOCAL ubuntu-88.04 -> only origin/ubuntu-88.04 can resolve it.
        rb = subprocess.run(
            ["git", "-C", str(clone), "rev-parse", "--verify", "-q", "ubuntu-88.04"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert rb.returncode != 0, "expected ubuntu-88.04 to be remote-only"

        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "check-slice.py"),
                "foo.yaml",
                "--branch",
                "ubuntu-88.04",
            ],
            cwd=str(clone),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        out = r.stdout + r.stderr
        # v3 resolved via origin/ubuntu-88.04 -> list-form essential blocks.
        assert "essential must be a map on v3" in out, out


def test_orientation_release_discovery() -> None:
    # hermetic end-to-end for the live-release table: point discovery at a local
    # repo (no network) with a future-eol branch (listed) and a past-eol branch
    # (not listed). also pins that the whole report is parseable YAML, which is
    # what lets a caller read it as data. exercises the set -e paths for real.
    import os

    import yaml

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        origin, clone = d / "origin", d / "clone"
        env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "CHISEL_RELEASES_URL": str(origin),
        }

        def git(cwd: Path, *a: str) -> None:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(cwd),
                    "-c",
                    "user.name=t",
                    "-c",
                    "user.email=t@t",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "commit.gpgsign=false",
                    *a,
                ],
                check=True,
                capture_output=True,
                env=env,
            )

        def manifest(fmt: str, ver: str, eol: str) -> str:
            return (
                f"format: {fmt}\narchives:\n  ubuntu:\n    version: '{ver}'\n"
                f"    suites: [foo]\nmaintenance:\n  end-of-life: {eol}\n"
            )

        origin.mkdir()
        git(origin, "init", "-q", "-b", "ubuntu-40.04")
        (origin / "chisel.yaml").write_text(
            manifest("v3", "40.04", "2999-01-01"), encoding="utf-8"
        )
        git(origin, "add", "-A")
        git(origin, "commit", "-qm", "live lts")
        git(origin, "checkout", "-q", "-b", "ubuntu-30.10")
        (origin / "chisel.yaml").write_text(
            manifest("v2", "30.10", "2000-01-01"), encoding="utf-8"
        )
        git(origin, "add", "-A")
        git(origin, "commit", "-qm", "dead interim")
        git(origin, "checkout", "-q", "ubuntu-40.04")  # HEAD -> the future-eol branch
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(clone)],
            check=True,
            capture_output=True,
            env=env,
        )

        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "orientation.py")],
            cwd=str(clone),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        # the whole report is YAML, so it parses as data, not just reads as prose
        doc = yaml.safe_load(out)
        assert doc["end-of-life"] == "2999-01-01", out
        assert doc["manifest format"] == "v3", out
        assert doc["tools"]["git"]["present"] is True, out
        assert doc["release discovery"]["status"] == "passed", out
        # discovery table: live branches only, formats normalised. a branch whose
        # end-of-life has passed is not listed at all -- nor is one that declares
        # no end-of-life, since it cannot be shown to be live.
        assert doc["live releases"]["ubuntu-40.04"] == {
            "format": "v3",
            "end-of-life": "2999-01-01",
        }, out
        assert "ubuntu-30.10" not in doc["live releases"], out


def test_check_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        sdf = write(d, "foo.yaml", CLEAN)
        exercised = write(
            d,
            "task.yaml",
            'summary: x\nexecute: |\n  rootfs="$(install-slices foo_bins)"\n  chroot "$rootfs" foo --version\n',
        )
        out = run("check-test.py", sdf, exercised)
        assert "ok:" in out, out

        # a test that touches none of the binaries is the red flag (warn).
        missing = write(d, "empty.yaml", "summary: x\nexecute: |\n  true\n")
        out = run("check-test.py", sdf, missing)
        assert "warn" in out and "references none" in out, out

        # partial coverage is advisory (info), not a warn: two bins, one tested.
        two = "package: foo\nessential:\n  - foo_copyright\nslices:\n  bins:\n    contents:\n      /usr/bin/foo:\n      /usr/bin/zzz:\n  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"
        sdf2 = write(d, "foo2.yaml", two)
        one = write(
            d, "one.yaml", 'summary: x\nexecute: |\n  chroot "$r" foo --version\n'
        )
        out = run("check-test.py", sdf2, one)
        assert "info" in out and "1/2 binaries referenced" in out and "zzz" in out, out
        assert "warn" not in out, out


@pytest.mark.parametrize(
    "contents", ["/usr/share/foo/data", "/usr/lib/libfoo.so.1", "/usr/bin/*"]
)
def test_check_test_requires_task_without_explicit_binaries(
    tmp_path: Path, contents: str
) -> None:
    sdf = write(tmp_path, "foo.yaml", CLEAN.replace("/usr/bin/foo", contents))
    out = run("check-test.py", sdf, str(tmp_path / "missing.yaml"))
    assert "warn" in out and "no spread test found" in out, out


@pytest.mark.parametrize(
    "task",
    [
        "",
        "[]",
        "summary: [broken",
        "summary: x\nexecute: []\n",
        "summary: x\nexecute: ''\n",
        "execute: true\n",
    ],
)
def test_check_test_rejects_malformed_task(tmp_path: Path, task: str) -> None:
    sdf = write(tmp_path, "foo.yaml", CLEAN)
    out = run("check-test.py", sdf, write(tmp_path, "task.yaml", task))
    assert "warn" in out and "cannot validate spread task" in out, out
    assert "Traceback" not in out, out


def test_check_test_ignores_metadata_and_comments(tmp_path: Path) -> None:
    sdf = write(tmp_path, "foo.yaml", CLEAN)
    task = write(
        tmp_path,
        "task.yaml",
        (
            "summary: foo\nenvironment:\n  NAME: foo\nexecute: |\n"
            "  # foo --version\n  true  # foo\n"
        ),
    )
    out = run("check-test.py", sdf, task)
    assert "warn" in out and "references none" in out, out
    write(tmp_path, "test.sh", "# foo\ntrue # foo\n")
    assert "references none" in run("check-test.py", sdf, task)
    write(tmp_path, "test.sh", 'chroot "$rootfs" /usr/bin/foo --version\n')
    task = write(tmp_path, "task.yaml", "summary: x\nexecute: ./test.sh\n")
    assert "ok:" in run("check-test.py", sdf, task)


def test_check_test_accepts_data_assertions(tmp_path: Path) -> None:
    sdf = write(
        tmp_path, "foo.yaml", CLEAN.replace("/usr/bin/foo", "/usr/share/foo/data")
    )
    task = write(
        tmp_path,
        "task.yaml",
        (
            'summary: x\nexecute: |\n  rootfs="$(install-slices foo_bins consumer_bins)"\n'
            '  chroot "$rootfs" consumer /usr/share/foo/data | grep -Fiq expected\n'
        ),
    )
    out = run("check-test.py", sdf, task)
    assert "info" in out and "review slice assertions manually" in out, out
    assert "warn" not in out, out


def test_check_test_reports_unreadable_helper(tmp_path: Path) -> None:
    sdf = write(tmp_path, "foo.yaml", CLEAN)
    task = write(tmp_path, "task.yaml", "summary: x\nexecute: ./test.sh\n")
    (tmp_path / "test.sh").write_bytes(b"\xff")
    out = run("check-test.py", sdf, task)
    assert "warn" in out and "Traceback" not in out, out


def test_check_diff() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        old = write(d, "old.yaml", CLEAN)
        # drop the whole bins slice -> both slice-removed and path-removed shapes.
        shrunk = "package: foo\nessential:\n  - foo_copyright\nslices:\n  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"
        new = write(d, "new.yaml", shrunk)
        out = run("check-diff.py", old, new)
        assert "slice removed" in out, out

        out = run("check-diff.py", old, old)
        assert "ok:" in out, out


def test_scaffold_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        sdf = write(d, "foo.yaml", CLEAN)  # ships /usr/bin/foo in the bins slice.
        out = run("scaffold-test.py", str(sdf))
        assert (
            "install-slices foo_bins" in out and 'chroot "$rootfs" /usr/bin/foo' in out
        ), out
        task = write(d, "task.yaml", out)
        ct = run("check-test.py", str(sdf), str(task))
        assert "warn" in ct and "unfinished scaffold" in ct, ct


@pytest.mark.parametrize("contents", ["/usr/share/foo/data", "/usr/bin/*"])
def test_scaffold_marks_non_explicit_binary_tests(
    tmp_path: Path, contents: str
) -> None:
    sdf = write(tmp_path, "foo.yaml", CLEAN.replace("/usr/bin/foo", contents))
    scaffold = run("scaffold-test.py", sdf)
    task = write(tmp_path, "task.yaml", scaffold)
    assert "install-slices foo_bins" in scaffold, scaffold
    out = run("check-test.py", sdf, task)
    assert "warn" in out and "unfinished scaffold" in out, out


def test_scaffold_keeps_helpers_and_mixed_slices(tmp_path: Path) -> None:
    sdf = write(
        tmp_path,
        "foo.yaml",
        CLEAN.replace("/usr/bin/foo", "/usr/libexec/foo/helper").replace(
            "  copyright:\n",
            "  data:\n    contents:\n      /usr/share/foo/data:\n  copyright:\n",
        ),
    )
    out = run("scaffold-test.py", sdf)
    assert 'chroot "$rootfs" /usr/libexec/foo/helper' in out, out
    assert "install-slices foo_data" in out, out
    assert "install-slices foo_copyright" not in out, out


def test_robustness() -> None:
    # a PR-review bot runs on arbitrary diffs; the checkers must degrade
    # gracefully on malformed SDFs, never crash. each of these should produce a
    # block (or clean handling), never a Python traceback.
    cases = {
        "empty.yaml": "",
        "scalar.yaml": "just a string",
        "list.yaml": "- a\n- b\n",
        "wrongtypes.yaml": "package: [1, 2]\nslices: not-a-map\n",
        "numkey.yaml": "package: x\nslices:\n  bins:\n    contents:\n      123: {}\n",
        "badyaml.yaml": 'key: "unclosed\n',
    }
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for name, text in cases.items():
            for tool in ("check-slice.py", "check-test.py", "scaffold-test.py"):
                out = run(tool, write(d, name, text))
                assert "Traceback" not in out, f"{tool} crashed on {name}: {out}"


def test_orientation_edge_cases() -> None:
    # the port must keep the bash contract on inputs sed never tripped on: a
    # block-style suites: list (per-line regexes, no bleed into the next line),
    # a non-UTF-8 byte in a comment (no traceback), a dotfile in slices/ (not
    # counted, as ls does not), and a cwd containing a double quote (escaped, so
    # the first line still parses). remote discovery is pointed at a path that
    # does not exist so the run is hermetic and fast.
    import os

    import yaml

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / 'q"d'
        (d / "slices").mkdir(parents=True)
        (d / "slices" / "foo.yaml").write_text("package: foo\n", encoding="utf-8")
        (d / "slices" / ".gitkeep").write_text("", encoding="utf-8")
        (d / "chisel.yaml").write_bytes(
            b"format: v3\n# \xff\xfe not utf-8\narchives:\n  ubuntu:\n    version: '44.04'\n"
            b"    suites:\n      - foo\n      - foo-updates\nmaintenance:\n  end-of-life: 2999-01-01\n"
        )
        env = {**os.environ, "CHISEL_RELEASES_URL": str(Path(td) / "nowhere")}
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "orientation.py")],
            cwd=str(d),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        out = r.stdout + r.stderr
        assert r.returncode == 2, out
        doc = yaml.safe_load(out)
        assert doc["release discovery"]["status"] == "unavailable", out
        assert doc["release discovery"]["reasons"], out
        assert doc["working dir"].endswith('q"d'), out
        assert doc["suites"] is None, out  # block list: nothing on the key's own line
        assert doc["ubuntu version"] == "44.04", out
        assert doc["maintained"] is True, out
        assert doc["existing slices"] == 1, out
        assert doc["live releases"] == {}, out
