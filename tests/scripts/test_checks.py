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
import yaml

SCRIPTS = Path(__file__).resolve().parents[2] / "_shared"
EXIT = {"passed": 0, "failed": 1, "unavailable": 3}


def run(script: str, *args: str) -> str:
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout + r.stderr


def report(script: str, *args: str, **kwargs) -> tuple[int, dict]:
    """Run a helper and return its exit code and its document, checked against
    the output contract in _shared/common.py."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        check=False,
        **kwargs,
    )
    assert "Traceback" not in r.stderr, r.stderr
    doc = yaml.safe_load(r.stdout)
    assert isinstance(doc, dict) and doc.get("status") in EXIT, r.stdout + r.stderr
    assert r.returncode == EXIT[doc["status"]], (r.returncode, r.stdout)
    for items in (doc.get("findings") or {}).values():
        for item in items:
            assert item["sev"] in ("block", "warn", "info"), item
            assert item["code"] in doc["codes"], item
    if doc["status"] == "unavailable":
        assert doc["unavailable"], doc
    return r.returncode, doc


def found(doc: dict, sev: str | None = None) -> list[dict]:
    """Every finding, with its file folded in, optionally of one severity."""
    return [
        {"file": file, **item}
        for file, items in (doc.get("findings") or {}).items()
        for item in items
        if sev in (None, item["sev"])
    ]


def codes(doc: dict, sev: str | None = None) -> set[str]:
    return {f["code"] for f in found(doc, sev)}


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

        def lint(text: str, fmt: str, name: str = "foo.yaml") -> dict:
            return report("check-slice.py", write(d, name, text), "--format", fmt)[1]

        # list-form essential is the v1/v2 shape; the map form is v3's.
        for text, fmt in ((CLEAN, "1"), (CLEAN_V3, "3")):
            doc = lint(text, fmt)
            assert doc["status"] == "passed" and not found(doc), doc
        # COVER: shape-vs-format gates both ways -- list on v3 and map on v1 are
        # chisel parse errors the linter must block.
        assert "essential-list" in codes(lint(CLEAN, "3"), "block")
        assert "essential-map" in codes(lint(CLEAN_V3, "1"), "block")

        doc = lint(DIRTY, "1")
        unsorted = {f["field"] for f in found(doc, "block") if f["code"] == "unsorted"}
        assert unsorted == {"contents", "essential"}, doc
        assert any(
            f["code"] == "clutter" and f["path"] == "/usr/share/man/man1/foo.1"
            for f in found(doc, "warn")
        ), doc
        # chisel does not gate hint: on format -- it is branch convention, so a
        # v1 branch gets a warning, never a block.
        assert "hint-format" in codes(doc, "warn"), doc
        assert not any(f.get("field") == "hint" for f in found(doc, "block")), doc

        # COVER: the path-shape rules chisel enforces at parse time. each is a
        # block on its own, and none of them fire on a well-formed path.
        def path_sdf(entry: str) -> str:
            return (
                "package: foo\nessential:\n  foo_copyright:\nslices:\n  bins:\n"
                f"    contents:\n      {entry}\n"
                "  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"
            )

        for entry, expected in [
            ("/usr/bin/*: {mode: 0755}", "glob-options"),
            ("/usr/lib/foo: {make: true}", "make-path"),
            (
                "/var/lib/chisel/**: {generate: manifest, until: mutate}",
                "generate-options",
            ),
            ("/var/lib/chisel/*/**: {generate: manifest}", "generate-path"),
            ("/x: {prefer: foo}", "prefer-self"),
        ]:
            assert expected in codes(lint(path_sdf(entry), "3"), "block"), entry

        for entry in [
            "/usr/bin/*: {arch: [amd64]}",
            "/usr/lib/foo/: {make: true}",
            "/var/lib/chisel/**: {generate: manifest}",
            "/x: {prefer: otherpkg}",
        ]:
            assert not found(lint(path_sdf(entry), "3"), "block"), entry

        # base-files really does own bin/ and lib/ -- exempt from the name warning.
        bf = (
            "package: base-files\nessential:\n  base-files_copyright:\nslices:\n"
            "  bin:\n    contents:\n      /bin:\n"
            "  copyright:\n    contents:\n      /usr/share/doc/base-files/copyright:\n"
        )
        assert "slice-name" not in codes(lint(bf, "3", "base-files.yaml"))

        # filename must match package.
        mismatch = [
            f
            for f in found(lint(CLEAN, "3", "bar.yaml"), "block")
            if f["code"] == "package-mismatch"
        ]
        assert mismatch and mismatch[0]["package"] == "foo", mismatch
        assert mismatch[0]["file-stem"] == "bar", mismatch

        # hint validation (v3): a good hint is clean; length/style are checked.
        def hint_sdf(h):
            return f"package: foo\nessential:\n  foo_copyright:\nslices:\n  bins:\n    hint: {h}\n    contents:\n      /usr/bin/foo:\n  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"

        assert not found(lint(hint_sdf("System log viewer"), "3"))
        doc = lint(hint_sdf("The tool that manages absolutely everything here."), "3")
        assert "hint-too-long" in codes(doc, "block"), doc  # a parse error
        assert any(
            f["code"] == "hint-style" and f["rule"] == "article"
            for f in found(doc, "warn")
        ), doc

        # v3-essential is a v1/v2 backport; a chisel parse error on v3.
        v3e = "package: foo\nslices:\n  bins:\n    v3-essential:\n      libc6_libs: {arch: [amd64]}\n    contents:\n      /usr/bin/foo:\n  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"
        assert "v3-essential" in codes(lint(v3e, "3"), "block")
        # ...but fine on v1 (no finding).
        assert "v3-essential" not in codes(lint(v3e, "1"))


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

        def lint(branch: str) -> dict:
            return report(
                "check-slice.py", "foo.yaml", "--branch", branch, cwd=str(d), env=env
            )[1]

        # v3 resolved from the committed chisel.yaml -> list-form essential blocks.
        assert "essential-list" in codes(lint("ubuntu-99.10"), "block")
        # an unknown ref resolves to no format -> the gated checks cannot run.
        doc = lint("ubuntu-00.00")
        assert "essential-list" not in codes(doc), doc
        assert doc["status"] == "unavailable", doc
        assert [u["check"] for u in doc["unavailable"]] == ["format"], doc


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

        _, doc = report(
            "check-slice.py",
            "foo.yaml",
            "--branch",
            "ubuntu-88.04",
            cwd=str(clone),
            env=env,
        )
        # v3 resolved via origin/ubuntu-88.04 -> list-form essential blocks.
        assert "essential-list" in codes(doc, "block"), doc


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
        assert doc["status"] == "passed", out
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
        _, doc = report("check-test.py", sdf, exercised)
        assert doc["status"] == "passed" and not found(doc), doc

        # a test that touches none of the binaries is the red flag (warn).
        missing = write(d, "empty.yaml", "summary: x\nexecute: |\n  true\n")
        _, doc = report("check-test.py", sdf, missing)
        assert "untested" in codes(doc, "warn"), doc

        # partial coverage is advisory (info), not a warn: two bins, one tested.
        two = "package: foo\nessential:\n  - foo_copyright\nslices:\n  bins:\n    contents:\n      /usr/bin/foo:\n      /usr/bin/zzz:\n  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"
        sdf2 = write(d, "foo2.yaml", two)
        one = write(
            d, "one.yaml", 'summary: x\nexecute: |\n  chroot "$r" foo --version\n'
        )
        _, doc = report("check-test.py", sdf2, one)
        partial = [f for f in found(doc, "info") if f["code"] == "partly-tested"]
        assert partial and partial[0]["unreferenced"] == ["zzz"], doc
        assert (partial[0]["referenced"], partial[0]["declared"]) == (1, 2), doc
        assert not found(doc, "warn"), doc


@pytest.mark.parametrize(
    "contents", ["/usr/share/foo/data", "/usr/lib/libfoo.so.1", "/usr/bin/*"]
)
def test_check_test_requires_task_without_explicit_binaries(
    tmp_path: Path, contents: str
) -> None:
    sdf = write(tmp_path, "foo.yaml", CLEAN.replace("/usr/bin/foo", contents))
    _, doc = report("check-test.py", sdf, str(tmp_path / "missing.yaml"))
    assert "no-test" in codes(doc, "warn"), doc


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
    _, doc = report("check-test.py", sdf, write(tmp_path, "task.yaml", task))
    assert "task-invalid" in codes(doc, "warn"), doc


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
    assert "untested" in codes(report("check-test.py", sdf, task)[1], "warn")
    write(tmp_path, "test.sh", "# foo\ntrue # foo\n")
    assert "untested" in codes(report("check-test.py", sdf, task)[1], "warn")
    write(tmp_path, "test.sh", 'chroot "$rootfs" /usr/bin/foo --version\n')
    task = write(tmp_path, "task.yaml", "summary: x\nexecute: ./test.sh\n")
    assert not found(report("check-test.py", sdf, task)[1])


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
    _, doc = report("check-test.py", sdf, task)
    assert "no-binaries" in codes(doc, "info"), doc
    assert not found(doc, "warn"), doc


def test_check_test_reports_unreadable_helper(tmp_path: Path) -> None:
    sdf = write(tmp_path, "foo.yaml", CLEAN)
    task = write(tmp_path, "task.yaml", "summary: x\nexecute: ./test.sh\n")
    (tmp_path / "test.sh").write_bytes(b"\xff")
    _, doc = report("check-test.py", sdf, task)
    assert "task-invalid" in codes(doc, "warn"), doc


def test_check_diff() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        old = write(d, "old.yaml", CLEAN)
        # drop the whole bins slice -> both slice-removed and path-removed shapes.
        shrunk = "package: foo\nessential:\n  - foo_copyright\nslices:\n  copyright:\n    contents:\n      /usr/share/doc/foo/copyright:\n"
        new = write(d, "new.yaml", shrunk)
        _, doc = report("check-diff.py", old, new)
        assert "slice-removed" in codes(doc, "warn"), doc

        _, doc = report("check-diff.py", old, old)
        assert doc["status"] == "passed" and not found(doc), doc


SPLIT_BASE = """\
package: foo
essential:
  foo_copyright:
slices:
  bins:
    essential:
      libc6_libs:
    contents:
      /usr/bin/foo:
      /usr/bin/foo-helper:
  copyright:
    contents:
      /usr/share/doc/foo/copyright:
"""


def split(bins_essential: str, extra_slices: str = "") -> str:
    """SPLIT_BASE with /usr/bin/foo-helper gone from bins' own contents."""
    return f"""\
package: foo
essential:
  foo_copyright:
slices:
  bins:
    essential:
      libc6_libs:
{bins_essential}    contents:
      /usr/bin/foo:
{extra_slices}  copyright:
    contents:
      /usr/share/doc/foo/copyright:
"""


HELPER = """\
  helper:
    contents:
      /usr/bin/foo-helper:
"""


def diff(tmp_path: Path, old: str, new: str) -> dict:
    return report(
        "check-diff.py",
        write(tmp_path, "old.yaml", old),
        write(tmp_path, "new.yaml", new),
    )[1]


# a path that moved into a slice the old one still depends on is still installed
# by it: that is how a published slice gets subdivided, not a regression.
@pytest.mark.parametrize(
    ("new", "owner"),
    [
        pytest.param(split("      foo_helper:\n", HELPER), "foo_helper", id="subslice"),
        pytest.param(
            split(
                "      foo_a:\n",
                "  a:\n    essential:\n      foo_helper:\n" + HELPER,
            ),
            "foo_helper",
            id="transitive",
        ),
        pytest.param(
            split("").replace(
                "      /usr/share/doc/foo/copyright:\n",
                "      /usr/bin/foo-helper:\n      /usr/share/doc/foo/copyright:\n",
            ),
            "foo_copyright",
            id="package-wide-essential",
        ),
        pytest.param(
            split(
                "      foo_a:\n",
                "  a:\n    essential:\n      foo_b:\n"
                "  b:\n    essential:\n      foo_a:\n"
                "    contents:\n      /usr/bin/foo-helper:\n",
            ),
            "foo_b",
            id="essential-cycle",
        ),
    ],
)
def test_check_diff_path_moved_to_essential(
    tmp_path: Path, new: str, owner: str
) -> None:
    doc = diff(tmp_path, SPLIT_BASE, new)
    assert not found(doc, "warn"), doc
    [moved] = found(doc, "info")
    assert moved["code"] == "moved" and moved["file"].endswith("new.yaml"), doc
    assert (moved["slice"], moved["path"], moved["to"]) == (
        "bins",
        "/usr/bin/foo-helper",
        owner,
    ), doc


def test_check_diff_path_moved_to_essential_list_form(tmp_path: Path) -> None:
    # v1/v2 list-form essentials resolve the same way as v3's map
    old = SPLIT_BASE.replace("  foo_copyright:", "  - foo_copyright").replace(
        "      libc6_libs:", "      - libc6_libs"
    )
    new = (
        split("      - foo_helper\n", HELPER)
        .replace("  foo_copyright:", "  - foo_copyright")
        .replace("      libc6_libs:", "      - libc6_libs")
    )
    doc = diff(tmp_path, old, new)
    assert not found(doc, "warn"), doc
    assert [(f["code"], f["to"]) for f in found(doc, "info")] == [
        ("moved", "foo_helper")
    ]


# the path is no longer installed with the slice, on every arch or at all, or
# only another package could still ship it: each stays a regression.
@pytest.mark.parametrize(
    "new",
    [
        pytest.param(split(""), id="dropped"),
        pytest.param(split("", HELPER), id="sibling-not-depended-on"),
        pytest.param(
            split("      foo_helper: {arch: [amd64]}\n", HELPER),
            id="arch-limited-essential",
        ),
        pytest.param(split("      bar_helper:\n"), id="other-package"),
        pytest.param(split("      foo_typo:\n", HELPER), id="dangling-essential"),
        pytest.param(
            split(
                "      foo_helper:\n",
                HELPER.replace("foo-helper:", "foo-helper: {arch: [amd64]}"),
            ),
            id="arch-limited-content",
        ),
        pytest.param(
            split(
                "      foo_helper:\n",
                HELPER.replace("foo-helper:", "foo-helper: {until: mutate}"),
            ),
            id="until-mutate",
        ),
    ],
)
def test_check_diff_path_removed(tmp_path: Path, new: str) -> None:
    doc = diff(tmp_path, SPLIT_BASE, new)
    [removed] = found(doc, "warn")
    assert (removed["code"], removed["path"]) == ("removed", "/usr/bin/foo-helper"), doc
    assert not found(doc, "info"), doc


@pytest.mark.parametrize(
    ("old_arch", "new_arch", "moved"),
    [
        pytest.param("[amd64]", "[amd64]", True, id="same-arches"),
        pytest.param("amd64", "[amd64, arm64]", True, id="more-arches"),
        pytest.param("[amd64, arm64]", "[amd64]", False, id="fewer-arches"),
    ],
)
def test_check_diff_arch_limited_path_moved(
    tmp_path: Path, old_arch: str, new_arch: str, moved: bool
) -> None:
    # an arch-limited path only has to stay installed on the arches it had
    old = SPLIT_BASE.replace("foo-helper:", f"foo-helper: {{arch: {old_arch}}}")
    new = split(
        "      foo_helper:\n",
        HELPER.replace("foo-helper:", f"foo-helper: {{arch: {new_arch}}}"),
    )
    doc = diff(tmp_path, old, new)
    if moved:
        assert codes(doc) == {"moved"} and len(found(doc)) == 1, doc
    else:
        assert codes(doc) == {"removed"} and len(found(doc)) == 1, doc


# a path kept in its slice can still stop being installed where it was
@pytest.mark.parametrize(
    ("old_opts", "new_opts", "narrowed"),
    [
        pytest.param("", " {arch: [amd64]}", True, id="arch-added"),
        pytest.param(
            " {arch: [amd64, arm64]}", " {arch: amd64}", True, id="arch-dropped"
        ),
        pytest.param("", " {until: mutate}", True, id="until-mutate-added"),
        pytest.param(" {arch: [amd64]}", "", False, id="arch-lifted"),
        pytest.param(" {arch: amd64}", " {arch: [amd64]}", False, id="arch-respelt"),
        pytest.param(" {until: mutate}", " {until: mutate}", False, id="until-kept"),
        pytest.param(" {until: mutate}", "", False, id="until-lifted"),
        pytest.param("", ' {until: ""}', False, id="until-empty"),
    ],
)
def test_check_diff_entry_narrowed_in_place(
    tmp_path: Path, old_opts: str, new_opts: str, narrowed: bool
) -> None:
    old = SPLIT_BASE.replace("foo-helper:", f"foo-helper:{old_opts}")
    new = SPLIT_BASE.replace("foo-helper:", f"foo-helper:{new_opts}")
    doc = diff(tmp_path, old, new)
    if narrowed:
        [hit] = found(doc, "warn")
        assert (hit["code"], hit["path"]) == ("narrowed", "/usr/bin/foo-helper"), doc
        assert hit["was"] == (yaml.safe_load(old_opts) or {}), doc
        assert hit["now"] == (yaml.safe_load(new_opts) or {}), doc
    else:
        assert doc["status"] == "passed" and not found(doc), doc


def test_check_diff_entry_narrowed_but_covered_by_essential(tmp_path: Path) -> None:
    # the arches bins stops shipping itself, a slice it depends on still does
    new = split("      foo_helper:\n", HELPER).replace(
        "      /usr/bin/foo:\n",
        "      /usr/bin/foo:\n      /usr/bin/foo-helper: {arch: [amd64]}\n",
    )
    doc = diff(tmp_path, SPLIT_BASE, new)
    assert not found(doc, "warn"), doc
    assert [(f["code"], f["to"]) for f in found(doc, "info")] == [
        ("moved", "foo_helper")
    ]


def test_check_diff_until_empty_still_covers(tmp_path: Path) -> None:
    # until: "" is chisel's default, the path stays in the rootfs
    new = split(
        "      foo_helper:\n", HELPER.replace("foo-helper:", 'foo-helper: {until: ""}')
    )
    doc = diff(tmp_path, SPLIT_BASE, new)
    assert codes(doc) == {"moved"} and len(found(doc)) == 1, doc


def test_check_diff_base_mode(tmp_path: Path) -> None:
    # --base reads the old SDF from git and the new one from the worktree
    import os

    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }

    def git(*a: str) -> None:
        subprocess.run(
            [
                "git",
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
            cwd=tmp_path,
            check=True,
            capture_output=True,
            env=env,
        )

    def check_diff() -> dict:
        return report("check-diff.py", "--base", "HEAD", cwd=tmp_path, env=env)[1]

    sdf = tmp_path / "slices" / "foo.yaml"
    sdf.parent.mkdir()
    sdf.write_text(SPLIT_BASE, encoding="utf-8")
    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "base")

    sdf.write_text(split("      foo_helper:\n", HELPER), encoding="utf-8")
    doc = check_diff()
    assert not found(doc, "warn"), doc
    assert [(f["file"], f["slice"], f["to"]) for f in found(doc, "info")] == [
        ("slices/foo.yaml", "bins", "foo_helper")
    ], doc

    sdf.write_text(split(""), encoding="utf-8")
    doc = check_diff()
    assert [(f["file"], f["slice"], f["code"]) for f in found(doc, "warn")] == [
        ("slices/foo.yaml", "bins", "removed")
    ], doc


def test_scaffold_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        sdf = write(d, "foo.yaml", CLEAN)  # ships /usr/bin/foo in the bins slice.
        out = run("scaffold-test.py", str(sdf))
        assert (
            "install-slices foo_bins" in out and 'chroot "$rootfs" /usr/bin/foo' in out
        ), out
        task = write(d, "task.yaml", out)
        _, doc = report("check-test.py", str(sdf), str(task))
        assert "scaffold" in codes(doc, "warn"), doc


@pytest.mark.parametrize("contents", ["/usr/share/foo/data", "/usr/bin/*"])
def test_scaffold_marks_non_explicit_binary_tests(
    tmp_path: Path, contents: str
) -> None:
    sdf = write(tmp_path, "foo.yaml", CLEAN.replace("/usr/bin/foo", contents))
    scaffold = run("scaffold-test.py", sdf)
    task = write(tmp_path, "task.yaml", scaffold)
    assert "install-slices foo_bins" in scaffold, scaffold
    _, doc = report("check-test.py", sdf, task)
    assert "scaffold" in codes(doc, "warn"), doc


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
        clean = write(d, "foo.yaml", CLEAN)
        for name, text in cases.items():
            path = write(d, name, text)
            for tool in ("check-slice.py", "check-test.py"):
                report(tool, path)  # checks the contract, tracebacks included
            report("check-diff.py", clean, path)
            out = run("scaffold-test.py", path)
            assert "Traceback" not in out, f"scaffold-test.py crashed on {name}: {out}"


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
        assert r.returncode == 3, out
        doc = yaml.safe_load(r.stdout)
        assert doc["status"] == "unavailable", out
        assert {u["check"] for u in doc["unavailable"]} == {"release discovery"}, out
        assert doc["working dir"].endswith('q"d'), out
        assert doc["suites"] is None, out  # block list: nothing on the key's own line
        assert doc["ubuntu version"] == "44.04", out
        assert doc["maintained"] is True, out
        assert doc["existing slices"] == 1, out
        assert doc["live releases"] == {}, out
