# Changelog

## 0.3.0

### Reference material split

`_shared/CHISEL.md` is gone. The reference is now seven subject files in `_shared/`, and a
skill's `shared.list` decides which of them it ships. Each file stands alone -- none
references a sibling, since a sibling may not have shipped.

- `slice-definition-format.md` -- SDF keys, entry options, wildcards, mutate, essentials, hints
- `chisel-releases.md` -- branch model, `chisel.yaml` schema versions
- `slice-conventions.md` -- slice names, path style, file layout, exclusions
- `cross-release-porting.md` -- cross-release differences, multiarch quirks
- `spread-tests.md` -- spread layout, `install-slices`, chroot patterns
- `chisel-cli.md` -- the CLI, `--release` handling, remote inspection
- `upstream-sources.md` -- upstream repos, doc index, precedence

### Corrections against upstream

Audited every factual claim against the chisel Go source, chisel-docs, and the real
chisel-releases branches. What changed:

- **`hint:` and `prefer:` are not gated by `chisel.yaml`'s `format:`.** Chisel validates both
  under every format; the gate is the chisel binary's version, and an older chisel ignores the
  key silently. `check-slice.py` had been hard-blocking valid SDFs on this -- now a warning
  that names it as branch convention. The one field the format really decides is `essential:`.
- **There is no `license` or `notice` slice convention.** No SDF in chisel-releases has one;
  upstream `NOTICE` / `LICENSE` / `ThirdPartyNotices` ship inside the `copyright` slice. The
  invented convention had been stated three times -- in the names table, the authoring
  workflow, and the review checklist.
- **Slice-name table corrected against all 690 SDFs on `ubuntu-26.04`**: `rules` is really
  `udev-rules`, `configs` and `dev` are not used, `fonts` was missing, fonts do not go in
  `data`, and each name now carries how many SDFs actually use it.
- **Sorting is a CI gate, not a parse error** -- and it covers `essential:` as well as
  `contents:`, which went undocumented.
- **`generate:` paths take `arch:` and reject `until:`**, which contradicted the file's own
  wildcard rule.
- Format table gains v4 and drops the "min chisel version" column that conflated the two gates.
- `--release` with no argument reads `/etc/lsb-release`, not `/etc/os-release`.
- Slice names are parse-validated (start `a-z`, >= 3 chars, `a-z0-9-` only) -- now documented.
- `mode:` pairs with `copy`/`make`/`text`, not `symlink`; defaults documented.
- Per-slice `essential:` takes same-package siblings, not just cross-package deps.
- Soname-bump example replaced with the real `librocksdb8.9` -> `9.10` -> `9.11` chain.
- `CONTRIBUTING.md` and the CI workflow definitions live on `main`, not on release branches.

### Linter

`check-slice.py` gained the path-shape parse errors it was missing: a glob carrying content
options, `make:` without a trailing `/`, `generate:` rules, and `prefer:` naming its own
package. `base-files` is now exempt from the `bin`/`lib` name warning it always tripped, and
`fonts-ubuntu` from `all`. Verified against every SDF on `ubuntu-26.04` and `ubuntu-24.04`:
no findings on either.

### Other

- `schemas/commands.manifest.yaml` removed -- nothing parsed it, and it restated `SKILL.md`.
- Path Entry Style and File Layout moved into `slice-conventions.md`; both commands had been
  carrying their own copies.
- Dispatch in `chisel-slicer/SKILL.md` now describes the plain-language route it always
  advertised but never specified.
- Dropped the rocks/rockcraft scope claim from the README, the tessl manifest, and the `/mason`
  usage text -- the repo has never contained either.
- Release procedure documented again in the README; `.ruff_cache/` and `.pytest_cache/` ignored.

## 0.2.0

Install migration to `npx tessl i` / `npx skills add` / `gh skill install`; `cli.js` removed
and the skill layout flattened under `skills/`.

## 0.1.0

Initial release.
