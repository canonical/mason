# chisel-releases: Branch Model

The [chisel-releases](https://github.com/canonical/chisel-releases) repository holds the _chisel releases_ that `chisel` consumes: one Git branch per Ubuntu release, `ubuntu-XX.XX` (e.g. `ubuntu-22.04`, `ubuntu-24.04`, `ubuntu-26.04`).

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

Live release list: run `scripts/_orientation` -- it discovers the branches, their `format:`, and which are still maintained (end-of-life vs today) -- or the repo [README.md](https://github.com/canonical/chisel-releases/blob/main/README.md).
