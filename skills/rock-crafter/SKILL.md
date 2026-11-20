---
name: rock-crafter
description: >-
  Builds rocks (OCI images) with rockcraft and chisel: drafts, checks, packs
  and tests a rockcraft.yaml from Ubuntu archive or PPA packages, or from a
  project built from source (Go, Rust, Python, Node, Java, C/C++, rockcraft
  framework extensions), with spread tests run by `rockcraft test`. Use when
  the user wants to build a rock or write a rockcraft.yaml. Fixing a failing
  pack is the rock-debugger skill.
---

# rock-crafter

Build [rocks](https://documentation.ubuntu.com/rockcraft/stable/) in the user's
project. **Do the work yourself** -- do not hand the task to a subagent (the
slice hand-over in step 3 is the one exception).

## roots and boundaries

- **Skill root** is the directory containing this `SKILL.md`. All `kb/` and
  `scripts/` paths below belong to it. Keep the project as the working
  directory and run helpers by absolute path, e.g.:

  ```bash
  uv run "/absolute/path/to/rock-crafter/scripts/_check-rock.py"
  ```

  In the remaining commands, replace `<skill-root>` with that path.
- **Project root** is the current directory: `rockcraft.yaml` and every file
  it references are written there. Preserve unrelated changes; when you make
  commits, use Conventional Commits.
- Where this knowledge base and upstream disagree, upstream wins:
  `kb/_rock-upstream-sources.md`.

Every helper reports `passed`, `failed` or `unavailable`. **Failed** is a
defect to fix; **unavailable** means a tool or a network source could not be
reached -- report it, do not work around it, and never read it as evidence
(a denied fetch does not mean a package or slice is absent).

**Slicing never blocks delivery**: when slices can't be authored, ship an
unchiselled rock and say so.

## 1. gather

If a `rockcraft.yaml` already exists, ask: overwrite it, or fix it with the
rock-debugger skill? Settle --
asking once, grouped, only for what is missing: **what goes in** (Ubuntu
archive packages, packages from a PPA, or a project to build: git URL or local
dir, and a tag if not the latest release); the **release** (default: the
newest supported LTS, which the draft reports); **service or CLI** -- for a
service, its foreground command line, absolute binary first (e.g.
`/usr/bin/redis-server --protected-mode no`).

## 2. draft

```bash
uv run "<skill-root>/scripts/draft-rock.py" xxd --release 24.04                                                 # archive
uv run "<skill-root>/scripts/draft-rock.py" python3.13 --ppa deadsnakes/ppa --release 24.04                      # PPA
uv run "<skill-root>/scripts/draft-rock.py" https://github.com/BurntSushi/ripgrep --tag 14.1.1 --release 24.04 # source
```

Swap in the real names; add `--service "<cmd>"` for a service. The draft is
complete -- do not retype or restructure it. A `missing-slices` failure goes
to step 3; other failures name what to correct.

## 3. missing slices

Ask the user **once**: author the slices, or build unchiselled?

- **Unchiselled**: re-draft with `--unchiselled`; the report says unchiselled.
- **Author**: needs the chisel-slicer skill installed beside this one
  (`<skill-root>/../chisel-slicer/SKILL.md`); without it the user installs it,
  or the rock goes unchiselled.
  Use the user's chisel-releases checkout or a fork, branched off the target
  release. In it, follow chisel-slicer's `SKILL.md` for each missing package
  (a subagent is fine here). Then re-draft with
  `--chisel-release <checkout> --force`. After a successful pack, push the
  branch and point the part at the fork (`kb/_rock-slices.md`; chisel itself in
  `kb/_chisel-cli.md`); if you cannot push, keep the local source and
  report the push as remaining. If authoring fails, go unchiselled and say why.

## 4. adjust

Edit only what the draft cannot know: what its `review` lists, config files,
writable dirs for a service, a non-privileged port. Keep every existing key.
Read `kb/_rockcraft-yaml.md` for keys and parts, `kb/_pebble-services.md` for
services and the non-root user, and `kb/_rock-slices.md` before adding runtime
slices.

## 5. check and pack

```bash
uv run "<skill-root>/scripts/_check-rock.py"
uv run "<skill-root>/scripts/_pack-rock.py"
```

Fix every `block` from check-rock and re-run it until it passes, then pack:
packing needs rockcraft, not docker. A failed pack goes to the rock-debugger
skill when it is installed beside this one
(`<skill-root>/../rock-debugger/SKILL.md`); otherwise report the failure
pack-rock names.

## 6. test

Read `kb/_rock-tests.md` before writing tests: it owns layout, depth and what
each kind of rock must prove. Scaffold the suite once, beside
`rockcraft.yaml`; preserve existing tests:

```bash
rockcraft init --profile=test --name <rock-name>
```

If it wrote `spread.yaml` rather than `rockcraft-test.yaml`, rename it and drop
its `project:` key. Replace the scaffolded placeholder task with tasks that prove the workload
works, then run them:

```bash
uv run "<skill-root>/scripts/_test-rock.py"
```

A failed task or prepare script is a defect: fix the rock (check, pack, test
again) or a wrong assertion, never weaken a test to make it pass. The tests
are always written: a test run that is unavailable here is reported as
remaining, never a reason to leave them out.

## completion gate

- **Complete**: check-rock passed, pack-rock packed the rock and test-rock
  passed.
- **Ready for remaining verification**: `rockcraft.yaml` and the tests are
  written and check-rock passed, but the pack or the test run is unavailable
  (no rockcraft, no test VM, unreachable network). Name what remains.
- **Blocked**: a failure you cannot fix in scope. State it.

A packed rock is not proof the workload runs; only passing tests are.

## final report

Summarise for the user (or the parent agent when delegated):

- the rock (file, or why not), its flavour -- chiselled, chiselled from local
  slices, or unchiselled and why -- and the service command or CLI
- the tests: what each task proves, and their result
- checks passed, failed or unavailable, and what remains (push, upstreaming
  slices, an unrun test suite)
- what you changed from the draft, and why

Keep it concise; do not dump file contents or raw logs.
