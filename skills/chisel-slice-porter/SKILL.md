---
name: chisel-slice-porter
description: >-
  Ports chisel slice definition files (SDFs) between Ubuntu release branches of
  canonical/chisel-releases, adapting package contents, dependencies and tests
  to the target release. Use for forward-ports or back-ports. Does not open PRs.
---

# chisel-slice-porter

Adapt the source slices and tests to the user's target release checkout.

## roots and boundaries

- `<skill-root>` is the absolute directory containing this `SKILL.md`. Resolve
  `kb/` and `scripts/` there; run helpers with the checkout as working directory.
- Run `python3 "<skill-root>/scripts/_orientation.py"` first. If no checkout is
  present, ask where it is; do not clone or guess one.
- Confirm the checkout's release is the requested target. Work on its current
  branch and preserve unrelated changes. Read source branches with `git show`
  or upstream URLs; do not switch branches as part of the port.
- Read `kb/_verification.md` for blockers, unavailable checks and completion.
  Leave PR creation to the user. If asked to commit, follow `kb/_contributing.md`.

## 1. establish source and target

Identify the source revision, target release and requested packages. Read both
manifests and source SDFs/tests. Use `kb/_chisel-branches.md` for the branch model
and `kb/_chisel-formats.md` for format compatibility.

Establish target maintenance from its manifest; stop on an EOL or unknown target.
Check orientation's release-discovery status before drawing conclusions about
other releases. If the target already has an SDF, compare and report differences;
reconcile it only when that work was requested.

For a locally available source revision:

```bash
git show <source-ref>:chisel.yaml
git show <source-ref>:slices/<pkg>.yaml
git show <source-ref>:tests/spread/integration/<pkg>/task.yaml
```

If source objects are unavailable locally, read the upstream revision online.
Distinguish an absent source test from a failed source lookup.

## 2. inspect target packages

Read `kb/_cross-release-porting.md` for packaging differences and
`kb/_dependency-policy.md` for inspection and dependency evidence. For each
affected target package and architecture:

```bash
python3 "<skill-root>/scripts/_deb-list.py" <pkg> <arch>
```

Compare target contents, dependencies and maintainer scripts with the source
design. Record changed paths, package identities, features and dependency edges.
Inspect required unsliced dependencies before authoring their consumers. A failed
lookup does not establish that a package disappeared; apply `kb/_verification.md`
when inspection cannot complete.

## 3. adapt SDFs and tests

Read `kb/_slice-conventions.md` and the relevant sections of
`kb/_slice-definition-format.md`. Preserve the source's grouping unless target
packaging or verified functionality requires a change. Adapt paths, dependencies,
legal files and format-sensitive fields using the inspected target evidence.
Preserve effective contents of any published target slices being reconciled.

Read `kb/_spread-tests.md`. Port the source task and its shell helpers, adapting
binary paths, installed slices and assertions. If no source test exists, create
one; use `_scaffold-test.py` only for a new task, then replace its placeholders.
Apply the same policy to any dependency package authored during the port.

```bash
mkdir -p tests/spread/integration/<pkg>
"<skill-root>/scripts/_scaffold-test.py" slices/<pkg>.yaml > tests/spread/integration/<pkg>/task.yaml
```

## 4. verify the target

For every new or modified SDF:

```bash
"<skill-root>/scripts/_check-slice.py" slices/<pkg>.yaml
"<skill-root>/scripts/_check-test.py" slices/<pkg>.yaml
```

Run the target repository's applicable lint checks. Cut each independently usable
new or changed slice and run the affected spread tasks when tools/backends permit:

```bash
"<skill-root>/scripts/_try-cut" --arch <arch> <pkg>_<slice>
spread lxd:tests/spread/integration/<pkg>
```

For changes to published target SDFs, compare against the target base revision:

```bash
"<skill-root>/scripts/_check-diff.py" --base <target-base-ref>
```

Investigate removed declarations using before/after cuts. A successful source
cut is not target verification. For retained rootfs inspection, use
`kb/_chisel-cli.md`.

Consult the live sources in `kb/_upstream-sources.md` for the affected fields,
design and contribution requirements. Apply `kb/_verification.md` to every
result, including unavailable upstream access and unjustified warnings.

## final report

Return the completion status from `kb/_verification.md`, with:

- Source revision, target release, formats and architectures inspected.
- Packaging differences, adaptations, retained dependency graph and justified
  unchanged parts.
- Checks passed, failed or unavailable, with evidence and coverage gaps.
- Other maintained releases still needing the port, or the discovery gap that
  prevents establishing that list.

Respond to the user when invoked directly, or the parent agent when delegated.
