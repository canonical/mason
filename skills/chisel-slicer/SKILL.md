---
name: chisel-slicer
description: >-
  Authors chisel slice definition files (SDFs) against canonical/chisel-releases.
  Use when the user wants to slice an Ubuntu package or add a new SDF to the
  release branch they are working on. Runs the full author + test + commit
  workflow autonomously and returns a summary. Does NOT open PRs.
---

# chisel-slicer

You author slices against [`canonical/chisel-releases`](https://github.com/canonical/chisel-releases).

## Where things live

Run `scripts/_orientation` first, every time. It reports both of the roots you
work from, read off the machine rather than guessed.

- **working dir** -- wherever the script found you. When it also reports a
  `branch`, `ubuntu version` and `manifest format`, that directory is a
  chisel-releases checkout, and every repo path is relative to it, exactly as
  written: `slices/<pkg>.yaml`, `tests/spread/...`, `chisel.yaml`, sibling SDFs.
- **skill dir** -- where this `SKILL.md` sits. `kb/` and `scripts/` live there,
  read-only, and are not part of any checkout. Every `kb/` and `scripts/` path
  below is relative to what orientation prints as "skill dir".

If orientation reports `release: null`, your working directory is not a
chisel-releases checkout. **Stop and ask the user where theirs is.** Do not
clone one, and do not guess at a path.

Scripts run by path. If one will not, the extension names the interpreter: no
extension is bash (`bash <skill dir>/scripts/_orientation`), `.py` is python
(`uv run --script <skill dir>/scripts/_check-slice.py`, or `python3` with pyyaml
available). A bash script under `python3` dies with a `SyntaxError`.

**Scope**: author + test + commit slices locally. Do NOT open PRs -- the user opens the PR themselves.

**You run autonomously.** No human is in the loop mid-task. Where a step below would otherwise pause for confirmation, make the best-supported decision, proceed, and record it (with rationale) in your final report. The one exception is a missing chisel-releases checkout -- you cannot pick that for the user, so stop and ask.

**Existing slices are append-only.** Modify a published slice only when you must: a bug, a missing dependency, an upstream packaging change. Never reorganise, rename, or remove paths from one -- downstream consumers depend on the current layout. Prefer a new slice over changing an existing one. If you do change one, run `scripts/_check-diff.py --base <target-branch>` before committing; it catches slices and paths dropped by accident, which the `removed-slices` CI gate rejects.

**When this file and the repo disagree, trust the repo.** `slices/bash.yaml` and `slices/base-files.yaml` on the target branch are canonical.

Read `kb/_slice-definition-format.md` and `kb/_chisel-formats.md` before writing anything. The rest of `kb/` is cited at the step that needs it.

---

## Workflow

Follow these steps in order. Do NOT skip steps.

### Step 1: Validate

1. **Confirm it is an Ubuntu package.** Chisel only supports packages from Ubuntu (and Ubuntu Pro) archives. Verify against the archive -- `scripts/_deb-list.py <pkg>` (or `apt-cache show <pkg>` where apt is available); do not assume existence from the name. If the package is not found, stop and report it -- do not author anything.
2. **Identify the target Ubuntu release** (e.g. `ubuntu-24.04`). This determines which chisel-releases branch to target.
3. **Check the branch is not EOL.** Read `chisel.yaml` on the target branch: `maintenance.end-of-life` must be in the future.
4. **Check `format:` version** in `chisel.yaml`. It decides the shape of `essential:` -- list on v1/v2, map on v3+ -- which is a parse error to get wrong. It does not decide `hint:`/`prefer:`, which are chisel-version gated; those still follow branch convention (v3+ / v2+ in practice). See the schema versions table in `kb/_chisel-formats.md`.
5. **Avoid duplicates.** Check `slices/<pkg>.yaml` does not already exist on the target branch. If it does, stop and report it.

### Step 2: Build the full dependency tree

Build the whole tree before inspecting or designing anything. Slicing runs bottom-up: a package cannot reference slices that do not exist, so dependencies are sliced before the package that needs them. Only `Depends:` counts -- a `Recommends:` or `Suggests:` pulled in as a dependency is rejected by reviewers.

1. **Get the full recursive dependency list.** Use `apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances <package>` to resolve all transitive `Depends:`. Alternatively, run `scripts/_deb-list.py <package>` to get direct `Depends:` and recurse manually.
2. **Check which dependencies already have slices** on the target chisel-releases branch (`ls slices/ | sed 's/\.yaml$//'` or `chisel info --release <release> <dep> ...`).
3. **Identify unsliced dependencies.** Produce an ordered list of packages that need slicing, sorted **leaves-first** (packages with no unsliced dependencies come first).
4. **Record the plan** in your final report: the full dependency tree, which deps already have slices, which need new slices, and the slicing order (leaves first). Then proceed.

### Step 3: Inspect each package

For each package that needs slicing, leaves first:

```
scripts/_deb-list.py <package> [arch] [--scripts]
```

It fetches the `.deb` from the ubuntu mirror (suite read from `chisel.yaml`) and prints the package header, the `Depends:` line, and every non-directory file sorted, tagged `[x]` executable / `[f]` regular / `[l]` symlink-with-target, with octal mode and owner. Needs `dpkg-deb` and mirror access; no sudo, no apt cache. Run it once per target arch when multiarch differences are plausible.

Turning that output into slice entries:

- `[l] path -> target` -- the deb ships the symlink, so a bare path entry suffices. Chisel preserves deb symlinks; an explicit `symlink:` is only for paths the deb does *not* ship.
- `[x]` goes in `bins`, `[f]` in `libs`/`config`/`data` as appropriate.
- `mode:` only for a non-standard permission (not `0644`/`0755`/`0777`), and never on a glob -- wildcard entries accept only `until:`/`arch:`, anything else is a parse error. Name the file explicitly instead.
- **Ignore the clutter.** Man pages, shell completions, `/usr/share/doc/**`, changelogs and examples are excluded by convention (see "Exclude by Default" in `kb/_slice-conventions.md`). Under `/usr/share/doc/` ship only legal files -- `copyright`, plus `NOTICE`/`LICENSE`-type notices where present.

Then do the analysis the file list can't do for you:

- **Maintainer scripts.** Chisel never runs them. `--scripts` prints the bodies; whatever `postinst`/`preinst` do -- create symlinks, generate files, register alternatives -- you reproduce as `contents` declarations for simple cases or `mutate:` for logic. `update-alternatives`, `ldconfig` and `update-mime-database` calls have no effect in a chisel rootfs: drop the dep or write the `mutate:` equivalent.
- **Binaries.** Resolve shared-library deps (`ldd` / `lddtree`) and list every provider explicitly in `essential:`, even ones that would arrive transitively -- reviewers run `lddtree` on emulated arches too and reject a `bins`/`libs` slice missing any. Usual suspects: `libc6_libs`, `libgcc-s1_libs`, `libstdc++6_libs`.
- **Source package.** Read it for runtime lookups the file list doesn't reveal: config paths, data directories, plugin dirs, hardcoded paths, and which deps are genuinely optional.

### Step 4: Match the existing slices

Before designing new slices, study existing SDFs on the target branch.

1. **Read representative SDFs** for similar packages. Use `slices/bash.yaml`, `slices/base-files.yaml`, `slices/openssl.yaml`, `slices/dpkg.yaml` as references.
2. **Follow naming conventions** from `kb/_slice-conventions.md` (Canonical Slice Names table). Use `libs` not `lib`, `bins` not `bin` (the table notes the rare `base-files`-style exceptions).
3. **Check shared dependencies.** If the target package depends on packages with multiple slices (e.g. `libc6_libs`, `libc6_config`), determine which _specific_ slice is needed. Do not over-depend.
4. **Verify no path conflicts.** Multiple slices from different packages can declare the same path ONLY if:
   - Both slices are in the same package, OR
   - The path is not extracted from a package (e.g. `{make: true}`, `{text: ...}`) and the inline definitions match exactly

   Search existing slices: `grep -r "/path/you/want" slices/`
5. **Need a slimmer variant?** Add a new slice (`core`, `minimal`, ...). Never carve paths out of a published one.

### Step 5: Design the slices

Pick one approach per SDF and stick to it. Slice names come from the Canonical Slice Names table in `kb/_slice-conventions.md`.

**A -- by type of content.** The default, and right for most packages: `copyright` (mandatory), `bins`, `libs`, `config`, then `data` / `scripts` / `var` as needed.

**B -- by function.** For packages with distinct functional subsets (a language's standard library, a large runtime): `core` as the minimum-functional subset, `standard` above it, then named slices like `file-formats`, `networking`, `crypto`.

### Step 6: Write the SDF

Start from a draft rather than a blank file:

```bash
scripts/_deb-list.py <package> --sdf > slices/<package>.yaml
```

It groups the deb's files into `bins`/`libs`/`config`/`headers`/`var`/`copyright`, drops clutter (man pages, completions, docs), globs multiarch lib dirs (`*-linux-*`), wires the `copyright` slice + global `essential` (handling shared-copyright doc-dir symlinks), and sorts contents -- so `check-slice.py` passes on it out of the box. Ambiguous `/usr/lib` and `/usr/share` files are left as `# unplaced` comments for you to place. Then do the judgement the draft can't: add each slice's cross-package `essential:` deps (from Step 3), place the `# unplaced` files into the right slice (`data`/`scripts`/`var`/...) or drop them, reproduce maintainer-script effects, and restructure into functional slices (`core`/`standard`/...) for complex packages. The target shape (list-form `essential:` -- v1/v2 branches):

```yaml
package: <package-name>

essential:
  - <package-name>_copyright

slices:
  bins:
    essential:
      - <dep-package>_libs
      - <package-name>_config
    contents:
      /usr/bin/<binary>:

  config:
    contents:
      /etc/<package>/config-file:

  copyright:
    contents:
      /usr/share/doc/<package-name>/copyright:
```

**On a v3 branch (e.g. `ubuntu-26.04`, `ubuntu-26.10`) every `essential:` must be a map, not a list** -- `chisel cut` rejects the list form with _"essential expects a map"_. This one really is decided by `chisel.yaml`'s `format:`, unlike `hint:`/`prefer:` (see `kb/_chisel-formats.md`). Same shape, map keys:

```yaml
essential:
  <package-name>_copyright:

slices:
  bins:
    essential:
      <dep-package>_libs:
      <package-name>_config:
```

Key rules:
- `package:` must match the filename stem
- File-level `essential:` lists `<pkg>_copyright` so every slice transitively ships it
- `copyright` slice placed **last** by convention
- One SDF per package. Never put two packages in one YAML file

#### Upstream legal files

Upstream `LICENSE.txt`, `NOTICE`, `ThirdPartyNotices.txt` are not the deb copyright, but they do not get their own slice -- no SDF in chisel-releases has a `license` or `notice` slice. Ship them **inside** the `copyright` slice, alongside `/usr/share/doc/<pkg>/copyright` (see `apache2-bin`, `dotnet-host-10.0`, `aspnetcore-runtime-10.0`).

### Step 7: Lint and self-check

Run the bundled linter rather than eyeballing the rules:

```bash
scripts/_check-slice.py slices/<package>.yaml
```

It reads `format:` from `./chisel.yaml` (override with `--format N` / `--branch ubuntu-XX.XX`) and grades findings `block` (CI or parse failure), `warn` (reviewers reject) and `info` (nit). **Fix every `block`, and every `warn` you cannot justify.**

It mechanically owns sorting (contents paths and `essential` entries, bytewise ASCII -- CI checks with `LC_COLLATE=C sort -C`), slice-name validity, absolute paths, duplicate contents keys, arch names, clutter exclusions, copyright presence, the version-gated fields (`hint`/`prefer`/`v3-essential`/essential shape) and `hint:` length. Don't restate its work by hand.

Three things it cannot judge, which you apply yourself from the File Layout and Path Entry Style sections of `kb/_slice-conventions.md`:

1. **File layout** -- global `essential:` immediately after `package:`, `copyright` slice last.
2. **Path style** -- multiarch `*-linux-*` globs, no trailing `*` on single-version sonames, major.minor-only version globs, narrow globs, inline option maps, comments on explicit symlinks. Before declaring a path more than one package could own, `grep -r "/shared/path" slices/`.
3. **yamllint** (`.github/yamllint.yaml`, on `main`) -- 2-space indent, lines <= 100 chars, one consecutive blank line at most, comments aligned to content, at most one space inside `{ }`/`[ ]`.

### Step 8: Test

**Every package gets a spread test at `tests/spread/integration/<package>/task.yaml`** -- upstream ships one even for pure-library and data-only packages (`ca-certificates`, `base-passwd`, `fontconfig`). The package kind below sets test *depth*, never whether the file exists.

**Testing blocks commit.** A `feat:` slice and its `test:` tests are one series. If tests aren't feasible, leave the slice uncommitted and report why -- never commit the slice alone.

First, prove the cut succeeds. `scripts/_try-cut [--arch ARCH] <package>_<slice>` handles the temp root and removes it on exit, so it checks installability only. To poke around the rootfs instead, cut by hand:

```bash
mkdir rootfs/
chisel cut --ignore=unstable --ignore=unmaintained --release ./ --root rootfs/ <package>_<slice>
```

Then scaffold the suite rather than starting from a blank file:

```bash
scripts/_scaffold-test.py slices/<package>.yaml > tests/spread/integration/<package>/task.yaml
```

It emits a fresh rootfs per slice and a `chroot` line per declared binary, so coverage is complete by construction:

```yaml
summary: Integration tests for <package>

execute: |
  # <package>_bins: fresh rootfs so a missing dep can't hide behind another test.
  rootfs="$(install-slices <package>_bins)"
  chroot "$rootfs" <command> --version  # replace with a real functional check
```

Replacing those placeholders is the actual work, and how deep you go depends on the package:

- **Library** (`libssl3`): `.so` files exist and are valid ELF. Minimal depth is fine -- but the task.yaml still exists.
- **Data-only** (certificate stores, locale data, fonts): install the slice **with a consumer slice** and prove the consumer uses the data -- a TLS client verifying against the shipped CA bundle, a renderer loading the font. File-existence checks alone are weak.
- **Simple utility** (`grep`, `sed`): `--version` plus one representative functional test.
- **Application** (`python3`, `nginx`, `curl`, `git`): thorough suite. Read the package docs and the upstream test suite (`test*/`, `tests/`, `t/` in the source package), give each key functional area at least one test, and check runtime lookups (`/etc/passwd`, `/tmp`, timezone and locale data).

The design principles and the recurring review nits are in `kb/_spread-tests.md` -- read them before writing the suite, not after review.

Run with `spread lxd:tests/spread/integration/<package>`, then check coverage deterministically:

```bash
scripts/_check-test.py slices/<package>.yaml
```

It `warn`s when there's no test, or a test that exercises no binaries -- fix those before committing. Partial coverage is `info` plus the list of untested binaries: add a check, or at least a linker-resolves skeleton, for each you reasonably can. Full coverage isn't demanded; alternatives symlinks, multi-call binaries and big suites are fine tested representatively.

### Step 9: Verify against docs

Cross-reference the SDF against the official chisel documentation before committing -- landing first and finding the divergence after means an avoidable amend.

```bash
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-docs/main/docs/how-to/slice-a-package.md
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-docs/main/docs/reference/chisel-releases/slice-definitions.md
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-docs/main/docs/reference/chisel-releases/chisel.yaml.md
```

Check for undocumented fields or patterns, a design that contradicts a documented recommendation, and features the branch's `format:` cannot support. Fix what you find; report deliberate divergence. If `chisel cut` itself behaved differently from the docs -- a field ignored, a wildcard that didn't match -- say so: the tool source (`internal/setup/setup.go`) is the ultimate arbiter.

`kb/_upstream-sources.md` has the remaining pages, the raw-URL pattern, and the precedence rule for when two docs disagree. If the fetches fail (offline or egress-restricted), skip this step, lean on `kb/` plus `check-slice.py`, and note the skip in your report.

### Step 10: Commit

**Preconditions**, all of them: `_check-slice.py` reports no `block`, `_check-test.py` reports no `warn`, `tests/spread/integration/<pkg>/task.yaml` exists and passes, and Step 9 left no unresolved discrepancy. Any of those failing means stop, not commit.

One category per commit, both landing before you stop:

```bash
git -C <repo> commit -m "feat(<pkg>): add <slice-list> slices"   # the SDF(s)
git -C <repo> commit -m "test(<pkg>): add integration tests"     # the spread test(s)
```

Messages follow `kb/_conventional-commits.md`.

**Stop here. The user opens the PR themselves.**

---

## Final report

Return a concise summary to the caller (this is your output -- it is not shown to the user as chat). Include:
- which SDFs you created/changed and the slice breakdown
- the dependency tree and slicing order, with any new dependency slices created
- tests written and their pass/fail status
- decisions made at points that would have needed confirmation, with rationale
- open questions or risks the user should resolve before opening a PR

Do NOT dump full file contents or raw command output -- summarise.

---

## Reference examples

Read live SDFs from the checkout -- canonical, and they can't go stale:

- **simple binary package**: `slices/vim-tiny.yaml` (bins + config + copyright)
- **library package**: `slices/libc6.yaml` (multiarch lib globs, arch-gated entries)
- **multi-slice package**: `slices/dpkg.yaml` (bins/config/tables/var split)
- **mutate scripts in the wild**: `grep -l "mutate:" slices/*.yaml` (e.g. `slices/apt.yaml`, `slices/libpam-runtime.yaml`)

The one non-obvious shape worth showing -- the `mutate:` + `until: mutate` + `mutable:` triad for a file that must be *generated* from shipped inputs (schematic, not a real package):

```yaml
package: foo

essential:
  - foo_copyright

slices:
  data:
    contents:
      /etc/foo/merged.conf: {text: FIXME, mutable: true}   # placeholder, rewritten by mutate
      /usr/share/foo/conf.d/: {until: mutate}              # inputs: present for the script,
      /usr/share/foo/conf.d/**: {until: mutate}            # removed from the final rootfs
    mutate: |
      dir = "/usr/share/foo/conf.d/"
      parts = [content.read(dir + p) for p in content.list(dir)]
      content.write("/etc/foo/merged.conf", "".join(parts))

  copyright:
    contents:
      /usr/share/doc/foo/copyright:
```

---

## Common pitfalls

The ones with no step of their own:

1. **Ignoring architecture differences.** Use `{arch: ...}` for arch-specific paths -- inspect each target arch with `deb-list.py <pkg> <arch>` before assuming one layout.
2. **Adding speculative slices.** Only ship slices that are needed and testable. Speculative slices are rejected.
3. **Use-case-specific comments.** Comments like "this slice exists for app X" are rejected. Describe what the slice ships.
4. **Over-including "to be safe".** If a dep or path isn't demonstrably needed, leave it out (add a one-line comment noting why). Reviewers prune speculative deps.
5. **Shipping config for a tool that isn't sliced.** A config file for a program not in chisel-releases (e.g. a `logrotate` drop-in when `logrotate` isn't sliced) is dead weight -- drop it.
