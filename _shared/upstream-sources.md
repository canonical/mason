# Sources of Truth

The knowledge in the mason reference files and the associated skills is derived from three upstream projects. When in doubt, **always defer to these sources** over anything written here.

## 1. `canonical/chisel` (tool behaviour)

The Go source code defines what chisel actually does: how it parses SDFs, resolves dependencies, extracts files, runs mutate scripts, handles wildcards, and validates fields. The tool's behaviour is the ultimate arbiter of what is valid.

- Repo: <https://github.com/canonical/chisel>
- Key paths: `internal/setup/` (SDF parsing), `internal/slicer/` (slice cutting logic)

## 2. `canonical/chisel-docs` (official documentation)

The documentation source renders to <https://documentation.ubuntu.com/chisel/en/latest/>. It is the authoritative reference for SDF format, CLI usage, and slicing workflows.

- Repo: <https://github.com/canonical/chisel-docs>
- Raw page access pattern: `https://raw.githubusercontent.com/canonical/chisel-docs/main/docs/<path>.md`; rendered at `https://documentation.ubuntu.com/chisel/latest/<path>/`
- Key pages:
  - `how-to/slice-a-package.md` -- canonical slicing workflow
  - `reference/chisel-releases/slice-definitions.md` -- SDF format specification
  - `reference/chisel-releases/chisel.yaml.md` -- release config schema (format versions, archives, maintenance)
  - `explanation/slice-design-approaches.md` -- grouping-by-content vs grouping-by-function
  - `explanation/slices.md` -- conceptual overview of slices
  - `reference/cmd/cut.md` -- `chisel cut` CLI reference
  - `reference/manifest.md` -- manifest format
  - `how-to/install-pro-package-slices.md` -- pro slices

## 3. `canonical/chisel-releases` (existing slices & conventions)

The collection of published SDFs is the ground truth for conventions, naming patterns, and reviewer expectations. Studying real SDFs is more reliable than any written convention doc.

- Repo: <https://github.com/canonical/chisel-releases>
- Key files on each release branch: `chisel.yaml`, `slices/bash.yaml`, `slices/base-files.yaml`, `CONTRIBUTING.md`
- `README.md` on `main` carries the live release-branch list
- CI workflows in `.github/` define the automated checks

Also: chisel-releases navigator <https://canonical.github.io/chisel-releases-navigator/>; Ubuntu release schedule <https://wiki.ubuntu.com/Releases>.

## Precedence

When sources conflict: **tool behaviour > chisel-docs > chisel-releases conventions > the mason reference files**.

When a reference file disagrees with the repo, trust the repo. When in doubt, read `slices/bash.yaml` or `slices/base-files.yaml` on the target release branch.
