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

A branch's format is a property of *that branch* -- read it from its own `chisel.yaml` `format:` (`orientation` prints it per live branch). The example column is illustrative, not an exhaustive branch list.

| Version | Branch (e.g.) | What the format itself decides |
|---------|---------------|--------------------------------|
| **v1** | `ubuntu-24.04` | Pro/esm archives live in a separate `v2-archives:` block. Archives may set `default:` |
| **v2** | `ubuntu-25.10` | Pro archives move into `archives:` under a `pro:` subkey; `v2-archives:` is now rejected, and `default:` with it |
| **v3** | `ubuntu-26.04`, `ubuntu-26.10` | `essential:` **must** be a map (`<slice>:` / `<slice>: {arch: ...}`) -- the list form is the parse error _"essential expects a map"_, and `v3-essential:` is rejected as obsolete. Adds `stores:` and per-package `store:` / `default-track:`. Bin slice definitions are read from `bin-slices/` as well as `slices/` |
| **v4** | none yet | As v3, except `bin-slices/` is no longer read -- bin slice definitions live in `slices/` alongside the rest |

Chisel rejects any other `format:` value outright. Two very old EOL branches (`ubuntu-22.10`, `ubuntu-23.04`) still declare the pre-v1 string `chisel-v1`, which current chisel cannot parse at all.

What the format does **not** decide: `hint:` and `prefer:`. Chisel validates both identically under every format -- neither is checked against `format:` anywhere in the parser. They are gated by the chisel *binary* (`prefer:` needs >= 1.2.0, `hint:` needs >= 1.4.0); an older chisel silently ignores the key rather than failing. `v3-essential:` is likewise chisel-version-gated (>= 1.3.0), not format-gated, and is valid on v1 and v2 branches alike.

In practice the release branches still track the two together -- no v1 or v2 branch uses `hint:` or `prefer:` -- so treat "v3+ only" as the branch convention it is, not as a rule chisel enforces.

Key fields: `format:`, `archives.ubuntu.suites[0]` (codename, e.g. `noble`), `archives.ubuntu.version` (mirrors branch suffix), `maintenance.end-of-life` (date).

**Always read `format:` from the target branch's `chisel.yaml` before writing `essential:`** -- getting its shape wrong is the one mistake here that fails the parse outright.
