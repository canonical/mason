"""pytest regression net for scripts/sync-shared.py.

Builds a throwaway repo (a _shared/ dir, a skills/ dir, a root .shared.yaml, the
real script) in a tmpdir and drives the script's CLI against it, so this tests
the real thing rather than imported internals. Like test_checks.py, the
subprocessed script needs pyyaml under the runner's interpreter. Run:

    uv run --with pyyaml --with pytest pytest tests/scripts/
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REAL = Path(__file__).resolve().parents[2] / "scripts/sync-shared.py"

# the smallest well-formed manifest: one skill, one source, one destination.
ONE_A = "shared:\n  one:\n    a.md:\n      path: shared/a.md\n"


def make_repo(d: Path, shared: dict[str, str], manifest: str, skills=("one",)) -> Path:
    """A minimal repo: _shared/ files, skills/<name>/SKILL.md, root .shared.yaml."""
    (d / "scripts").mkdir(parents=True)
    shutil.copy(REAL, d / "scripts/sync-shared.py")
    (d / "_shared").mkdir()
    for name, text in shared.items():
        (d / "_shared" / name).write_text(text, encoding="utf-8")
    for skill in skills:
        sd = d / "skills" / skill
        sd.mkdir(parents=True)
        (sd / "SKILL.md").write_text(f"# {skill}\n", encoding="utf-8")
    (d / ".shared.yaml").write_text(manifest, encoding="utf-8")
    return d


def sync(d: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(d / "scripts/sync-shared.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode, r.stdout + r.stderr


def test_destination_is_a_path_not_a_convention() -> None:
    """A copy lands wherever the manifest says -- nested, renamed, or at the root."""
    with tempfile.TemporaryDirectory() as td:
        d = make_repo(
            Path(td),
            {"a.md": "alpha\n", "b.md": "bravo\n", "c.md": "charlie\n"},
            "shared:\n"
            "  one:\n"
            "    a.md:\n      path: shared/a.md\n"  # under shared/
            "    b.md:\n      path: reference/deep/renamed.md\n"  # nested + renamed
            "    c.md:\n",  # no entry body -> same relative path
        )
        rc, out = sync(d)
        assert rc == 0, out
        skill = d / "skills/one"
        # a copy is byte-for-byte its source -- nothing added, since it ships
        assert (skill / "shared/a.md").read_text() == "alpha\n"
        assert (skill / "reference/deep/renamed.md").read_text() == "bravo\n"
        assert (skill / "c.md").read_text() == "charlie\n"
        assert sync(d, "--check")[0] == 0


def test_nothing_of_the_tool_lands_in_the_skill() -> None:
    """COVER: the skill dir holds only what ships -- no listing file beside the
    copies, and no marker inside one."""
    with tempfile.TemporaryDirectory() as td:
        d = make_repo(Path(td), {"a.md": "alpha\n"}, ONE_A)
        assert sync(d)[0] == 0
        names = {p.name for p in (d / "skills/one").rglob("*")}
        assert names == {"SKILL.md", "shared", "a.md"}
        assert (d / "skills/one/shared/a.md").read_bytes() == b"alpha\n"


def test_retarget_moves_the_copy_and_prunes_the_dir() -> None:
    """COVER: the generated block is what makes a copy removable -- changing a
    destination moves the file rather than leaving an orphan at the old path."""
    with tempfile.TemporaryDirectory() as td:
        d = make_repo(Path(td), {"a.md": "alpha\n"}, ONE_A)
        assert sync(d)[0] == 0
        assert (d / "skills/one/shared/a.md").exists()

        (d / ".shared.yaml").write_text(
            "shared:\n  one:\n    a.md:\n      path: docs/a.md\n", encoding="utf-8"
        )
        rc, out = sync(d)
        assert rc == 0, out
        assert "removed" in out and "wrote" in out
        assert (d / "skills/one/docs/a.md").exists()
        assert not (d / "skills/one/shared/a.md").exists()
        assert not (d / "skills/one/shared").exists()  # emptied dir pruned


def test_dropping_an_entry_removes_the_copy() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_repo(
            Path(td),
            {"a.md": "alpha\n", "b.md": "bravo\n"},
            ONE_A + "    b.md:\n      path: shared/b.md\n",
        )
        assert sync(d)[0] == 0
        (d / ".shared.yaml").write_text(ONE_A, encoding="utf-8")
        assert sync(d)[0] == 0
        assert (d / "skills/one/shared/a.md").exists()
        assert not (d / "skills/one/shared/b.md").exists()


def test_a_leftover_whose_source_changed_too_is_not_seen() -> None:
    """The known blind spot: a copy is recognised by matching a _shared/ source
    byte for byte, so one that moved in the same change that rewrote its source
    matches nothing and survives. Syncing after a plain retarget catches it."""
    with tempfile.TemporaryDirectory() as td:
        d = make_repo(Path(td), {"a.md": "alpha\n"}, ONE_A)
        assert sync(d)[0] == 0
        (d / "_shared/a.md").write_text("alpha rewritten\n", encoding="utf-8")
        (d / ".shared.yaml").write_text(
            "shared:\n  one:\n    a.md:\n      path: docs/a.md\n", encoding="utf-8"
        )
        assert sync(d)[0] == 0
        assert (d / "skills/one/docs/a.md").read_text() == "alpha rewritten\n"
        assert (d / "skills/one/shared/a.md").exists()  # the blind spot


def test_a_hand_written_skill_file_is_left_alone() -> None:
    """COVER: the sweep keys on content, so it must not touch a skill's own
    files -- only ones that duplicate a _shared/ source."""
    with tempfile.TemporaryDirectory() as td:
        d = make_repo(Path(td), {"a.md": "alpha\n"}, ONE_A)
        own = d / "skills/one/notes.md"
        own.write_text("mine, not shared\n", encoding="utf-8")
        assert sync(d)[0] == 0
        assert own.read_text() == "mine, not shared\n"
        assert sync(d, "--check")[0] == 0


def test_check_reports_drift_without_writing() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_repo(Path(td), {"a.md": "alpha\n"}, ONE_A)
        rc, out = sync(d, "--check")
        assert rc == 1 and "missing" in out
        assert not (d / "skills/one/shared/a.md").exists()  # --check writes nothing

        assert sync(d)[0] == 0
        (d / "_shared/a.md").write_text("alpha changed\n", encoding="utf-8")
        rc, out = sync(d, "--check")
        assert rc == 1 and "differs" in out


def test_the_manifest_is_never_written_to() -> None:
    """COVER: nothing is machine-generated, so a sync leaves the manifest --
    comments, ordering and all -- exactly as the author wrote it."""
    with tempfile.TemporaryDirectory() as td:
        text = "# keep me\n" + ONE_A
        d = make_repo(Path(td), {"a.md": "alpha\n"}, text)
        assert sync(d)[0] == 0
        assert (d / ".shared.yaml").read_text() == text
        assert sync(d)[0] == 0
        assert (d / ".shared.yaml").read_text() == text


def test_bad_manifests_are_rejected() -> None:
    cases = [
        (
            "shared:\n  one:\n    a.md:\n      path: ../../escape.md\n",
            "must stay inside",
        ),
        ("shared:\n  one:\n    a.md:\n      path: /abs.md\n", "must stay inside"),
        (
            (
                "shared:\n  one:\n    a.md:\n      path: shared/x.md\n"
                "    b.md:\n      path: shared/x.md\n"
            ),
            "both target",
        ),
        (
            "shared:\n  one:\n    missing.md:\n      path: shared/m.md\n",
            "does not exist",
        ),
        ("shared:\n  nope:\n    a.md:\n", "is not a skill"),
        ("one:\n  a.md:\n    path: shared/a.md\n", "unknown top-level key"),
        ("shared:\n  one:\n    a.md: shared/a.md\n", "must be a map"),
        ("shared:\n  one:\n    a.md:\n      dest: shared/a.md\n", "unknown key"),
    ]
    for manifest, expected in cases:
        with tempfile.TemporaryDirectory() as td:
            d = make_repo(Path(td), {"a.md": "alpha\n", "b.md": "bravo\n"}, manifest)
            rc, out = sync(d)
            assert rc != 0, (manifest, out)
            assert expected in out, (manifest, out)
