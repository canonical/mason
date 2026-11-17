Use the chisel-slicer skill to revise the proposed package slices file `slices/libssl3t64.yaml` and its spread test, `tests/spread/integration/libssl3t64/`, for `ubuntu-26.04`.

You are in a checkout of canonical/chisel-releases (your current directory). The proposed files are uncommitted changes in the working tree. A reviewer left the review below. Address its findings where they hold up, and check them yourself: a reviewer can be wrong. Follow the skill's workflow and the conventions in its knowledge base.

This is an automated eval: work autonomously, do not ask questions, and do not open a PR. Produce the revised files and stop.

---

# Review -- `slices/libssl3t64.yaml` and `tests/spread/integration/libssl3t64/` (ubuntu-26.04)

## Scope and assumptions

- Reviewed revision: the working tree of the `ubuntu-26.04` checkout (`HEAD` = `a4240a6`). The slices file is untracked, so `_check-diff.py` treats it as a new file (no published predecessor in this history to diff against).
- Target release/branch: `ubuntu-26.04`, `chisel.yaml` `format: v3`, suites `resolute`(-updates/-security).
- Upstream GitHub is unreachable from this environment (`raw.githubusercontent.com` returns 403 "egress denied"), so upstream branch contents and CI results could not be read; see *Unavailable* below.
- Static analysis only -- spread was not run (and `spread` is not installed here).

## Blocking

### 1. `libcrypto` (and transitively `libs`) drops the `libzstd1` and `zlib1g` linkage

`slices/libssl3t64.yaml`, slice `libcrypto`, `essential:` lists only `libc6_libs`, but the shipped object links against both zlib and zstd:

```
readelf -d libcrypto.so.3
  NEEDED  libz.so.1
  NEEDED  libzstd.so.1
  NEEDED  libc.so.6
```

`_deb-list.py libssl3t64 amd64` confirms the deb's runtime deps: `libzstd1 (>= 1.5.5)`, `zlib1g (>= 1:1.1.4)`. Both are already sliced (`libzstd1_libs`, `zlib1g_libs`). The `libs` slice inherits the hole because it only reaches `libcrypto`. Any `chroot` executing a consumer will fail at load time with `libzstd.so.1: cannot open shared object file` (the existing tracked `tests/spread/integration/openssl` test does exactly `chroot "$rootfs" openssl sha1`, so it breaks too).

Correction -- add both to `libcrypto`'s essential map (sorted):

```yaml
  libcrypto:
    essential:
      libc6_libs:
      libzstd1_libs:
      zlib1g_libs:
```

### 2. The new test asserts the missing libraries and therefore fails

`tests/spread/integration/libssl3t64/task.yaml`, `libssl3t64_libcrypto` block, checks `libz.so.1` and `libzstd.so.1` after `install-slices libssl3t64_libcrypto`. Given finding 1, those files are not installed, so the file-existence loop fails. This is the same root cause; fixing the slice makes the assertion correct. (The test is actually *useful* here: it is currently red evidence of the slice defect.)

### 3. Test hardcodes `x86_64-linux-gnu`, breaking the multi-arch CI matrix

Same file; every path is `$rootfs/usr/lib/x86_64-linux-gnu/...`. The spread CI runs X64, ARM64, S390X and PPC64EL (per `kb/_spread-tests.md` / `.github/workflows/ci.yaml`), where the multiarch tuple is `aarch64-linux-gnu`, `s390x-linux-gnu`, `powerpc64le-linux-gnu`. The first `[ -f ... ]` fails on 3 of 4 CI architectures.

Correction -- follow the established portable-library pattern (`libffi8`, `libjansson4`, `libnftables1`):

```bash
lib="$(find "$rootfs" -maxdepth 4 -path "*/lib/*-linux-*/libssl.so.3" -print -quit)"
loader="$(find "$rootfs" -maxdepth 4 -path "*/lib/*-linux-*/ld*.so.*" -print -quit)"
chroot "$rootfs" "${loader#"$rootfs"}" --list "${lib#"$rootfs"}"
```

## Should-fix

### 4. `libs` omits the hard `Depends: openssl-provider-legacy`

`_deb-list.py libssl3t64` shows `Depends: ... openssl-provider-legacy`. That package ships `ossl-modules/legacy.so` (a dynamically loaded provider, and a hard dep, not a Recommends), and `openssl-provider-legacy.yaml`'s `libs` slice deliberately leaves out `libssl3t64_libs`. The comment in the proposed file claims this is "to avoid a cycle with `libssl3t64_libcrypto`", but no cycle exists: `openssl-provider-legacy_libs` currently declares only `libc6_libs`, so adding `openssl-provider-legacy_libs` to `libssl3t64_libs` (or to `libcrypto`) closes the graph without a loop, and that is the direction that should carry the edge. Either add it or state explicitly in-file why the legacy provider is intentionally not part of the `libs` closure.

### 5. `ldconfig -r` step is decorative

`printf ... > "$rootfs/etc/ld.so.conf"` + `ldconfig -r "$rootfs"` has no assertion afterwards; it proves nothing. Replace it with the loader `--list` pattern in finding 3, which actually fails when a NEEDED library is missing.

### 6. `libs` test never asserts `libcrypto.so.3`

The comment says `libssl.so.3`'s dep is supplied via essentials, but the loop doesn't check `/usr/lib/*-linux-*/libcrypto.so.3`. Add it (or resolve the real transitive deps with the loader) so the `libs` slice's dependency graph is actually asserted.

## Nits

- Use `grep -Fiq` per `kb/_spread-tests.md` (currently `grep -F`).
- Prefer `chroot "$rootfs" openssl sha1 <<< "test"` over `echo "test" | chroot ...`.
- The `legacy.so` comment names `openssl-provider-legacy_libs` -- good; update it together with finding 4 so the stated reason matches the actual edge.

## Check status

**Passed**
- Orientation (`_orientation.py`): working dir `/workspace`, target base `ubuntu-26.04`, manifest `format: v3`, Ubuntu `26.04`.
- `_check-diff.py`: merge base `a4240a6`; changed `slices/libssl3t64.yaml`; no append-only regressions (file is new).
- `_check-slice.py slices/libssl3t64.yaml`: passed, no findings (`essential:` map shape and contents/essential sorting correct for v3; `copyright` slice present and package-wide essential).
- `_check-test.py`: passed (info `no-binaries` -- expected, correct to hand-review library assertions).
- Package inspection (`_deb-list.py`): `libssl3t64`, `openssl-provider-legacy`, `zlib1g`, `libzstd1` all resolved for `resolute/amd64`.

**Failed**
- Runtime dependency closure of `libssl3t64_libcrypto`/`libssl3t64_libs` (findings 1, 4), demonstrated by `readelf -d` NEEDED entries vs. the slices' essentials.
- New spread test as written: `libz`/`libzstd` assertions (finding 2) and non-amd64 paths (finding 3).

**Unavailable**
- Upstream `canonical/chisel-releases` branch contents and PR CI (GitHub egress denied 403): could not diff against upstream `ubuntu-26.04`/`ubuntu-26.10`, and no CI result exists for this revision locally, so no cut/spread run can be cited as passing.
- Layer-2 runtime execution (spread) not run here; `spread` absent.
- Forward-port coverage to `ubuntu-26.10` (live, maintained) could not be verified.

## Forward ports and gaps

- `ubuntu-26.10` is a live, maintained branch; any fix here (especially the zlib/zstd deps and the legacy-provider edge) should be forward-ported there, and that branch should be checked for the same omission. Discovery was impossible here due to the blocked GitHub egress.
- Once the slice is fixed, re-run the loaders' `--list` on all four CI architectures, and re-run the tracked `tests/spread/integration/openssl` task (it consumes `openssl_bins` -> `libssl3t64_libs`).

## Verdict

**Request changes.** The proposed `libssl3t64.yaml` omits two hard runtime dependencies (`libzstd1_libs`, `zlib1g_libs`) that its own test asserts and that `libcrypto.so.3` requires at load time, so both the new test and the pre-existing `openssl` integration test will fail; the new test is additionally non-portable across the CI architecture matrix. Findings 4-6 should be addressed in the same pass.
