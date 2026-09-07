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

## Test design principles

- **Test real functionality**, not just file existence. A `bins` slice must prove its binaries actually work.
- **Test each functional slice.** If a package ships `bins` and `scripts`, both need tests.
- **One rootfs per test.** Call `install-slices` afresh for each test rather than reusing one rootfs -- leftover slices from an earlier test mask a missing dependency in a later one. This is a standard reviewer request.
- **Every binary in a `bins` slice must be exercised.** Reviewers reject untested binaries. A binary you can't drive fully still gets a skeleton test proving the dynamic linker resolves it -- run it and grep for its own usage/error text, e.g. `chroot "$rootfs" /usr/lib/foo/helper 2>&1 | grep -Fiq "usage"`.
- **Untestable means unshippable.** Reviewers push to drop rather than ship untested slices. For data-only slices the consumer pattern is the test -- "no binaries" never means "no test".
- **Set up the chroot before weakening a test.** If a chroot command fails on missing `/dev/null`, `/bin/sh`, or DNS, fix the environment per the chroot patterns table above -- do not retreat to file-existence checks.
- **Hermetic by default.** Generate inputs (secrets, digests, fixtures) inline; never apt-install extras into the test env. Exception: when the package's function IS the network path (CA bundles, TLS/http clients), hitting one stable well-known endpoint (e.g. `https://example.com`) is accepted upstream -- copy `resolv.conf` in per the chroot patterns table.

## Test hygiene

Recurring review nits:

- Drop `--arch "$chisel_arch"` from `install-slices` on v3+ branches -- it was a v2-era workaround. Older (v1/v2) branches may still want it.
- Use `"$rootfs"` (no trailing-slash/brace noise), quote every variable, and use bash arrays rather than string-joined args.
- Assert with `grep -Fiq` (`-F` literal, `-i` case-insensitive, `-q` quiet).
- No magic `sleep`s or unbounded retry loops -- bound every wait with a timeout so spread can't hang.
- `trap cleanup EXIT` to `umount` anything you bind-mounted (`/dev`, `/proc`). Some tools need `/proc` mounted in the chroot (see `systemd/test_standard.sh`).
- End files with a trailing newline.

## Backends

`spread.yaml` configures two backends:

- **lxd** -- ephemeral LXC containers. The local default, and what CI runs
  (`.github/workflows/spread.yaml` sets `backend: "lxd"`) across a self-hosted
  runner matrix: X64, ARM64, S390X, PPC64EL.
- **docker** -- also defined in `spread.yaml`, but not what the CI job drives.
