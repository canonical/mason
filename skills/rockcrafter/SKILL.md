---
name: rockcrafter
description: >-
  Builds and fixes rocks (OCI images) with rockcraft and chisel. Drafts a
  rockcraft.yaml from `rockcraft init`, then fills in, checks, packs and tests
  it, from Ubuntu archive or PPA packages, or from a project built from source
  (Go, Rust, Python, Node, Java, C/C++, rockcraft framework extensions), with
  spread tests run by `rockcraft test`.
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
unchiseled rock and say so.

Every rock starts at step 1. After it, a rock that already exists and fails to
pack or fails its tests goes to step 6, under "fixing a failure".

## 1. orient

```bash
uv run "<skill-root>/scripts/orientation.py"
```

Run it first, every time: it reports the tools on this machine, the rock
already in the project (`rock`), and per Ubuntu release what Ubuntu,
chisel-releases and the installed rockcraft each say (`releases`). When
`tools` shows no rockcraft, a new rock is blocked -- say so and stop; an
existing rock can still be linted.

## 2. gather

If orientation reports a `rock`, ask: overwrite it, or fix it (step 6)?
Settle -- asking once, grouped, only for what is missing: **what goes in**
(Ubuntu archive packages, packages from a PPA, or a project to build: git URL
or local dir, and a tag if not the latest release); the **release** (default:
orientation's `default rock base`; a release the user names must be one
rockcraft takes as a base); **service or CLI** -- for a service, its
foreground command line, absolute binary first (e.g.
`/usr/sbin/nginx -g 'daemon off;'`).

## 3. packages

```bash
uv run "<skill-root>/scripts/rock-packages.py" hello --release 24.04
uv run "<skill-root>/scripts/rock-packages.py" git --ppa git-core/ppa --release 24.04
```

Run it for every Ubuntu package the rock stages: the workload from the archive
or a PPA, and the runtime a source build needs (`kb/rock-slices.md`). Take
versions, executables and slice names from its report, never from memory. A
`package-not-found` is a name to correct. For `missing-slices`, ask the user
**once**: author the slices, or build unchiseled?

- **Unchiseled**: stage whole debs on an Ubuntu base (`kb/rock-slices.md`);
  the report says unchiseled.
- **Author**: needs the chisel-slicer skill installed beside this one
  (`<skill-root>/../chisel-slicer/SKILL.md`); without it the user installs it,
  or the rock goes unchiseled.
  Use the user's chisel-releases checkout or a fork, branched off the target
  release. In it, follow chisel-slicer's `SKILL.md` for each missing package
  (a subagent is fine here). Then run rock-packages again with
  `--chisel-release <checkout>` and cut the slices from the checkout
  (`kb/rock-slices.md`; chisel itself in `kb/chisel-cli.md`). After a
  successful pack, push the branch and point the part at the fork; if you
  cannot push, keep the local source and report the push as remaining. If
  authoring fails, go unchiseled and say why.

## 4. start the file

Pick the profile: `rockcraft init -h` lists the installed version's, and the
docs describe each (`kb/rock-upstream-sources.md`). Use a framework profile
when the project is an application its extension supports, else `simple`.
Then draft:

```bash
uv run "<skill-root>/scripts/draft-rock.py" --name hello --package hello --release 24.04
uv run "<skill-root>/scripts/draft-rock.py" --name git --package git --ppa git-core/ppa --release 24.04
uv run "<skill-root>/scripts/draft-rock.py" --name yq --source https://github.com/mikefarah/yq \
  --plugin go --source-tag v4.44.3 --slice base-files_base --slice ca-certificates_data --release 24.04
uv run "<skill-root>/scripts/draft-rock.py" --name app --profile flask-framework --release 24.04
```

It runs `rockcraft init`, fills in only what you pass and has rockcraft
validate the result; never write `rockcraft.yaml` from scratch. Its report
names the schema the installed rockcraft ships (`schema`): read the structure
of anything you add or change there. Add `--service "<command>"` for a service
and `--unchiseled` when the user chose it. A source build takes its plugin from
upstream's reference (`kb/rock-upstream-sources.md`), pinned to the tag the
user named, else the newest release tag, and its runtime slices from
`kb/rock-slices.md`. A `rejected` finding is rockcraft's own complaint: correct
the option it names. To replace a `rockcraft.yaml` the user asked to replace,
pass `--force`.

## 5. fill in

Edit the draft: keep its structure, settle everything under its `review`, and
add only what the rock needs.
Read `kb/rockcraft-yaml.md` for keys, parts, the version and services,
`kb/rock-slices.md` for the base and what to stage, and `kb/hardening.md` for
the non-root user and what the rock ships. A source build takes its plugin's
other keys from upstream's reference. A service also needs its config files,
its writable dirs and a non-privileged port.

## 6. check and pack

```bash
uv run "<skill-root>/scripts/check-rock.py"
uv run "<skill-root>/scripts/pack-rock.py"
```

Fix every `block` from check-rock and re-run it until it reports none --
these are cheaper than a pack -- then pack: packing needs rockcraft, not
docker. A failed pack goes to "fixing a failure".

## 7. test

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
remove `run-user`, or drop or weaken a test's check of real behavior -- if
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
  written, or the fixes are in, and check-rock reports no block, but one of
  its checks, the pack or the test run is unavailable (no rockcraft, no test
  VM, unreachable network). Name what remains.
- **Blocked**: a new rock without rockcraft installed, a failure you cannot
  fix in scope, or one only a forbidden change would fix. State it and the
  change you recommend.

A packed rock is not proof the workload runs; only passing tests are.

## final report

Summarize for the user (or the parent agent when delegated):

- the rock (file, or why not), its flavor -- chiseled, chiseled from local
  slices, or unchiseled and why -- and the service command or CLI
- the tests: what each task proves, and their result
- each fix round: the failure (pack category and step / part, or the failed
  task), the cause, and the change made -- to the rock or to a wrong assertion
- checks passed, failed or unavailable, and what remains (push, upstreaming
  slices, an unrun test suite)
- for a new rock, the choices the user did not make (release, profile or
  plugin, slices), and why

Keep it concise; do not dump file contents or raw logs.
