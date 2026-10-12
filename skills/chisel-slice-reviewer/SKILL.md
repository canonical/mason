---
name: chisel-slice-reviewer
description: >-
  Reviews chisel slice definition files (SDFs), branches or PRs in
  canonical/chisel-releases for correctness, dependencies, conventions, tests
  and forward-port requirements. Read-only; returns findings and a verdict.
---

# chisel-slice-reviewer

Review the supplied SDF as it stands, or a branch/PR against its target base.
State the scope and any assumption needed to interpret the request.

## roots and boundaries

- `<skill-root>` is the absolute directory containing this `SKILL.md`. Resolve
  `kb/` and `scripts/` there; keep the checkout as working directory.
- Run `uv run "<skill-root>/scripts/_orientation.py"` first. The working
  directory is the checkout; without one, stop and report that. Do not clone
  or guess one.
- Confirm that the files and manifest being checked match the review's revision
  and target release. Use read-only git and upstream reads; do not switch branches
  or edit the checkout. If the requested revision is not available to a helper,
  report that check as unavailable rather than checking different files.
- The review inspects; it does not cut slices or run spread. Runtime evidence
  is what already exists for the reviewed revision, its CI results; without
  it the review is incomplete, never passed. Read `kb/_verification.md` for
  check status and completion.

## 1. run static checks

For a branch or PR represented by the working tree, find what changed against
the target base and check it for append-only regressions:

```bash
uv run "<skill-root>/scripts/_check-diff.py"
```

The target base is the release branch named by `chisel.yaml`; orientation
reports it as `target base` and whether it is fetched. Pass `--base=<ref>` only
to review against something else.

Then run the single-file checkers on each SDF `_check-diff.py` lists, or on the
one SDF under review:

```bash
uv run "<skill-root>/scripts/_check-slice.py" slices/<pkg>.yaml
uv run "<skill-root>/scripts/_check-test.py" slices/<pkg>.yaml
```

Fold findings into the review under `kb/_verification.md`, then assess design
and runtime evidence before choosing the overall verdict.

## 2. assess correctness and design

Read the references relevant to the changed slices:

- `kb/_slice-definition-format.md` and `kb/_chisel-formats.md`: field semantics,
  manifest format and tool-version compatibility.
- `kb/_slice-conventions.md`: grouping, naming, legal files, path style and
  preservation of published slice contents.
- `kb/_dependency-policy.md`: target package inspection, runtime dependency
  selection, provider resolution and generated files.

Inspect actual target package contents where needed:

```bash
uv run "<skill-root>/scripts/_deb-list.py" <pkg> <arch>
```

Trace the retained dependencies and compare against the files actually supplied
by their slices. Review broad globs, shared paths and mutation effects. For
removed declarations, establish whether effective contents are preserved through
dependencies; static path comparison cannot decide this.

Validate disputed rules against the live sources in `kb/_upstream-sources.md`.
Distinguish parser errors, demonstrated runtime defects and repository
conventions. Do not turn an unsupported stylistic preference into a hard gate.

## 3. assess tests and upstream checks

Use `kb/_spread-tests.md` for coverage, assertions and rootfs isolation. Review
each affected package, including libraries, data and dependency packages.
Explicit binary references alone do not prove execution or meaningful tests.

Read the lint, cut and spread results CI holds for the reviewed revision, for
example with `gh pr checks` and the run logs; `kb/_upstream-sources.md` names
the workflows. A result for another revision or architecture is unavailable
evidence, not a pass.

Read `kb/_chisel-branches.md` and live contribution guidance linked from
`kb/_contributing.md` to establish forward-port obligations and PR requirements.
Check discovery completeness before claiming that all maintained releases are
covered. Package disappearance requires archive evidence, not a denied lookup.

## review report

Return findings with file, slice/path, evidence and proposed correction:

- **Blocking:** demonstrated parse/runtime failures or other hard requirements.
- **Should-fix:** justified convention, design or test deficiencies.
- **Nits:** optional improvements.

List passed, failed and unavailable checks separately, then give the overall
verdict under `kb/_verification.md`: approve, request-changes or incomplete.
Include remaining forward ports and verification gaps. The final message is
the review.
