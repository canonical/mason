# Slices in a Rock

## Chiselled vs unchiselled

| | Chiselled | Unchiselled |
|---|---|---|
| `base` | `bare` (+ `build-base: ubuntu@XX.04`) | `ubuntu@XX.04` |
| `stage-packages` | slice names only: `<pkg>_<slice>` | whole debs: `<pkg>` |
| size / surface | minimal -- no shell, no apt unless sliced in | full Ubuntu base + debs |

Prefer chiselled. A part's `stage-packages` must not mix slices and whole debs. Rockcraft resolves slice names from the upstream chisel-releases branch matching `build-base` -- you list the top-level slices you need; `essential:` deps resolve automatically.

## Foundation slices

For a `bare` rock:

- `base-files_base` -- `/bin`, `/lib` usrmerge symlinks, `/tmp`, `/etc` skeleton. Needed for anything that runs a shell / shebang script or expects the standard FHS layout. `base-files_var` is the slimmer option for pure static/dynamic binaries that don't.
- `base-passwd_data` -- `/etc/passwd`, `/etc/group` (user/group lookups, `run-user`).
- `ca-certificates_data` -- when the workload makes TLS connections.
- `tzdata_*` -- when the workload needs zone data.
- `<pkg>_bins` / `<pkg>_libs` / `<pkg>_config` / `<pkg>_data` -- the workload itself.

## Shell and CLI gotchas

- Shebang scripts need the interpreter slice (`bash_bins`, `dash_bins`, `python3_*`) **and** `base-files_base` for the `/bin` symlink.
- `coreutils_bins` is the catch-all for scripts calling `cp`, `mv`, `cat`, ...
- Alternatives symlinks (`awk`, `sh`, `editor`) are created by maintainer scripts, which chisel doesn't run. Use a slice that ships the link (e.g. `gawk_bins` ships `/usr/bin/awk`) or create it in `override-build`/`override-prime`.

## Slices that aren't upstream yet

Slices that only exist in a chisel-releases checkout / fork **must not** be listed in `stage-packages` (rockcraft resolves those against upstream and fails with `slices of package "<pkg>" not found`). Cut them manually from a part whose source is the release:

```yaml
parts:
  <name>-slices:
    plugin: nil
    source: https://github.com/<user>/chisel-releases.git   # the fork
    source-type: git
    source-branch: <branch>                                 # ubuntu-XX.04-based branch with the new slices files
    override-build: |
      chisel cut --release ./ --root "${CRAFT_PART_INSTALL}" \
        base-files_base \
        base-passwd_data \
        <pkg>_bins
```

- Chisel's `--release` and cutting from a checkout: `kb/chisel-cli.md`.
- `--release ./` points chisel at the full checkout (every upstream slices file plus the new ones), so upstream deps resolve too.
- List **every** slice the rock needs in that one `chisel cut` (including ones that are upstream) -- don't split slices between `stage-packages` and a manual cut of the same tree.
- While iterating locally use `source: <path-to-checkout>` + `source-type: local`; switch to the git fork once pushed.
- Chisel is available in the rockcraft build environment; no `build-snaps` needed for it.
