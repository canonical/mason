# chisel-releases: Branch Model and `chisel.yaml`

The [chisel-releases](https://github.com/canonical/chisel-releases) repository holds the _chisel releases_ that `chisel` consumes: one Git branch per Ubuntu release, `ubuntu-XX.XX` (e.g. `ubuntu-22.04`, `ubuntu-24.04`, `ubuntu-26.04`).

## Branch Model

- **`main`** is meta-only: CI, workflows, contributing docs. **No `slices/` or `chisel.yaml` on `main`.** Never commit slice work on `main`.
- **All slice work targets a release branch.** Branch off the target release branch, not `main`.
- **EOL branches are frozen** (read-only). Check `maintenance.end-of-life` in `chisel.yaml`.
- **Branch suffix matches `chisel.yaml`'s `archives.ubuntu.version`**: `ubuntu-24.04` <-> `version: 24.04`.

Per-release branch root layout:

```
chisel.yaml                                    # release manifest
slices/<pkg>.yaml                              # one SDF per package
spread.yaml                                    # spread test config
tests/spread/integration/<pkg>/task.yaml       # integration tests
tests/spread/lib/                              # shared spread helpers
.github/                                       # workflows + CI scripts
```

Active branches accumulate hundreds of SDFs and keep growing; count a checkout with `ls slices/ | wc -l` (`orientation` prints this).

Live release list: run `scripts/orientation` -- it discovers the branches, their `format:`, and which are still maintained (end-of-life vs today) -- or the repo [README.md](https://github.com/canonical/chisel-releases/blob/main/README.md).

## `chisel.yaml` Schema Versions

A branch's format is a property of *that branch* -- read it from its own `chisel.yaml` `format:` (`orientation` prints it per live branch). The example column below is illustrative, not an exhaustive branch list.

| Version | Branch (e.g.) | Min chisel | Key additions |
|---------|---------------|------------|---------------|
| **v1** | `ubuntu-24.04` | any | Separate `v2-archives:` for pro/esm |
| **v2** | `ubuntu-25.10` | >= v1.2.0 | Pro archives unified under `archives:` via `pro:` subkey. Adds `prefer:` |
| **v3** | `ubuntu-26.04` and newer | >= v1.4.0 | Adds `hint:` on slices. `essential:` **must** be a map (`<slice>:` / `<slice>: {arch: ...}`) -- the list form is a parse error, and `v3-essential:` is rejected |

(`v3-essential:` -- the arch-gated backport -- is gated by chisel version, >= 1.3.0, not by format; it is valid on v1 and v2 branches alike.)

Key fields: `format:` (gates available features), `archives.ubuntu.suites[0]` (codename, e.g. `noble`), `archives.ubuntu.version` (mirrors branch suffix), `maintenance.end-of-life` (date).

**Always check `format:` in `chisel.yaml` before using version-gated features.** Writing `hint:` against a v1 branch or `prefer:` against a v1 branch produces invalid SDFs.
