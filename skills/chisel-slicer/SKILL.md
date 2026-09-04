---
name: chisel-slicer
description: >-
  Author or review chisel slice definition files (SDFs) against canonical/chisel-releases.
  Command-per-file architecture.
  Commands: write-slice (author + test + commit), review-slice (read-only review).
  Use when user says "add slice", "write a chisel slice", "review slices/<pkg>.yaml",
  or works inside a canonical/chisel-releases checkout.
argument-hint: "[write-slice|review-slice] <pkg-or-sdf>"
---

# chisel-slicer

Skill for working on [`canonical/chisel-releases`](https://github.com/canonical/chisel-releases).

## Where things live

You work inside a checkout of `canonical/chisel-releases` -- your current working
directory. Every repo path you read or write -- `slices/<pkg>.yaml`,
`tests/spread/...`, `chisel.yaml`, sibling SDFs -- is relative to this checkout,
exactly as written.

Paths below (`commands/`, `shared/`, `scripts/`) are relative to this
skill's own directory instead -- the one holding this `SKILL.md`. They are
read-only. If a `scripts/` file will not run by path, run it through its interpreter -- **the extension tells you
which**: `orientation` and `try-cut` have none and are bash (`bash scripts/orientation`);
everything ending `.py` is python (`uv run --script scripts/check-slice.py`, or
`python3` with pyyaml available). Running a bash script under `python3` fails
with a `SyntaxError`.

## Layout

- `commands/` -- command workflows: markdown to read and follow, not executable scripts
- `shared/` -- reference material, one file per subject. Each stands alone; read the ones a step calls for.
  - `slice-definition-format.md` -- SDF format: top-level and per-slice keys, content entry options, wildcards, `mutate:`, arch-gated essentials, `hint:` style, arch names
  - `chisel-releases.md` -- branch model, per-branch layout, `chisel.yaml` schema versions
  - `slice-conventions.md` -- canonical slice names, path entry style, file layout, what to exclude by default
  - `cross-release-porting.md` -- cross-release differences, multiarch quirks
  - `spread-tests.md` -- spread layout, `install-slices`, chroot patterns, backends
  - `chisel-cli.md` -- `chisel` CLI, `--release` semantics, inspecting the repo without a checkout
  - `upstream-sources.md` -- upstream repos, doc page index, precedence when sources conflict
- `scripts/` -- runnable helpers: `orientation`, `deb-list.py` (inspect a .deb; `--sdf` emits a draft SDF), `try-cut`, `scaffold-test.py` (emit a spread test skeleton), `check-slice.py` (deterministic SDF linter), `check-test.py` (binary test-coverage check), `check-diff.py` (append-only regression check), `review-diff.py` (runs all three over a PR diff)

## Orient first

Before anything else, run `scripts/orientation [<package>]`. It prints --
deterministically -- your working dir, this skill's own dir, the target release
+ manifest format parsed from `chisel.yaml`, and which tools are available here
(`chisel`, `dpkg-deb`, `spread`, `uv`, ...) so you know upfront what you can run.
Treat its output as ground truth; don't infer any of it. Then read
`shared/slice-definition-format.md` and `shared/chisel-releases.md` before
touching an SDF; pull the other `shared/` files in as a step calls for them.

## Commands

`write-slice` and `review-slice` are **not** standalone slash commands -- only `/chisel-slicer` is registered. select a command from the invocation:

- `/chisel-slicer write-slice <pkg>` (the first arg names the command), or
- plain language: "write a slice for `<pkg>`", "review `slices/foo.yaml`".

dispatch: if the first token of the args names a command below, read that file and follow its steps, treating the rest of the args as its input. otherwise read the args as plain language and match on intent -- authoring / adding / writing / forward-porting a slice or SDF goes to `write-slice`, reviewing an existing one goes to `review-slice`. on no args at all, or intent that matches neither, print the numbered list below and wait for the user's reply before loading anything -- never guess.

1. `write-slice` -> `commands/write-slice.md` -- author + test + commit SDFs. does not open PRs.
2. `review-slice` -> `commands/review-slice.md` -- read-only review of SDFs.
