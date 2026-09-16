---
name: chisel-slicer
description: >-
  Authors and tests chisel slice definition files (SDFs) against
  canonical/chisel-releases. Use when the user wants to slice an Ubuntu package
  or add a new SDF to their release branch. Does not open PRs.
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
  Repository paths below are relative to it. Run orientation first. If no
  checkout is present, stop and ask where it is; do not clone one or guess a
  path. Confirm the target release matches the request.
- Work on the checked-out branch and preserve unrelated changes. Leave PR
  creation to the user.
- Read `kb/_verification.md` for blockers, check status and completion.
- When you make commits, use Conventional Commits as upstream does; see
  `kb/_contributing.md`.
- For changes to published slices, apply the preservation policy in
  `kb/_slice-conventions.md` and run
  `"<skill-root>/scripts/_check-diff.py" --base <target-base-ref>`.

## 1. validate the target

Read the orientation output for the release, maintenance status, manifest format
and available tools. Stop on an unmaintained or unknown target, or an existing
`slices/<pkg>.yaml`; report the conflict before authoring a new SDF.
Check release-discovery status before drawing conclusions about other releases.
Read `kb/_dependency-policy.md` for package inspection.

```bash
python3 "<skill-root>/scripts/_deb-list.py" <pkg> <arch>
```

Keep the output as evidence for the design and stop the affected package work
if inspection cannot complete.

## 2. inspect the requested functionality

Inspect the root package before expanding dependencies. Establish the runtime
functionality to ship from the request and package contents; exclude speculative
features. Repeat this inspection for each required unsliced dependency.

Use `kb/_dependency-policy.md` to inspect package contents, maintainer effects
and runtime lookups. Inspect each target architecture when layouts or
dependencies differ.

## 3. resolve the required dependency graph

Build and record the retained graph under `kb/_dependency-policy.md`, resolving
providers and checking existing slice contents. Apply the blockers in
`kb/_verification.md` to unresolved edges and cycles. Once resolved, author
dependencies before their consumers; update the graph if inspection finds
another runtime need.

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

Resolve findings under `kb/_verification.md`. Review layout and path style
against `kb/_slice-conventions.md` and run the target repository's applicable
lint checks as well.

Read `kb/_spread-tests.md` before writing tests. It owns test depth, representative
coverage and rootfs isolation. Scaffold only a
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

Run a cut for each independently usable new or changed slice when chisel is available:

```bash
"<skill-root>/scripts/_try-cut" --arch <arch> <pkg>_<slice>
spread lxd:tests/spread/integration/<pkg>
```

For rootfs inspection use the manual cut commands in `kb/_chisel-cli.md`. Check
backend readiness before running spread. Classify each required check using the
completion gate below.

## 6. verify against upstream

Before completion, consult the official slicing guide and the SDF/manifest
references through `kb/_upstream-sources.md`. Check fields, design choices and
branch compatibility. Fix discrepancies or document justified divergence using
that reference's source precedence. Apply `kb/_verification.md` when a source
cannot be reached.

## 7. completion gate

Apply `kb/_verification.md` to each applicable lint, static test check, cut,
spread run and documentation check, including dependency packages. Review
assertions and coverage under `kb/_spread-tests.md` before declaring tests
finished. Report complete, ready for remaining verification or blocked.

## final report

Respond to the user for direct invocation, or to the parent agent when delegated.
Summarise:

- SDFs created or changed and their slice breakdown.
- Required dependency graph, reused slices, new dependencies and authoring order.
- Checks passed, failed or unavailable; representative coverage choices and gaps.
- Remaining decisions or risks before the user opens a PR.

Keep the report concise; do not dump file contents or raw logs.
