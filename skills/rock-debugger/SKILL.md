---
name: rock-debugger
description: >-
  Fixes a rock that fails to pack or fails its tests: lints the rockcraft.yaml,
  packs, runs its spread tests (`rockcraft test`), classifies each failure and
  applies targeted fixes until the rock packs and its tests pass. Use when a
  rockcraft.yaml does not pack, a rock's tests fail, or the user asks why.
  Autonomous; does not redesign the rock.
---

# rock-debugger

Fix a rock that fails to pack or fails its tests in the user's project. **Do the work yourself** -- do
not hand the task to a subagent. Work autonomously: no mid-task questions.

## roots and boundaries

- **Skill root** is the directory containing this `SKILL.md`. All `kb/` and
  `scripts/` paths below belong to it. Keep the project as the working
  directory and run helpers by absolute path, e.g.:

  ```bash
  uv run "/absolute/path/to/rock-debugger/scripts/_check-rock.py"
  ```

  In the remaining commands, replace `<skill-root>` with that path.
- **Project root** is the current directory, holding `rockcraft.yaml`; with no
  `rockcraft.yaml` there, stop and ask where the rock is. Edit only
  `rockcraft.yaml`, its tests and project files a finding names; preserve unrelated
  changes. In a git project commit each fix once it works -- only the files it
  touched. Without git, copy `rockcraft.yaml` to `rockcraft.yaml.bak` before
  the first edit.
- `kb/rock-debugging.md` covers logs, the build instance and failing tests;
  `kb/_rock-tests.md` how the tests are laid out and run. For the fix
  itself: `kb/_rockcraft-yaml.md` (keys, parts, lifecycle),
  `kb/_pebble-services.md` (services, permissions), `kb/_rock-slices.md`
  (slices, including ones not upstream yet). Upstream wins over this
  knowledge base: `kb/_rock-upstream-sources.md`.

Every helper reports `passed`, `failed` or `unavailable`. **Failed** is a
defect to fix; **unavailable** means a tool or a network source could not be
reached -- report it, do not work around it, and never read it as evidence
(a denied fetch does not mean a package or slice is absent).

**Targeted fixes only**: change what the finding names. Never replace slices
with whole debs, drop the workload, switch `base: bare` to an Ubuntu base,
remove `run-user`, or drop or weaken a test's check of real behaviour -- if
only that would work, stop and recommend it.

## 1. lint

```bash
uv run "<skill-root>/scripts/_check-rock.py"
```

Fix every `block` and re-run until it passes; these are cheaper than a pack.

## 2. pack

```bash
uv run "<skill-root>/scripts/_pack-rock.py"
```

A failure names the category, step, part and the fix; apply it and go back to
step 1. For `unknown`, read the log it names.

## 3. test

When the rock has a test suite (`rockcraft-test.yaml`, or a deprecated
`spread.yaml`):

```bash
uv run "<skill-root>/scripts/_test-rock.py"
```

Each failed task comes with the commands spread ran and their output.
Diagnose it with `kb/rock-debugging.md`, "A failing test": fix the rock and go
back to step 1, or fix a wrong assertion and re-run only that task. With no
test suite, the work ends at a passing pack and the report says the rock is
untested.

## 4. still failing

After 3 rounds, inspect the kept build instance for a pack failure when `lxc`
is available (`kb/rock-debugging.md`); apply what it shows, or stop.

## completion gate

- **Fixed**: check-rock passed, pack-rock packed the rock, and test-rock
  passed (or the rock has no tests -- say so).
- **Ready for remaining verification**: the fixes are in and check-rock
  passed, but the pack or the test run is unavailable (no rockcraft, no test
  VM, unreachable network). Name what remains.
- **Blocked**: a failure you cannot fix in scope, or one only a forbidden
  change would fix. State it and the change you recommend.

A packed rock is not proof the workload runs; only passing tests are.

## final report

Summarise for the user (or the parent agent when delegated):

- the outcome and the rock file
- each round: the failure (pack category and step / part, or the failed task),
  the cause, and the change made -- to the rock or to a wrong assertion
- checks passed, failed or unavailable, and what remains

Keep it concise; do not dump file contents or raw logs.
