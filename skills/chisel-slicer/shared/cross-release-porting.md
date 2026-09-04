<!-- generated from _shared/cross-release-porting.md by scripts/sync-shared.py -- edit the source, then make sync-shared -->

# Porting Slices Across Ubuntu Releases

SDFs for the same package differ across Ubuntu release branches. Forward-porting is **adaptation, not copy-paste**. Always run `deb-list.py` against each target release and verify actual `.deb` contents.

## Cross-Release Differences

| Category | Example | What changes |
|----------|---------|-------------|
| **usrmerge** | `/bin/bash` -> `/usr/bin/bash` | Ubuntu 24.04+ moved binaries from `/bin/` to `/usr/bin/`. Update `contents` paths per release |
| **t64 transition** | `libssl3` -> `libssl3t64` | Ubuntu 24.04+ renamed libraries for 64-bit `time_t`. Update `essential` deps and copyright refs |
| **Package splits/renames** | Transitional packages, new soname packages | May need entirely different SDF structure or filename |
| **Soname bumps** | `librocksdb9.11` -> `librocksdb10` | Old SDF deleted (archive no longer carries it); new SDF with new filename |
| **Essential syntax** | List (`- foo_bar`) vs map (`foo_bar:`) | Gated by the branch's `chisel.yaml` `format:`. v3 branches **must** use map syntax in `essential:` (the list form is a parse error, and `v3-essential:` is rejected -- fold its entries into `essential:`); v1/v2 use the list, with `v3-essential:` alongside it for arch gating |
| **Slice granularity** | `bashbug` inline in `bins` (24.04) vs separate `bashbug` slice (26.04) | Newer releases may demand finer-grained decomposition |
| **New/removed files** | New config files, removed scripts | `.deb` contents change between releases. Some paths exist in one release but not another |
| **Dependency changes** | New deps added, old deps dropped | `Depends:` may differ. Always re-check with `deb-list.py` or `apt-cache depends` |

## Multiarch Quirks

- **`binutils-common` per-arch** despite `Architecture: all`-looking contents. Don't assume one SDF covers all arches without checking.
- **Cross-toolchain packages** (`<tool>-<triple>-linux-gnu`, e.g. `binutils-aarch64-linux-gnu`) ship prefixed binaries (`aarch64-linux-gnu-ld`). Unprefixed symlinks (`/usr/bin/ld -> aarch64-linux-gnu-ld`) are **not** in the cross deb -- consumers create them. Convention: arch-specific SDFs leave them out; top-level `binutils` SDF carries the unprefixed name with a `# Symlink to ${ARCH_TRIPLET}-ld` comment.
- **`/proc/self/exe` workaround** for chroot Java tests (chroot breaks `/proc/self/exe`, which the JVM launcher reads): inside the rootfs, `mkdir -p "${rootfs}/proc/self" && ln -sf <path-to-java-binary> "${rootfs}/proc/self/exe"` -- see the openjdk `task.yaml` files for the convention.
