# mason

agent kit for chisel / rocks work. a cross-agent skill bundle, portable across claude code, pi, opencode, copilot, and codex.

each capability area is its own skill under `skills/`. today there are two: `mason` (the `/mason` entry point -- routes a request to the right skill, or prints usage) and the substance:

## chisel-slicer

working on [`canonical/chisel-releases`](https://github.com/canonical/chisel-releases). command-per-file; commands:

- **`write-slice`** -- authors + tests + commits chisel slice definition files (SDFs). does not open PRs.
- **`review-slice`** -- read-only review of SDFs against chisel conventions, CI checks, and forward-port rules.

@./skills/chisel-slicer/SKILL.md

lives under `./skills/chisel-slicer/`: `commands/`, helpers under `scripts/`, command index `schemas/commands.manifest.yaml`, and shared reference `shared/CHISEL.md`. paths inside command files are relative to the skill's own directory (or, for repo paths like `slices/`, to the chisel-releases checkout being worked on).

`shared/CHISEL.md` is a generated copy -- the source of truth is `./_shared/CHISEL.md`. each skill lists the `_shared/` files it ships in its `shared.list`; `make sync-shared` (`scripts/sync-shared.py`) copies them into `<skill>/shared/` with a "generated" banner, and the copies are committed so every installer ships a self-contained skill. edit `_shared/`, run `make sync-shared`, commit both; `make check-shared` in ci fails on drift.

the deterministic scripts are the backbone, so the commands don't rely on the agent remembering conventions or hand-rolling boilerplate:

- **inspect / author**: `orientation` (where am i, which release/format, which tools are available), `deb-list.py` (files + deps inside a .deb; `--sdf` groups them into a draft SDF -- bins/libs/config/headers/var/copyright, clutter dropped, multiarch dirs globbed, copyright wired (incl. shared-copyright doc-dir symlinks), sorted, ambiguous files left as unplaced comments -- as a deterministic starting point the author refines), `try-cut` (chisel cut into a temp root), `scaffold-test.py` (emit a spread `task.yaml` skeleton -- one fresh rootfs per binary-bearing slice, a chroot line per declared binary, so the author fills real functional checks not boilerplate).
- **check**: `check-slice.py` (static conventions: sorting, naming, absolute paths, copyright presence, clutter exclusion, arch names, version-gated fields, hint length/style), `check-test.py` (binary test coverage: warns on no test or a test exercising none of the binaries, else an info summary of untested binaries), `check-diff.py` (append-only regressions -- removed SDF / slice / path -- the `removed-slices` CI gate; file-pair or `--base <ref>` via git).
- **assemble**: `review-diff.py --base <ref>` finds the changed SDFs in a diff, runs the three checkers, prints findings by severity with a verdict, exits non-zero on any `block`. this is the CI-callable PR-review bot; it needs no agent.

`write-slice` drafts the SDF and its tests then self-checks with the checkers before commit; `review-slice` leads with `review-diff.py`; together they're the engine for a future chisel-releases PR-review bot. the generators round-trip with the checkers by construction -- a fresh `deb-list.py --sdf` passes `check-slice.py`, a fresh `scaffold-test.py` reports full coverage under `check-test.py`. static-check rule sets are kept in sync with the eval scorers under `tests/skills/scorers/` (shared vocab like the canonical slice-name set lives in both). the scripts have a pytest regression net at `tests/scripts/test_checks.py` (`make test`); they're load-bearing, so keep it green. the checkers stay empirically clean against the real merged corpus on `ubuntu-24.04` (v1) and `ubuntu-26.04` (v3) -- 0 false-positive blocks.

`tests/` splits by what's under test: `tests/skills/` is the pats eval (agents run through the skill in docker, scored by the `scorers/`); `tests/scripts/` is pytest unit tests of the scripts that ship with the skill. `make verify` = `lint` (ruff) + `check-shared` + `test`, the same set ci runs.

## install

`mason` is a tessl plugin (`.tessl-plugin/plugin.json`; skills discovered from `skills/`): `npx tessl i canonical/mason --skill chisel-slicer`. the same tree installs via `npx skills add`, `gh skill install`, and the claude code marketplace (`.claude-plugin/`) -- see README. there is no installer of our own any more; a skill has to be self-contained (hence `_shared/` + `sync-shared`). adding a capability = a new skill dir under `skills/`, name equal to the dir, `SKILL.md` frontmatter per agentskills.io.

the version is `.tessl-plugin/plugin.json`'s (mirror in `.claude-plugin/plugin.json`); releasing = bump, tag, `npx tessl plugin publish .` (README "releasing").
