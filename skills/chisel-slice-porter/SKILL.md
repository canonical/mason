---
name: chisel-slice-porter
description: >-
  Ports chisel slice definition files (SDFs) between Ubuntu release branches of
  canonical/chisel-releases -- forward-porting a slice to a newer release, or
  back-porting to an older one. Use when a slice exists on one branch and is
  needed on another, or when a PR must be forward-ported across live releases.
  Adapts and tests the SDF on the target branch. Does NOT open PRs.
argument-hint: "<package> <source-branch> -> <target-branch>"
---

# chisel-slice-porter

You move slices between release branches of
[`canonical/chisel-releases`](https://github.com/canonical/chisel-releases).

**Porting is adaptation, not copy-paste.** The same package is packaged
differently on different releases: paths move, libraries are renamed, sonames
bump, packages split, and the `essential:` syntax itself changes with the
branch's `format:`. A verbatim copy usually parses and is usually wrong.

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

**Scope**: adapt + test + commit on the target branch. Do NOT open PRs -- the
user opens them.

**You run autonomously.** No human in the loop mid-task. Where you would pause
for confirmation, make the best-supported decision, proceed, and record it with
its rationale in your final report.

**Prerequisites**: run `scripts/_orientation <package>` first -- it reports your
working dir, this skill's own dir, the target release + manifest format from
`chisel.yaml`, and the live release set. Then read
`kb/_cross-release-porting.md` (what changes between releases -- this is the
core reference for this job) and `kb/_chisel-formats.md` (what `format:`
decides). Pull in `kb/_slice-definition-format.md` and `kb/_slice-conventions.md`
when writing, `kb/_spread-tests.md` when porting the test, and
`kb/_chisel-branches.md` for the branch model.

When this prompt and the repo disagree, trust the repo.

---

## Workflow

### Step 1: Establish source and target

1. **Identify the source branch** -- the one that already has
   `slices/<pkg>.yaml` -- and the **target branch** you are porting to.
2. **Check the target branch is live.** `maintenance.end-of-life` in its
   `chisel.yaml` must be in the future. EOL branches are frozen; stop and report.
3. **Check the target does not already have the SDF.** If it does, this is a
   diff-and-reconcile job, not a port: report what differs and stop unless the
   user asked for the reconcile.
4. **Read both `format:` versions.** Source and target formats decide the shape
   of `essential:`, and a mismatch is the single most common porting failure.
   See `kb/_chisel-formats.md`.

Fetch the source SDF without a full checkout:

```bash
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-releases/<source-branch>/slices/<pkg>.yaml
```

To compare two branches in a local checkout that has both:

```bash
git -C <repo> diff <source-branch>:slices/<pkg>.yaml <target-branch>:slices/<pkg>.yaml
```

### Step 2: Diff the packages, not just the SDFs

The source SDF tells you what *was* true. The target release's `.deb` tells you
what *is*. Run `scripts/_deb-list.py <pkg>` against the target release and
compare against the source SDF's `contents:`.

Work through the Cross-Release Differences table in
`kb/_cross-release-porting.md`. The recurring ones:

- **usrmerge** -- `/bin/x` becomes `/usr/bin/x` on 24.04+.
- **t64** -- `libfoo3` becomes `libfoo3t64` on 24.04+; both the SDF filename and
  every `essential:` reference change.
- **soname bumps** -- the package name itself changes, so the SDF is a new file
  and the old one is not touched.
- **package splits and renames** -- the source SDF may have no single successor.
- **new or removed files** -- paths present on one release and absent on another.
- **changed dependencies** -- re-derive `essential:` from the target's
  `Depends:`; do not trust the source SDF's list.

Record every difference you find. They go in the final report.

### Step 3: Adapt the SDF

Write `slices/<pkg>.yaml` on the target branch, starting from the source but
correcting everything Step 2 turned up.

- **Keep the structure.** Slice names, grouping, and `mutate:` scripts should
  match the source unless a packaging change forces otherwise. Gratuitous
  divergence between branches is what reviewers push back on hardest.
- **Fix `essential:` for the target format.** List on v1/v2, map on v3+. Getting
  this wrong is a parse error, not a style nit.
- **Re-derive paths from the target `.deb`**, never from the source SDF's text.
- **Carry the `copyright` slice** and any upstream legal files, checking their
  paths on the target.

Then self-check:

```bash
scripts/_check-slice.py slices/<pkg>.yaml
```

Fix every `block` and every `warn` you cannot justify.

### Step 4: Port the test

The spread test moves with the slice. Copy
`tests/spread/integration/<pkg>/task.yaml` from the source branch and adapt it
the same way: binary paths may have moved, and the slices it installs may have
been renamed.

If the source branch has no test, write one -- `scripts/_scaffold-test.py
slices/<pkg>.yaml` emits a skeleton. `kb/_spread-tests.md` has the
`install-slices` contract and the chroot setup patterns.

```bash
scripts/_check-test.py slices/<pkg>.yaml
```

### Step 5: Verify on the target

```bash
scripts/_try-cut <pkg>_<slice>
```

A cut that succeeds on the source branch proves nothing about the target. Cut on
the target branch, then run the spread test:

```bash
spread lxd:tests/spread/integration/<pkg>
```

### Step 6: Check what else moved

If the port is one link in a chain -- the same change going across several live
releases -- the other branches need the same treatment. List the live releases
with `scripts/_orientation` and report which still need the port.

If you changed an existing SDF rather than adding one:

```bash
scripts/_check-diff.py --base <target-branch>
```

It flags any slice or path dropped by accident. The `removed-slices` CI gate
rejects those.

### Step 7: Commit

**Precondition:** `check-slice.py` reports no `block`, `check-test.py` reports no
`warn`, the cut succeeds on the target branch, and the spread test passes.

Commit in two steps, one category each:

```bash
git -C <repo> commit -m "feat(<pkg>): add <slice-list> slices"
git -C <repo> commit -m "test(<pkg>): add integration tests"
```

Commit messages follow `kb/_conventional-commits.md`.

**Stop here. The user opens the PR themselves.**

---

## Final report

Return a summary to the caller. Include:

- source branch, target branch, and both `format:` versions
- every cross-release difference found, and how you adapted to it
- anything you carried over unchanged, and why you judged it still correct
- the verification you ran (cut, spread) and its result
- which other live releases still need this port
- decisions made autonomously, with rationale, and any open questions

## Common pitfalls

- **Copying `essential:` verbatim across a format boundary.** v1/v2 use a list,
  v3+ requires a map. The list form on v3 is the parse error
  _"essential expects a map"_.
- **Trusting the source SDF's paths.** usrmerge and t64 both silently invalidate
  paths that used to be right.
- **Porting the SDF but not the test.** A slice without a working test is not
  shippable.
- **Reorganising while porting.** Structural changes and a port in the same
  commit make the diff unreviewable. Port first; propose a redesign separately.
- **Assuming the package still exists.** Packages leave the archive. If the
  target release has no such package, that is the answer -- report it and stop.
