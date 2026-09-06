---
name: chisel-slicer
description: >-
  Authors chisel slice definition files (SDFs) against canonical/chisel-releases.
  Use when the user wants to slice an Ubuntu package or add a new SDF to the
  release branch they are working on. Runs the full author + test + commit
  workflow autonomously and returns a summary. Does NOT open PRs.
argument-hint: "<package>"
---

# chisel-slicer

You author slices against [`canonical/chisel-releases`](https://github.com/canonical/chisel-releases).

## Where things live

You work inside a checkout of `canonical/chisel-releases` -- your current working
directory. Every repo path you read or write -- `slices/<pkg>.yaml`,
`tests/spread/...`, `chisel.yaml`, sibling SDFs -- is relative to that checkout,
exactly as written.

`kb/` and `scripts/` are **not**. They are relative to this skill's own
directory -- the one holding this `SKILL.md` -- which is somewhere else entirely,
and they are read-only. Running `scripts/_orientation` from the checkout finds
nothing; run it by its real path. `scripts/_orientation` prints that path as
"skill dir" for you, so run it first and use what it prints.

If a `scripts/` file will not run by path, run it through its interpreter --
**the extension tells you which**: `_orientation` and `_try-cut` have no
extension and are bash (`bash <skill dir>/scripts/_orientation`); everything ending `.py` is python
(`uv run --script <skill dir>/scripts/_check-slice.py`, or `python3` with pyyaml
available). Running a bash script under `python3` fails with a `SyntaxError`.

**Scope**: author + test + commit slices locally. Do NOT open PRs -- the user opens the PR themselves.

**You run autonomously.** There is no human in the loop mid-task. Where the workflow below would historically pause for confirmation, instead make the best-supported decision, proceed, and record the decision (with rationale and any open questions) in your final report. Surface anything genuinely ambiguous or risky in that report rather than blocking.

**Existing slices are append-only.** Only modify a published slice if strictly necessary (e.g. fixing a bug, adding a missing dependency, or accommodating an upstream packaging change). Never reorganise, rename, or remove paths from existing slices without a concrete reason -- downstream consumers depend on the current layout. When in doubt, create a new slice rather than changing an existing one. If you do change an existing SDF, run `scripts/_check-diff.py --base <target-branch>` before committing -- it flags any slice or path you removed by accident (the `removed-slices` CI gate rejects those).

**Prerequisites**: run `scripts/_orientation <package>` first -- it reports your working dir, this skill's own dir, and the target release + manifest format (from `chisel.yaml`) deterministically. Then read `kb/_slice-definition-format.md` (SDF format) and `kb/_chisel-formats.md` (what `format:` decides); pull in `kb/_slice-conventions.md` (naming, path style, exclusions) at steps 5-7, `kb/_chisel-cli.md` at step 8 for `chisel cut`'s flags and `--release` handling, and `kb/_spread-tests.md` at step 8 for the test contract.

When this prompt and the repo disagree, trust the repo. Read `slices/bash.yaml` or `slices/base-files.yaml` on the target branch as canonical reference.

---

## Workflow

Follow these steps in order. Do NOT skip steps.

### Step 1: Validate

1. **Confirm it is an Ubuntu package.** Chisel only supports packages from Ubuntu (and Ubuntu Pro) archives. Verify against the archive -- `scripts/_deb-list.py <pkg>` (or `apt-cache show <pkg>` where apt is available); do not assume existence from the name. If the package is not found, stop and report it -- do not author anything.
2. **Identify the target Ubuntu release** (e.g. `ubuntu-24.04`). This determines which chisel-releases branch to target.
3. **Check the branch is not EOL.** Read `chisel.yaml` on the target branch: `maintenance.end-of-life` must be in the future.
4. **Check `format:` version** in `chisel.yaml`. It decides the shape of `essential:` -- list on v1/v2, map on v3+ -- which is a parse error to get wrong. It does not decide `hint:`/`prefer:`, which are chisel-version gated; those still follow branch convention (v3+ / v2+ in practice). See the schema versions table in `kb/_chisel-formats.md`.
5. **Avoid duplicates.** Check `slices/<pkg>.yaml` does not already exist on the target branch. If it does, stop and report it.

### Step 2: Build the Full Dependency Tree

Before inspecting or designing anything, build the complete dependency tree. Dependencies MUST be sliced before the target package.

1. **Get the full recursive dependency list.** Use `apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances <package>` to resolve all transitive `Depends:`. Alternatively, run `scripts/_deb-list.py <package>` to get direct `Depends:` and recurse manually.
2. **Check which dependencies already have slices** on the target chisel-releases branch (`ls slices/ | sed 's/\.yaml$//'` or `chisel info --release <release> <dep> ...`).
3. **Identify unsliced dependencies.** Produce an ordered list of packages that need slicing, sorted **leaves-first** (packages with no unsliced dependencies come first).
4. **Record the plan** in your final report: the full dependency tree, which deps already have slices, which need new slices, and the slicing order (leaves first). Then proceed.

IMPORTANT: Slice dependencies bottom-up. A package cannot reference slices that do not exist. Work from the leaves of the dependency tree toward the root.

Note: only `Depends:` matter. Not `Recommends:` or `Suggests:`. Including `Recommends:` is rejected by reviewers.

### Step 3: Inspect Each Package

For EACH package that needs slicing (starting from leaf dependencies), inspect it using the bundled `deb-list.py` script:

```
scripts/_deb-list.py <package> [arch] [--scripts]
```

This fetches the `.deb` straight from the ubuntu mirror (reading the suite from `chisel.yaml`) and prints:
- Package header (name, version, arch)
- `Depends:` line (feeds directly into `essential:` entries)
- All non-directory files, lexicographically sorted, with type tags:
  - `[x]` executable, `[f]` regular file, `[l]` symlink (with target)
- Octal permissions and owner per file
- Which maintainer scripts are present (add `--scripts` to print full bodies)

Reading the output:
- `[l] path -> target` means the deb ships that symlink -- use a bare path entry, no explicit `symlink:` needed.
- `[x]` marks executables (go in `bins`); `[f]` marks regular files.
- Add `mode:` to a slice entry only when the permission is non-standard (not `0644`/`0755`/`0777`). Never on a glob path -- wildcard entries accept only `until:`/`arch:` (anything else is a parse error); name the file explicitly instead.
- If `--scripts` shows `postinst` calling `update-alternatives`, `ldconfig`, or `update-mime-database`, those side-effects don't run in a chisel rootfs -- either drop the dep or write a `mutate:` equivalent.
- Run once per target arch when multiarch differences are expected (`deb-list.py libfoo amd64`, then `deb-list.py libfoo arm64`).
- **Ignore the clutter.** deb-list prints everything the deb ships, including man pages, shell completions, `/usr/share/doc/**`, changelogs, examples. Those are excluded by convention (see "Exclude by Default" in `kb/_slice-conventions.md`) -- under `/usr/share/doc/` ship only legal files (`copyright`, and `NOTICE`/`LICENSE`-type notices where present).

Requires `dpkg-deb` + network to the mirror (archive.ubuntu.com / ports.ubuntu.com). No sudo or apt cache needed.

With this output, analyse:

#### 3a. Contents & file types

Understand what the package ships: binaries, libraries, config files, data files, scripts, headers, etc. Note architecture-specific paths.

#### 3b. Maintainer scripts

Chisel does not run maintainer scripts. Whatever `postinst`/`preinst` do (create symlinks, generate files, register alternatives), you must reproduce via:
- `contents` declarations for simple cases (symlinks, directories)
- `mutate:` scripts for logic

**No explicit `symlink:` if the deb already ships it.** Chisel preserves deb symlinks. Manual `symlink:` only for paths the deb doesn't ship (e.g. those created by maintainer scripts).

#### 3c. Binary analysis

For ELF binaries, determine shared library dependencies (via `ldd` / `lddtree` output). Cross-reference against the dependency tree to catch transitive runtime deps. List each provider explicitly in `essential:` even when it would come in transitively -- reviewers run `lddtree` (on emulated arches too) and reject a `bins`/`libs` slice missing any of them. The usual suspects: `libc6_libs`, `libgcc-s1_libs`, `libstdc++6_libs`.

#### 3d. Source package analysis

Use the source to:
- Understand what features/modules are compiled in
- Check for runtime file lookups (config paths, data directories, plugin dirs)
- Identify optional vs mandatory dependencies
- Check for hardcoded paths that must be included in slices

### Step 4: Ensure Consistency with Existing Slices

Before designing new slices, study existing SDFs on the target branch.

1. **Read representative SDFs** for similar packages. Use `slices/bash.yaml`, `slices/base-files.yaml`, `slices/openssl.yaml`, `slices/dpkg.yaml` as references.
2. **Follow naming conventions** from `kb/_slice-conventions.md` (Canonical Slice Names table). Use `libs` not `lib`, `bins` not `bin` (the table notes the rare `base-files`-style exceptions).
3. **Check shared dependencies.** If the target package depends on packages with multiple slices (e.g. `libc6_libs`, `libc6_config`), determine which _specific_ slice is needed. Do not over-depend.
4. **Verify no path conflicts.** Multiple slices from different packages can declare the same path ONLY if:
   - Both slices are in the same package, OR
   - The path is not extracted from a package (e.g. `{make: true}`, `{text: ...}`) and the inline definitions match exactly

   Search existing slices: `grep -r "/path/you/want" slices/`
5. **Respect the append-only principle.** Removing files from existing published slices is a regression. If you need a slimmer variant, create a new slice (`core`, `minimal`, etc.) rather than removing from an existing one.

### Step 5: Design the Slices

Choose the approach that fits the package best.

#### Approach A: Group by Type of Content

Best for most packages. Group files by their type. See the Canonical Slice Names table in `kb/_slice-conventions.md`.

Typical structure:
- `copyright` slice (mandatory, always present)
- `bins` for executables
- `libs` for shared objects
- `config` for configuration files
- `data`, `scripts`, `var`, etc. as needed

#### Approach B: Group by Function

Best for complex packages with distinct functional subsets (e.g. Python standard library, large runtime frameworks).

Typical structure:
- `core` -- minimum-functional subset
- `standard` -- fuller-featured above `core`
- Named functional slices (e.g. `file-formats`, `networking`, `crypto`)

Do NOT mix approaches arbitrarily within a single SDF.

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

### Step 7: Apply Formatting Rules and Self-Check

These are **mandatory**. CI and reviewers reject non-conforming SDFs.

After writing the SDF, run the bundled deterministic linter -- do not eyeball these rules:

```bash
scripts/_check-slice.py slices/<package>.yaml
```

It reads `format:` from `./chisel.yaml` automatically (or pass `--format N` / `--branch ubuntu-XX.XX`). It reports `block` (fix before commit -- CI/parse failure), `warn` (reviewers reject), `info` (nit / skipped). **Fix every `block` and every `warn` you can't justify** before moving on.

The script mechanically owns: sorting (contents paths and `essential` entries, bytewise ASCII -- CI checks with `LC_COLLATE=C sort -C`), slice-name validity, absolute paths, duplicate contents keys, arch names (list *order* there is a nit, not a gate), clutter exclusions, copyright presence, the version-gated fields (`hint`/`prefer`/`v3-essential`/essential-as-map/essential-as-list), and `hint:` length + style. Don't restate its work -- run it.

The rules it can't judge are the Path Entry Style and File Layout sections of `kb/_slice-conventions.md` -- read them and apply them by hand:

1. **File layout** -- global `essential:` right after `package:`, `copyright` slice last in `slices:`.
2. **Path style** -- multiarch `*-linux-*` globs, no trailing `*` on single-version sonames, major.minor-only version globs, narrow globs, inline option maps, comments on explicit symlinks.

For the glob-narrowness rule specifically, `grep -r "/shared/path" slices/` before declaring a path more than one package could own.
3. **yamllint gates** (`.github/yamllint.yaml`, which lives on `main`): 2-space indent, lines <= 100 chars, at most one consecutive blank line, comments aligned to content, at most one space inside `{ }`/`[ ]`.

Both sorted lists -- `contents:` paths and each slice's `essential:` entries -- are CI gates, not chisel parse errors; `check-slice.py` blocks on them anyway because the `lint` job will. `kb/_slice-definition-format.md` has the detail.

### Step 8: Test

Testing is mandatory. **Every package gets a spread test at `tests/spread/integration/<package>/task.yaml`** -- upstream ships one even for pure-library and data-only packages (`ca-certificates`, `base-passwd`, `fontconfig`, ...). The classification below controls test *depth* only, never whether the file exists.

**Testing blocks commit.** Do NOT proceed to Step 10 (commit) without tests landed. A `feat:` slice and its `test:` tests form one series -- both must exist before you stop. If tests aren't feasible, leave the slice uncommitted and report why; do not commit the slice alone.

#### Manual cut (always do this first)

Use the bundled `try-cut` helper to verify the cut succeeds without managing the temp root manually (NOTE: it removes the rootfs on exit -- installability only):

```bash
scripts/_try-cut [--arch ARCH] <package>_<slice>
```

When you need to poke around the resulting rootfs (chroot in, inspect files), cut manually instead:

```bash
mkdir rootfs/
chisel cut --ignore=unstable --ignore=unmaintained --release ./ --root rootfs/ <package>_<slice>
```

#### Write the test suite

Start from the scaffold rather than a blank file:

```bash
scripts/_scaffold-test.py slices/<package>.yaml > tests/spread/integration/<package>/task.yaml
```

It emits one fresh rootfs per slice and a `chroot` line for every declared binary, so coverage is complete by construction. Then do the real work per package kind:

- **Library** (e.g. `libssl3`): verify `.so` files exist and are valid ELF (`head -c4 | grep ELF`-style). Minimal depth acceptable -- but the task.yaml still exists.
- **Data-only** (e.g. certificate stores, locale data, fonts): install the slice **together with a consumer slice** and prove the consumer can use the data (e.g. a TLS client verifying against the shipped CA bundle, a renderer loading the font). File-existence checks alone are weak; pair with a consumer where one exists.
- **Simple utility** (e.g. `grep`, `sed`): `--version` + one representative functional test.
- **Application / major software** (e.g. `python3`, `nginx`, `curl`, `git`): thorough suite. Research first: read the package docs (features, flags, config), study the upstream test suite (`test*/`, `tests/`, `t/` in the source package), identify key functional areas (each gets at least one test), and check runtime lookups (`/etc/passwd`, `/tmp`, timezone/locale data).

The shape the scaffold produces:

```yaml
summary: Integration tests for <package>

execute: |
  # <package>_bins: fresh rootfs so a missing dep can't hide behind another test.
  rootfs="$(install-slices <package>_bins)"
  chroot "$rootfs" <command> --version  # replace with a real functional check
  # (for an http client: fetch a URL; for an interpreter: import core modules)
```

**Test design principles**:
- **Test real functionality**, not just file existence. A `bins` slice must prove its binaries actually work.
- **Test each functional slice.** If you have `bins` and `scripts`, both need tests.
- **One rootfs per test.** Call `install-slices` afresh for each test rather than reusing one rootfs -- leftover slices from an earlier test mask a missing dependency in a later one. This is a standard reviewer request.
- **Every binary in a `bins` slice must be exercised.** Reviewers reject untested binaries. A binary you can't drive fully still gets a skeleton test proving the dynamic linker resolves it -- run it and grep for its own usage/error text, e.g. `chroot "$rootfs" /usr/lib/foo/helper 2>&1 | grep -Fiq "usage"`.
- **Untestable means unshippable.** Reviewers push to drop rather than ship untested slices. (For data-only slices, the consumer pattern above is the test -- "no binaries" never means "no test".)
- **Set up the chroot before weakening a test.** If a chroot command fails on missing `/dev/null`, `/bin/sh`, or DNS, fix the environment per the "Chroot environment patterns" table in `kb/_spread-tests.md` -- do not retreat to file-existence checks.
- **Hermetic by default.** Generate inputs (secrets, digests, fixtures) inline; never apt-install extras into the test env. Exception: when the package's function IS the network path (CA bundles, TLS/http clients), hitting one stable well-known endpoint (e.g. `https://example.com`) is accepted upstream -- copy `resolv.conf` in per the chroot patterns table.

**Test hygiene** (recurring review nits):
- Drop `--arch "$chisel_arch"` from `install-slices` on v3+ branches -- it was a v2-era workaround, not needed post-v2. Older (v1/v2) branches may still want it.
- Use `"$rootfs"` (no trailing-slash/brace noise), quote every variable, and use bash arrays rather than string-joined args.
- Assert with `grep -Fiq` (`-F` literal, `-i` case-insensitive, `-q` quiet).
- No magic `sleep`s or unbounded retry loops -- bound every wait with a timeout so spread can't hang.
- `trap cleanup EXIT` to `umount` anything you bind-mounted (`/dev`, `/proc`). Some tools need `/proc` mounted in the chroot (see `systemd/test_standard.sh`).
- End files with a trailing newline.

Run with: `spread lxd:tests/spread/integration/<package>`

Then check coverage deterministically:

```bash
scripts/_check-test.py slices/<package>.yaml
```

It `warn`s when there's no test, or a test that exercises none of the binaries -- fix those before committing. It reports partial coverage as `info` with the list of untested binaries: review that list and add a check (or at least a linker-resolves skeleton) for each you reasonably can. Full coverage isn't demanded -- alternatives symlinks, multi-call binaries, and big suites are fine tested representatively.

### Step 9: Verify against docs

Before committing, cross-reference the authored SDFs against the official chisel documentation (the authoritative source of truth). Fix discrepancies now -- landing a commit and then finding it diverged means an avoidable amend.

```bash
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-docs/main/docs/how-to/slice-a-package.md
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-docs/main/docs/reference/chisel-releases/slice-definitions.md
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-docs/main/docs/reference/chisel-releases/chisel.yaml.md
```

`kb/_upstream-sources.md` lists the rest of the pages and the raw-URL pattern; it also carries the precedence rule for when they disagree with each other (tool behaviour wins). Rendered at `https://documentation.ubuntu.com/chisel/latest/<path>/` if you prefer. If these fetches fail -- offline / egress-restricted environment -- skip this step, rely on the `kb/` reference files + `check-slice.py`, and note the skipped verification in your final report.

Check: does the SDF use any undocumented fields or patterns? Does the design match documented recommendations? Is the `format:` version compatible with all features used? Fix any discrepancy before committing; note deliberate divergence in your final report.

If tool behaviour diverged from the docs during `chisel cut` (a field ignored, a wildcard that didn't match, mutate running differently), note it -- the tool source at `https://raw.githubusercontent.com/canonical/chisel/main/internal/setup/setup.go` is the ultimate arbiter.

### Step 10: Commit

**Precondition:** `scripts/_check-slice.py slices/<pkg>.yaml` reports no `block` findings, `scripts/_check-test.py slices/<pkg>.yaml` reports no `warn` (a test exists and exercises the binaries), `tests/spread/integration/<pkg>/task.yaml` exists and passes (`spread lxd:tests/spread/integration/<pkg>`), and Step 9 surfaced no unresolved discrepancy. If the linter blocks, the test is missing or exercises no binaries, or tests fail, stop -- do not commit a `feat:` slice with lint blocks or without working tests.

Commit in two steps (one category per commit): the `feat:` slice first, then the `test:` tests. Both must land before you stop.

```bash
git -C <repo> commit -m "feat(<pkg>): add <slice-list> slices"   # the SDF(s)
git -C <repo> commit -m "test(<pkg>): add integration tests"     # the spread test(s)
```

Commit messages follow `kb/_conventional-commits.md`.

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

Read live SDFs from the checkout -- they are canonical and can't go stale (Step 4 already mandates this):

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

## Common Pitfalls

(The rest of this file already covers dependency order, transitive deps, naming, globs, copyright, maintainer scripts, clutter, and testing -- these are the ones with no step of their own.)

1. **Ignoring architecture differences.** Use `{arch: ...}` for arch-specific paths -- inspect each target arch with `deb-list.py <pkg> <arch>` before assuming one layout.
2. **Adding speculative slices.** Only ship slices that are needed and testable. Speculative slices are rejected.
3. **Use-case-specific comments.** Comments like "this slice exists for app X" are rejected. Describe what the slice ships.
4. **Over-including "to be safe".** If a dep or path isn't demonstrably needed, leave it out (add a one-line comment noting why). Reviewers prune speculative deps.
5. **Shipping config for a tool that isn't sliced.** A config file for a program not in chisel-releases (e.g. a `logrotate` drop-in when `logrotate` isn't sliced) is dead weight -- drop it.
