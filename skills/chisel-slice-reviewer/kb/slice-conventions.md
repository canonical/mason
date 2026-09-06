# Slice Naming and Content Conventions

Conventions the chisel-releases reviewers enforce on Slice Definition Files (SDFs). These are not parse errors -- chisel accepts any well-formed slice name -- but a PR that ignores them is rejected.

## Canonical Slice Names

Names are convention but reviewers enforce them. The counts below are how many SDFs on `ubuntu-26.04` use each name, as a rough signal of how established it is; a name is not wrong for being rare, but a rare one wants a reason.

| Name | Used by | Contents |
|------|---------|----------|
| `bins` | 114 | Executables (plural; use `bins` not `bin`). The singular `bin` is only correct in `base-files`, whose `bin` slice builds the `/bin` and `/usr/bin` directory tree, not executables |
| `libs` | 404 | Shared libraries (plural; use `libs` not `lib`). Same `base-files` `lib` exception -- it makes the `/lib` and `/usr/lib` tree |
| `config` | 75 | Configuration files. Singular -- `configs` is not used. Break large configs into `<purpose>-config` (e.g. `modprobe-config`, `tmpfiles-config`, `pam-config`) |
| `scripts` | 29 | Shell helpers / non-binary executables. Not in `bins` |
| `data` | 21 | Static data (templates, tables, arch-independent payload). Not fonts -- those get `fonts` |
| `headers` | 15 | `/usr/include/...`. This is the name `-dev` packages use, not `dev` |
| `jars` | 5 | JVM artefacts |
| `copyright` | 690 | The deb copyright file, plus any upstream `NOTICE` / `LICENSE` / `ThirdPartyNotices` the package ships. Every SDF has one |
| `fonts` | 15 | Font files. Every font package uses this, not `data` |
| `core` | 38 | Minimum-functional subset. **Not "everything"**. Avoid `all` -- exactly one SDF uses it (`fonts-ubuntu`, an umbrella aggregate) |
| `standard` | 24 | Fuller-featured above `core` |
| `var` | 6 | Directories/files under `/var/` |
| `services` | 12 | Systemd service files |
| `modules` | 33 | Loadable modules/plugins |
| `locales` | 1 | Translation/locale files |
| `tables` | 1 | Static data tables (`dpkg_tables` ships `/usr/share/dpkg/*table`) |
| `chisel` | 1 | The generated manifest slice; only on `base-files` (`generate: manifest`) |
| `udev-rules` | 1 | udev rules (`systemd_udev-rules` ships `/usr/lib/udev/rules.d/*.rules`). The bare name `rules` is not used |
| `minimal` / `runtime` | 7 / 5 | Alternative subset names where `core` / `standard` do not fit the package's own vocabulary |

When the deb already names `<pkg>-core` (e.g. `fonts-dejavu-core`), keep the name verbatim.

There is no `license` or `notice` slice convention: upstream `NOTICE`, `LICENSE.txt` and `ThirdPartyNotices.txt` go **inside** the `copyright` slice next to the deb copyright file. Do not invent a separate slice for them.

Beyond this table, packages freely coin their own names for functional subsets -- `openjdk` ships `awt`, `jfr`, `management`; `binutils` ships `assembler`, `linker`, `archiver`. That is expected. The table covers the names that recur across packages; a package-specific name needs only to describe what it ships.

## Path Entry Style

Conventions on how a `contents:` path is written. Chisel accepts either form; reviewers do not.

- **Multiarch lib glob**: `*-linux-*`, not explicit triples -- `/usr/lib/*-linux-*/libnghttp2.so.14*:`.
- **Drop the trailing `*` for single-version sonames**: `libfoo.so.1:`, not `libfoo.so.1*:`.
- **Version globs pin major.minor only**, never the patch: `/usr/src/rustc-1.93.*/**`, `/usr/lib/perl5/*/`. A patch-level pin breaks on the next package update.
- **Keep globs narrow.** A broad `**` or a bare `*.pm` collides with other packages' paths. Add another path level to scope it (`.../perl5/*/auto/DBI/DBI.so:`). A path more than one package could own is a red flag -- grep the branch's `slices/` before declaring one.
- **No explicit `symlink:` if the deb ships it.** Chisel preserves the deb's own symlinks. Write `symlink:` only for paths the deb does not ship, e.g. ones a maintainer script creates.
- **Annotate explicit symlinks** with a comment: `/usr/bin/dotnet:  # Symlink to ../lib/dotnet/dotnet`.
- **Inline-style for short option maps**: `/path: {arch: [amd64, arm64]}`.
- **Arch list order is a nit, not a gate.** Alphabetical reads tidily, but real SDFs (`systemd`) use a priority order; do not block on it.

## File Layout

- Global `essential:` at the top of the file, right after `package:`.
- The `copyright` slice last in the `slices:` block.
- `package:` matches the filename stem -- `slices/foo.yaml` -> `package: foo`.
- One SDF per package. Never two packages in one YAML file.

## Exclude by Default

A `.deb` ships files a minimal rootfs never needs. Do **not** slice these unless a concrete runtime need is proven -- reviewers reject them, and `check-slice.py` flags them:

| Excluded | Paths | Notes |
|----------|-------|-------|
| **man pages** | `/usr/share/man/`, `/usr/man/` | never shipped |
| **shell completions** | `/usr/share/bash-completion/`, `/usr/share/fish/`, `/usr/share/zsh/`, `/etc/bash_completion.d/` | never shipped |
| **docs / changelogs** | `/usr/share/doc/**` | **except** the legal files below |
| **doc-base / lintian** | `/usr/share/doc-base/`, `/usr/share/lintian/` | packaging metadata, not runtime |
| **examples** | `/usr/share/doc/*/examples/`, `.../example*` | covered by the doc rule above |

Under `/usr/share/doc/<pkg>/`, ship only legal files: `copyright` always, and the upstream legal notices (`NOTICE`, `LICENSE`, `COPYING`, `AUTHORS`, with `.txt`/`.gz` variants) where the package carries them for licence compliance -- apache2, aspnetcore, and libaprutil1t64 do. Everything else there (README, changelog, NEWS, examples) is clutter. Shared-copyright packages instead ship `/usr/share/doc/<pkg>` itself as a symlink to another package's doc dir (gcc/cpp/binutils families); that bare entry is also fine.
