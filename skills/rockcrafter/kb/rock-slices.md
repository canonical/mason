# Slices in a Rock

Which slices a rock stages, and how to choose between a chiseled and an
unchiseled rock. How `bare` and Ubuntu bases differ is in
[Bases](https://ubuntu.com/containers/rockcraft/docs/stable/explanation/bases/),
and how rockcraft installs slices in
[Chisel in Rockcraft](https://ubuntu.com/containers/rockcraft/docs/stable/explanation/chisel/)
and [Chisel a rock](https://ubuntu.com/containers/rockcraft/docs/stable/how-to/chiseling/chisel-existing-rock/).

## Chiseled or unchiseled

- Prefer chiseled: `base: bare` with slices (`<pkg>_<slice>`) in
  `stage-packages`. List only the top-level slices the workload needs; their
  `essential:` slices come with them.
- Unchiseled (an `ubuntu@` base with whole debs) only when the user chooses it
  -- and the report says so.
- One package without slices does not make the rock unchiseled. Keep
  `base: bare`, stage that package as a whole deb in a `plugin: nil` part of
  its own, and leave every package that has slices in its sliced part. Stage
  what the deb depends on as slices where those exist.
- Packages from a PPA are always staged whole, on an `ubuntu@` base: chisel
  only reads the Ubuntu archive.
- A part's `stage-packages` is all slices or all whole debs, never a mix; the
  parts of one rock may differ.

## Foundation slices

For a `bare` rock:

- `base-files_base` -- `/bin`, `/lib` usrmerge symlinks, `/tmp`, `/etc` skeleton. Needed for anything that runs a shell / shebang script or expects the standard FHS layout. `base-files_var` is the slimmer option for pure static/dynamic binaries that don't.
- `base-passwd_data` -- `/etc/passwd`, `/etc/group` (user/group lookups, `run-user`).
- `ca-certificates_data` -- when the workload makes TLS connections.
- `tzdata_*` -- when the workload needs zone data.
- `<pkg>_bins` / `<pkg>_libs` / `<pkg>_config` / `<pkg>_data` -- the workload itself.

## Runtime of a source build

What a built workload needs at run time, on top of `base-files_base` and
`ca-certificates_data`:

| Built with | Stage | Build side |
|---|---|---|
| go | nothing more | `build-environment: [CGO_ENABLED: "0"]` for a static binary |
| rust | `libc6_libs`, `libgcc-s1_libs` | |
| python, uv | `python3.X_standard`, `python3.X-venv_ensurepip` | `python3.X` is what `python3` depends on in the release |
| npm | `nodejs_bins` | the archive's node: `npm-include-node: false`, `build-packages: [nodejs, npm]` |
| maven, gradle | `openjdk-N-jre-headless_standard` | `build-packages` with the matching `openjdk-N-jdk-headless`; `N` is what `default-jre-headless` depends on unless the project pins one |
| cmake, meson, autotools, make | `libc6_libs` and a `<lib>_libs` slice per shared library (`ldd` on the built binary) | the matching `-dev` packages in `build-packages` |

## Shell and CLI gotchas

- Shebang scripts need the interpreter slice (`bash_bins`, `dash_bins`, `python3_*`) **and** `base-files_base` for the `/bin` symlink.
- `coreutils_bins` is the catch-all for scripts calling `cp`, `mv`, `cat`, ...
- Alternatives symlinks (`awk`, `sh`, `editor`) are created by maintainer scripts, which chisel doesn't run. Use a slice that ships the link (e.g. `gawk_bins` ships `/usr/bin/awk`) or create it in `override-build`/`override-prime`.

## Slices that aren't upstream yet

[Install a custom package slice](https://ubuntu.com/containers/rockcraft/docs/stable/how-to/chiseling/install-slice/)
shows the part that cuts slices from a chisel-releases checkout. On top of it:

- Never list such slices in `stage-packages`: rockcraft resolves those against
  upstream and fails with `slices of package "<pkg>" not found`.
- List **every** slice the rock needs in that one `chisel cut`, upstream ones
  too, starting with the foundation slices. Don't split them between
  `stage-packages` and the cut.
- Cut with `--release ./` from a checkout branched off the target release, so
  the upstream slices resolve too (chisel itself: `kb/chisel-cli.md`).
- While iterating, source the local checkout (`source-type: local`); once the
  branch is pushed, point the part at the fork (`source-type: git`,
  `source-branch: <branch>`).
