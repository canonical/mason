<!-- generated from _shared/chisel-cli.md by scripts/sync-shared.py -- edit the source, then make sync-shared -->

# Chisel: the Tool and its CLI

[Chisel](https://github.com/canonical/chisel) builds minimal Ubuntu root filesystems by extracting named _slices_ of `.deb` packages instead of whole packages. It is a Go tool that consumes a _chisel release_ (a branch of [chisel-releases](https://github.com/canonical/chisel-releases)) as its source of truth.

Docs: <https://documentation.ubuntu.com/chisel/en/latest/>

## Commands

```bash
chisel cut --release <ref> --root <dir> [--arch <a>] <pkg>_<slice> ...   # materialise rootfs
chisel find <pattern>                                                     # search slices
chisel info <pkg>_<slice>                                                 # inspect slice
chisel debug check-release-archives --release <ref>                       # download all pkgs, report cross-package path conflicts
```

Slices are addressed as `<package_name>_<slice_name>` -- the underscore separates package from slice (underscores are not allowed in Debian package names).

## `--release`

Accepts:

- `ubuntu-XX.XX` -- an online release branch.
- a directory path -- anything containing a `/`, e.g. `./` for the current checkout.
- omitted -- inferred from the host's `/etc/os-release`.

On a devel (unstable) or EOL (unmaintained) branch, add `--ignore=unstable` / `--ignore=unmaintained` or `cut` errors out.

## Inspecting the Repo Without a Full Checkout

```bash
# List live release branches
git ls-remote --heads https://github.com/canonical/chisel-releases.git 'ubuntu-*' \
  | awk '{print $2}' | sed 's|refs/heads/||'

# Read release manifest
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-releases/ubuntu-24.04/chisel.yaml

# Read an SDF
curl -fsSL https://raw.githubusercontent.com/canonical/chisel-releases/ubuntu-24.04/slices/bash.yaml

# Sparse clone (slices + chisel.yaml only)
git clone --filter=blob:none --no-checkout --depth 1 \
  -b ubuntu-24.04 https://github.com/canonical/chisel-releases.git /tmp/cr
git -C /tmp/cr sparse-checkout set slices chisel.yaml
git -C /tmp/cr checkout

# Diff slice between releases
git -C <repo> diff ubuntu-22.04:slices/coreutils.yaml ubuntu-24.04:slices/coreutils.yaml
```
