---
name: chisel-slicer
description: >-
  Authors and tests chisel slice definition files (SDFs) against
  canonical/chisel-releases. Use when the user wants to slice an Ubuntu package
  or add a new SDF to their release branch. Commits locally when authorised;
  does not open PRs.
---

# chisel-slicer

Author slices against the user's `canonical/chisel-releases` checkout.

## roots and boundaries

- **Skill root** is the directory containing this `SKILL.md`. All `kb/` and
  `scripts/` paths below belong to that directory, not the target repository.
  Resolve helper paths from the loaded skill's location; keep the checkout as
  the working directory. For example:

  ```bash
  python3 "/absolute/path/to/chisel-slicer/scripts/_orientation.py"
  ```

  In the remaining commands, replace `<skill-root>` with that absolute path.
- **Checkout root** contains `chisel.yaml`, `slices/`, and `tests/spread/`.
  Repository paths below are relative to it. Run orientation first. If it
  reports `release: null`, stop and ask where the checkout is; do not clone one
  or guess a path. Confirm the reported release matches the request.
- Work on the checked-out branch and preserve unrelated changes. Commit only
  when authorised by the user and allowed by the session's workflow. Leave PR
  creation to the user.
- Published slices are append-only. Change one only for a demonstrated need;
  do not rename it or remove its effective cut contents. Subdivision is allowed
  if the original slice depends on the new subslices and preserves its contents.
  Before committing such changes, run
  `"<skill-root>/scripts/_check-diff.py" --base <target-branch>` and investigate
  warnings. The checker compares declared paths, so a valid subdivision still
  needs a before/after cut comparison.

## 1. validate the target

Read the orientation output for the release, maintenance status, manifest format
and available tools. Stop on an unmaintained branch or an existing
`slices/<pkg>.yaml`; report the conflict before authoring a new SDF.

```bash
python3 "<skill-root>/scripts/_deb-list.py" <pkg> <arch>
```

Keep the output for inspection. The helper lists a public Ubuntu archive package's
version, dependencies, file types and `postinst`. It needs `dpkg-deb`; without
`file(1)` it says so in its header and uses the bundled `_file.py`, which knows
ELF, scripts, links, compressed data and text but not versions or build ids.
Exit `1` means the package was absent from all public indexes checked for that
suite and architecture; exit `2` means verification failed (`dpkg-deb`, manifest,
network, index or extraction error). Stop on either non-zero result and report
which outcome occurred.
Neither establishes absence from Ubuntu Pro. The helper cannot authenticate to
Pro archives or reproduce arbitrary archive configuration. For those targets,
inspect the package through an already authorised archive setup; if unavailable,
report the access limitation and stop. Never invent contents from a failed lookup.

## 2. inspect the requested functionality

Inspect the root package before expanding dependencies. Establish the runtime
functionality to ship from the request and package contents; exclude speculative
features. Repeat this inspection for each required unsliced dependency.

- Use the listing for paths, types, modes and shipped symlinks. Inspect each
  target architecture when layouts or dependencies differ.
- Read `postinst` and relevant source code for generated files, alternatives,
  config/data/plugin lookups and optional features. Chisel does not run package
  maintainer scripts: reproduce required effects with contents declarations or
  `mutate:`, and omit install-time work that has no runtime purpose.
- Resolve shared libraries against the target release and architecture, using
  `lddtree` or a suitable target environment. Do not use host library resolution
  as evidence for another release or architecture. List needed providers
  explicitly in `essential:`, including providers that also arrive transitively.

## 3. resolve the required dependency graph

Use `Depends:` and `Pre-Depends:` as candidates, then retain the runtime needs
identified above. Do not automatically slice every package dependency, or add
`Recommends:` / `Suggests:` without evidence that selected functionality needs it.

1. Match each retained dependency to specific slices in the target checkout.
   A package having an SDF does not prove it ships the needed files. Inspect its
   slices; reuse sufficient ones and expand only missing runtime functionality.
2. Resolve alternatives (`a | b`) to a suitable concrete provider, respecting
   version and architecture constraints. Resolve virtual names through provider
   metadata; do not treat them as downloadable package names. Record the choice.
3. Use apt metadata only after confirming its suites, components and architecture
   match the target manifest. Otherwise use target archive metadata and the
   package listings. A recursive `apt-cache depends` dump is discovery input,
   not a resolved slice plan. If provider metadata is unavailable, report the
   unresolved edge rather than guessing.
4. Track visited packages and dependency edges. Inspect each required unsliced
   package before recursing. Detect cycles instead of recursing indefinitely:
   discard only edges shown to be install-time or outside selected functionality.
   If a required slice cycle remains, stop and report it for design resolution.
5. Record the retained graph, existing slices reused, new slices needed, and
   significant exclusions with reasons. Author dependencies before their consumers
   once the graph is resolved; update the plan if inspection finds another need.

Dependency field semantics: [Debian package relationships](https://www.debian.org/doc/debian-policy/ch-relationships.html).

## 4. design and write

Read representative SDFs from the target checkout: `bash`, `base-files`, `openssl`
and `dpkg`, choosing those relevant to the package. Read these references before
writing:

- `kb/_slice-conventions.md`: naming, grouping, legal files, exclusions, path
  style and file layout.
- `kb/_chisel-formats.md`: fields supported by the manifest format and installed
  chisel version. Use the actual format, not a release-name guess.
- `kb/_slice-definition-format.md`: contents options, essentials, conflicts and
  mutation semantics; consult the relevant sections for the design.

Write only inspected paths. Wire both cross-package dependencies and required
siblings (for example, a binary needing its own package's config). Search existing
SDFs for shared paths before declaring them; check conflicts with an actual cut.

## 5. lint and test

For every new or modified SDF:

```bash
"<skill-root>/scripts/_check-slice.py" slices/<pkg>.yaml
```

Fix every `block` and every unjustified `warn`. The helper covers mechanical SDF
rules; review layout and path style against `kb/_slice-conventions.md` and run
the target repository's applicable lint checks as well.

Read `kb/_spread-tests.md` before writing tests. It owns test depth, representative
coverage, rootfs isolation and interpretation of static checks. Scaffold only a
new test file; preserve existing tests:

```bash
mkdir -p tests/spread/integration/<pkg>
"<skill-root>/scripts/_scaffold-test.py" slices/<pkg>.yaml > tests/spread/integration/<pkg>/task.yaml
```

Replace the scaffold's author placeholders with checks that satisfy the testing
policy. It is a starting point, not proof of coverage. The test file is always
written: spread not being runnable here is reported at the gate as an
unavailable run, never as a reason to leave the file out. Then run:

```bash
"<skill-root>/scripts/_check-test.py" slices/<pkg>.yaml
```

Run a cut for each independently usable new slice when chisel is available:

```bash
"<skill-root>/scripts/_try-cut" --arch <arch> <pkg>_<slice>
spread lxd:tests/spread/integration/<pkg>
```

`_try-cut` removes its temporary rootfs on exit and proves installability only.
For rootfs inspection use the manual cut commands in `kb/_chisel-cli.md`. The cut
reads the checkout (`--release ./`) and the Ubuntu archive; a denied or failed
request to the upstream chisel-releases repository says nothing about it, so a
403 from `chisel info` or `git ls-remote` is not a reason to skip the cut. Run
spread when its backend is usable; orientation reports executables, not backend
readiness. Classify each required check using the completion gate below.

## 6. verify against upstream

Before completion, consult the official slicing guide and the SDF/manifest
references through `kb/_upstream-sources.md`. Check fields, design choices and
branch compatibility. Fix discrepancies or document justified divergence using
that reference's source precedence. If documentation is unreachable, record the
check as unavailable and use the bundled references; do not claim live verification.

## 7. completion and commit gate

Record each applicable lint, static test check, cut, spread run and documentation
check as **passed**, **failed** or **unavailable**, with evidence or a reason.

- **Passed:** the check ran and met its acceptance criteria. Static checks do not
  establish runtime success.
- **Failed:** malformed or missing tests, unfinished scaffold markers, SDF blocks,
  unjustified SDF warnings, test-check warnings, unresolved documentation conflicts,
  or observed cut/spread failures. Fix these before committing. If no fix is
  possible in scope, leave changes uncommitted and report the failure.
- **Unavailable:** a required tool, backend, archive or documentation endpoint
  could not be used. Report the exact missing verification and command to run.
  Do not relabel a product failure as unavailable. Leave changes uncommitted
  unless the user and session workflow permit commits with that verification
  gap. Continue writing and statically checking tests even when spread cannot run.

Apply this gate and the shared testing policy to every package added or changed,
including dependencies. Review assertions and coverage before declaring tests
finished.

When commits are authorised and the gate permits them, stage only task-owned
changes. Follow `kb/_conventional-commits.md` for messages and category separation.
Prepare both SDF and test changes before committing either; complete the series
before reporting success. Otherwise hand over the uncommitted changes.

## final report

Respond to the user for direct invocation, or to the parent agent when delegated.
Summarise:

- SDFs created or changed and their slice breakdown.
- Required dependency graph, reused slices, new dependencies and authoring order.
- Checks passed, failed or unavailable; representative coverage choices and gaps.
- Commit hashes, or why changes remain uncommitted.
- Remaining decisions or risks before the user opens a PR.

Keep the report concise; do not dump file contents or raw logs.
