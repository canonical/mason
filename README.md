# mason

<img src="assets/logo2.png" alt="Mason logo" align="right" width="300">

![WIP](https://img.shields.io/badge/%E2%9A%A0%EF%B8%8F%20work%20in%20progress%20%20%E2%9A%A0%EF%B8%8F-ffffff)

[![Ubuntu](https://img.shields.io/badge/Ubuntu-E95420?logo=ubuntu&logoColor=white)](#)
[![rocks](https://img.shields.io/badge/%F0%9F%AA%A8-rocks-E95420)](https://ubuntu.com/server/docs/explanation/virtualisation/about-rock-images/)
[![test](https://github.com/canonical/mason/actions/workflows/test.yml/badge.svg)](https://github.com/canonical/mason/actions/workflows/test.yml)
[![tessl](https://img.shields.io/endpoint?url=https%3A%2F%2Fapi.tessl.io%2Fv1%2Fbadges%2Fcanonical%2Fmason)](https://tessl.io/registry/canonical/mason)

Tribal knowledge about [`rocks`](https://documentation.ubuntu.com/rockcraft/stable/explanation/rocks/), [`rockcraft`](https://documentation.ubuntu.com/rockcraft/latest/), [`chisel`](https://github.com/canonical/chisel), [`chisel-releases`](https://github.com/canonical/chisel-releases), and slice definition files (SDFs).

Install with:

```
npx tessl i canonical/mason --skill chisel-slicer
```

_(see below for detailed instructions)_

and then, for example, write a new SDF file:

```
git clone https://github.com/canonical/chisel-releases.git && cd chisel-releases
git checkout ubuntu-26.04 && git checkout -b feat/my-new-slice
<in your coding agent>
/mason "please help me write an sdf for foobar"
```

## install

`mason` is a [tessl](https://tessl.io) plugin: one registry entry
([`canonical/mason`](https://tessl.io/registry/canonical/mason)), several skills, pick the
ones you want. No clone, no npm publish:

```
npx tessl i canonical/mason --skill chisel-slicer             # into the current repo
npx tessl i canonical/mason --skill chisel-slicer --global    # into ~/.tessl, for every repo
npx tessl i canonical/mason@0.2.0 --skill chisel-slicer       # pinned
npx tessl i canonical/mason                                   # no --skill: pick interactively
```

tessl keeps one copy of the plugin (`.tessl/plugins/`, or `~/.tessl/` with `--global`) and
symlinks each chosen skill into the discovery directory of every agent it detects -- claude
code, codex, copilot, cursor, gemini, ... (`--agent <id>` to choose). opencode and pi read
`.agents/skills/` and `.claude/skills/` natively, so `--agent agents` covers them. A
project-level install also writes `tessl.json`; use `--global` when the target checkout is not
yours to commit to (a `chisel-releases` clone, say).

The layout is a plain `skills/<name>/SKILL.md` tree, so the other installers work too:

```
npx skills add canonical/mason --skill chisel-slicer    # skills.sh (vercel), 70+ agents incl. pi
gh skill install canonical/mason chisel-slicer          # github cli >= 2.90
/plugin marketplace add canonical/mason                 # claude code plugin: every skill, as /mason:<skill>
```

## what's in here

`mason` is an umbrella kit for chisel / rocks work. Each capability area is one self-contained skill
under `skills/`, copied verbatim by whichever installer. Today there are two: `chisel-slicer` (the
substance) and `mason` (the `/mason` entry point -- routes a request to the right skill, or prints help).

```
skills/
  chisel-slicer/                   # a skill -- self-contained, copied verbatim on install
    SKILL.md                       # skill entry + command dispatch
    commands/
      write-slice.md               # author + scaffold tests + self-check + commit
      review-slice.md              # review: deterministic first pass (scripts) + judgement
    shared/CHISEL.md               # generated copy of _shared/CHISEL.md (make sync-shared)
    shared.list                    # which _shared/ files this skill ships
    scripts/
      orientation                  # deterministic orientation: cwd, skill dir, target release + format
      deb-list.py                  # inspect .deb contents (files, deps, maintainer scripts); --sdf emits a draft SDF
      try-cut                      # test slices with chisel cut against the current checkout
      scaffold-test.py             # emit a spread task.yaml skeleton (a rootfs per slice, every binary listed)
      check-slice.py               # lint an SDF: sorting, naming, copyright, clutter, arch, version-gated fields
      check-test.py                # report binary test coverage for a slice
      check-diff.py                # append-only regressions (removed SDF / slice / path) vs a base ref
      review-diff.py               # run the three checks over a PR diff -> report + verdict + exit code
    schemas/commands.manifest.yaml # command index (command -> file)
  mason/                           # umbrella /mason skill -- routes to a skill, or prints usage
    SKILL.md
_shared/                           # material used by more than one skill -- the source of truth
  CHISEL.md                        # chisel reference: format, branch model, schema versions, naming
scripts/sync-shared.py             # copies _shared/ files into each skill's shared/ per its shared.list
.tessl-plugin/plugin.json          # tessl plugin manifest (name, version); skills/ discovered by default
.claude-plugin/                    # claude code marketplace + plugin manifests
tests/scripts/                     # pytest for the skill scripts -- see makefile
tests/skills/                      # pats eval of the skills themselves
```

Adding a capability = a new skill directory under `skills/`; every installer picks it up. A skill
that needs something from `_shared/` lists it in its `shared.list`; `make sync-shared` copies it
into `<skill>/shared/` (with a "generated" banner) and the copy is committed, so installed skills
are self-contained. `make check-shared` (run in ci) fails when a copy drifts from its source.

## testing

The scripts are covered by pytest (`make test`); `make verify` runs everything ci runs. The skills
themselves (prompt-level behaviour) are tested with [pats](https://github.com/lczyk/pats), see
`tests/skills/`.

## releasing

The version lives in `.tessl-plugin/plugin.json` (mirror it in `.claude-plugin/plugin.json`).
Bump it, tag `vX.Y.Z`, then publish to the registry:

```
npx tessl plugin lint .
npx tessl plugin pack . --output /tmp/mason.tgz && tar tzf /tmp/mason.tgz   # eyeball what ships
npx tessl plugin publish .
```

Installs from github (`npx tessl i github:canonical/mason`, `npx skills add`, `gh skill`) pin
the commit and need no publish.

## sources of truth

The skill defers to three upstream projects. When in doubt:

**tool behaviour** ([canonical/chisel](https://github.com/canonical/chisel)) > **docs** ([canonical/chisel-docs](https://github.com/canonical/chisel-docs)) > **conventions** ([canonical/chisel-releases](https://github.com/canonical/chisel-releases)) > **this repo**

