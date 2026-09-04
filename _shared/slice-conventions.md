# Slice Naming and Content Conventions

Conventions the chisel-releases reviewers enforce on Slice Definition Files (SDFs). These are not parse errors -- chisel accepts a badly named slice -- but a PR that ignores them is rejected.

## Canonical Slice Names

Names are convention but reviewers enforce them. Use:

| Name | Contents |
|------|----------|
| `bins` | Executables (plural; use `bins` not `bin`). The singular `bin` is essentially only correct in `base-files`, whose `bin` slice builds the `/bin` directory tree, not executables |
| `libs` | Shared libraries (plural; use `libs` not `lib`). Same `base-files` `lib` exception -- it makes the `/lib` tree |
| `config` / `configs` | Configuration files. Break large configs into `<purpose>-config` (e.g. `modprobe-config`, `tmpfiles-config`, `pam-config`) |
| `scripts` | Shell helpers / non-binary executables. Not in `bins` |
| `data` | Static data (locales, templates, fonts) |
| `headers` | `/usr/include/...` |
| `jars` | JVM artefacts |
| `copyright` | Deb copyright file |
| `license` / `notice` | Upstream licence/notice (**not** deb copyright). Depends on `<pkg>_copyright` |
| `core` | Minimum-functional subset. **Not "everything"**. Avoid `all` except a rare umbrella-aggregate slice (e.g. `fonts-ubuntu` ships every font under `all`) |
| `standard` | Fuller-featured above `core` |
| `var` | Directories/files under `/var/` |
| `services` | Systemd service files |
| `modules` | Loadable modules/plugins |
| `locales` | Translation/locale files |
| `tables` | Static data tables (e.g. `dpkg_tables` ships `/usr/share/dpkg/*table`) |
| `chisel` | The generated manifest slice; only on `base-files` (`generate: manifest`) |
| `rules` | udev / polkit rules (e.g. `/usr/lib/udev/rules.d/*.rules`) |
| `dev` | Development files (headers + `.so` dev symlinks) in the by-function layout |

When the deb already names `<pkg>-core` (e.g. `fonts-dejavu-core`), keep the name verbatim.

## Exclude by Default

A `.deb` ships files a minimal rootfs never needs. Do **not** slice these unless a concrete runtime need is proven -- reviewers reject them, and `check-slice.py` (and the eval) flag them:

| Excluded | Paths | Notes |
|----------|-------|-------|
| **man pages** | `/usr/share/man/`, `/usr/man/` | never shipped |
| **shell completions** | `/usr/share/bash-completion/`, `/usr/share/fish/`, `/usr/share/zsh/`, `/etc/bash_completion.d/` | never shipped |
| **docs / changelogs** | `/usr/share/doc/**` | **except** the legal files below |
| **doc-base / lintian** | `/usr/share/doc-base/`, `/usr/share/lintian/` | packaging metadata, not runtime |
| **examples** | `/usr/share/doc/*/examples/`, `.../example*` | covered by the doc rule above |

Under `/usr/share/doc/<pkg>/`, ship only legal files: `copyright` always, and the upstream legal notices (`NOTICE`, `LICENSE`, `COPYING`, `AUTHORS`, with `.txt`/`.gz` variants) where the package carries them for licence compliance -- apache2, aspnetcore, and libaprutil1t64 do. Everything else there (README, changelog, NEWS, examples) is clutter. Shared-copyright packages instead ship `/usr/share/doc/<pkg>` itself as a symlink to another package's doc dir (gcc/cpp/binutils families); that bare entry is also fine.
