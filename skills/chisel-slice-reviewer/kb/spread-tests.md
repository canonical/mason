# Spread Test Infrastructure

Integration tests in [chisel-releases](https://github.com/canonical/chisel-releases) use [spread](https://github.com/canonical/spread) to validate slices inside ephemeral containers.

## Layout

```
spread.yaml                                         # project config (backends, global prepare)
tests/spread/integration/<pkg>/task.yaml            # per-package test
tests/spread/lib/                                   # shared helpers (on PATH via spread.yaml)
```

## `install-slices` helper

Located at `tests/spread/lib/install-slices`. Added to `PATH` by `spread.yaml`. Usage:

```bash
rootfs="$(install-slices <pkg>_<slice> [<pkg2>_<slice2> ...])"
```

What it does:
1. Creates a temporary directory for the rootfs.
2. Runs `chisel cut --ignore=unstable --ignore=unmaintained --release "$PROJECT_PATH" --root "$rootfs" $slices` -- validates against the **local checkout**.
3. Automatically appends `base-files_chisel` to every cut (for manifest generation). You do not need to include it.
4. Retries on transient archive fetch failures (up to 3 attempts).
5. Prints the rootfs path to stdout.

NOTE: the `--ignore=unstable` / `--ignore=unmaintained` flags mean install-slices succeeds on devel/EOL branches where a bare manual `chisel cut` errors out -- pass them yourself when testing manually on such a branch.

## Two-layer testing model

- **Layer 1 -- installability**: `chisel cut` succeeds. The SDF parses, dependencies resolve, files extract. This is what the `install-slices` CI check validates.
- **Layer 2 -- functionality**: `chroot` + commands prove the sliced rootfs actually works. This is what spread tests validate.

Both layers are required. A slice that installs but doesn't function is rejected.

## Chroot environment patterns

Sliced rootfs is minimal. Tests that need more than bare files must set up the chroot:

| Need | Pattern |
|------|---------|
| Network (DNS) | `cp /etc/resolv.conf "${rootfs}/etc/"` |
| `/dev/null` | `mkdir -p "${rootfs}/dev" && touch "${rootfs}/dev/null"` |
| `/bin/sh` | `ln "${rootfs}/bin/bash" "${rootfs}/bin/sh"` (or whichever shell is available) |
| `/proc/self/exe` (Java) | `mkdir -p "${rootfs}/proc/self" && ln -sf <java-binary> "${rootfs}/proc/self/exe"` (see openjdk task.yaml) |

## Backends

`spread.yaml` configures two backends:

- **lxd** -- default for local development. Ephemeral LXC containers.
- **docker** -- used in CI for multi-arch testing: `amd64`, `arm64`, `armhf`, `ppc64el`, `s390x`, `riscv64`.
