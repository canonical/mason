---
name: rockcrafter
description: >-
  Builds and fixes rocks (OCI images) with rockcraft and chisel. Drafts,
  checks, packs and tests a rockcraft.yaml from Ubuntu archive or PPA packages,
  or from a project built from source (Go, Rust, Python, Node, Java, C/C++,
  rockcraft framework extensions), with spread tests run by `rockcraft test`.
  Classifies a failing pack or test and applies targeted fixes until the rock
  packs and its tests pass. Use when the user wants to build a rock or write a
  rockcraft.yaml, when a rock does not pack or its tests fail, or the user
  asks why.
---

# rockcrafter

Build [rocks](https://ubuntu.com/containers/rockcraft/docs) in the user's
project, and fix the ones that fail to pack or fail their tests. **Do the work
yourself** -- do not hand the task to a subagent (the slice hand-over in step 3
is the one exception).

## roots and boundaries

- **Skill root** is the directory containing this `SKILL.md`. All `kb/` and
  `scripts/` paths below belong to it. Keep the project as the working
  directory and run helpers by absolute path, e.g.:

  ```bash
  uv run "/absolute/path/to/rockcrafter/scripts/check-rock.py"
  ```

  In the remaining commands, replace `<skill-root>` with that path.
- **Project root** is the current directory: `rockcraft.yaml` and every file
  it references live there. Preserve unrelated changes; when you make
  commits, use Conventional Commits.
- Where this knowledge base and upstream disagree, upstream wins:
  `kb/rock-upstream-sources.md`.

Every helper reports `passed`, `failed` or `unavailable`. **Failed** is a
defect to fix; **unavailable** means a tool or a network source could not be
reached -- report it, do not work around it, and never read it as evidence
(a denied fetch does not mean a package or slice is absent).

**Slicing never blocks delivery**: when slices can't be authored, ship an
unchiselled rock and say so.

A new rock starts at step 1. A rock that already exists and fails to pack or
fails its tests starts at step 5, under "fixing a failure".

## 1. gather

If a `rockcraft.yaml` already exists, ask: overwrite it, or fix it (step 5)?
Settle -- asking once, grouped, only for what is missing: **what goes in**
(Ubuntu archive packages, packages from a PPA, or a project to build: git URL
or local dir, and a tag if not the latest release); the **release** (default:
the newest supported LTS, which the draft reports); **service or CLI** -- for a
service, its foreground command line, absolute binary first (e.g.
`/usr/sbin/nginx -g 'daemon off;'`).

## 2. draft

```bash
uv run "<skill-root>/scripts/draft-rock.py" hello --release 24.04                                       # archive
uv run "<skill-root>/scripts/draft-rock.py" git --ppa git-core/ppa --release 24.04                      # PPA
uv run "<skill-root>/scripts/draft-rock.py" https://github.com/jqlang/jq --tag jq-1.7.1 --release 24.04 # source
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
  branch and point the part at the fork (`kb/rock-slices.md`; chisel itself in
  `kb/chisel-cli.md`); if you cannot push, keep the local source and
  report the push as remaining. If authoring fails, go unchiselled and say why.

## 4. adjust

Edit only what the draft cannot know: what its `review` lists, config files,
writable dirs for a service, a non-privileged port. Keep every existing key.
Read `kb/rockcraft-yaml.md` for keys and parts, `kb/pebble-services.md` for
services and the non-root user, and `kb/rock-slices.md` before adding runtime
slices.

## 5. check and pack

```bash
uv run "<skill-root>/scripts/check-rock.py"
uv run "<skill-root>/scripts/pack-rock.py"
```

Fix every `block` from check-rock and re-run it until it passes -- these are
cheaper than a pack -- then pack: packing needs rockcraft, not docker. A
failed pack goes to "fixing a failure".

## 6. test

Read `kb/rock-tests.md` before writing tests: it owns layout, depth and what
each kind of rock must prove. Scaffold the suite once, beside
`rockcraft.yaml`; preserve existing tests:

```bash
rockcraft init --profile=test --name <rock-name>
```

If it wrote `spread.yaml` rather than `rockcraft-test.yaml`, rename it and drop
its `project:` key. Replace the scaffolded placeholder task with tasks that prove the workload
works, then run them:

```bash
uv run "<skill-root>/scripts/test-rock.py"
```

A failed task or prepare script is a defect, see "fixing a failure". For a
new rock the tests are always written: a test run that is unavailable here is
reported as remaining, never a reason to leave them out.

## fixing a failure

- **A failed pack** names the category, step, part and the fix: apply it and
  go back to check-rock. For `unknown`, read the log it names. After 3 rounds,
  inspect the kept build instance when `lxc` is available
  (`kb/rock-debugging.md`); apply what it shows, or stop.
- **A failed task**, or a failed prepare or restore script, comes with the
  commands spread ran and their output. Diagnose it with
  `kb/rock-debugging.md`, "A failing test": fix the rock and go back to
  check-rock, or fix a wrong assertion and re-run only that task.

**Targeted fixes only**: change what the finding names. Never replace slices
with whole debs, drop the workload, switch `base: bare` to an Ubuntu base,
remove `run-user`, or drop or weaken a test's check of real behaviour -- if
only that would work, stop and recommend it.

**A rock that already exists** is fixed, not redesigned. Work autonomously,
with no mid-task questions; with no `rockcraft.yaml` in the project root, stop
and ask where the rock is. Edit only `rockcraft.yaml`, its tests and project
files a finding names. In a git project commit each fix once it works -- only
the files it touched. Without git, copy `rockcraft.yaml` to
`rockcraft.yaml.bak` before the first edit. Run its test suite
(`rockcraft-test.yaml`, or a deprecated `spread.yaml`) when it has one; with
none, the work ends at a passing pack and the report says the rock is
untested.

## completion gate

- **Complete**: check-rock passed, pack-rock packed the rock and test-rock
  passed (or an existing rock has no tests -- say so).
- **Ready for remaining verification**: `rockcraft.yaml` and the tests are
  written, or the fixes are in, and check-rock passed, but the pack or the
  test run is unavailable (no rockcraft, no test VM, unreachable network).
  Name what remains.
- **Blocked**: a failure you cannot fix in scope, or one only a forbidden
  change would fix. State it and the change you recommend.

A packed rock is not proof the workload runs; only passing tests are.

## final report

Summarise for the user (or the parent agent when delegated):

- the rock (file, or why not), its flavour -- chiselled, chiselled from local
  slices, or unchiselled and why -- and the service command or CLI
- the tests: what each task proves, and their result
- each fix round: the failure (pack category and step / part, or the failed
  task), the cause, and the change made -- to the rock or to a wrong assertion
- checks passed, failed or unavailable, and what remains (push, upstreaming
  slices, an unrun test suite)
- for a new rock, what you changed from the draft, and why

Keep it concise; do not dump file contents or raw logs.
