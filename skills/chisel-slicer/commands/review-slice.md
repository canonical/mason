---
name: review-slice
description: >-
  Reviews chisel slice definition files (SDFs) in canonical/chisel-releases.
  Use when the user wants a slice / SDF / PR reviewed against chisel conventions:
  CI checks, dependency accuracy, naming, formatting, schema-version compliance,
  testing, and forward-port requirements. Read-only -- returns a review report.
---

You review slices in [`canonical/chisel-releases`](https://github.com/canonical/chisel-releases).

**Prerequisites**: read `shared/slice-definition-format.md` (SDF format) and `shared/chisel-releases.md` (branch model, schema versions) first, plus `shared/slice-conventions.md` for canonical naming. Pull in `shared/cross-release-porting.md` when the review touches a forward-port. This agent focuses on _what to check_ when reviewing.

You are read-only: inspect the diff / SDFs and return a review report. Do not edit files.

---

## Deterministic first pass

Before reasoning about anything, run the deterministic checks over the diff. When reviewing a PR or branch, one command does it all -- pass the branch the PR targets:

```bash
scripts/review-diff.py --base <target-branch>
```

It finds the changed SDFs and runs the three checkers over them, then prints findings grouped by severity plus a verdict, and exits non-zero if anything `block`s (the same command a CI PR-review job would call). The three it drives, also runnable on their own:

- `scripts/check-slice.py slices/<pkg>.yaml` -- static conventions: sorting, naming, absolute paths, duplicate contents keys, copyright presence, clutter exclusion, arch names, the format-gated `essential:` shape and `v3-essential:`, the path-shape parse errors (glob with content options, `make:` without a trailing `/`, `generate:` rules, `prefer:` naming its own package), and `hint:` length + mechanical style (the noun-phrase rule needs NLP -- `validate-hints` CI covers that, not this script). Reads `format:` from `./chisel.yaml` (or pass `--branch ubuntu-XX.XX`).
- `scripts/check-test.py slices/<pkg>.yaml` -- test coverage: `warn` if there's no test or it exercises none of the binaries; `info` listing untested binaries under partial coverage (normal for suites and alternatives symlinks -- judge whether the gaps matter).
- `scripts/check-diff.py --base <target-branch>` -- append-only regressions: a removed SDF or slice fails the `removed-slices` CI gate (unless the package left the archive); a content path dropped from a kept slice has no CI gate but is a regression reviewers reject.

Fold the output straight into your report: map `block` -> blocking, `warn` -> should-fix, `info` -> judge. Then spend your own judgement on what they can't check: dependency accuracy, test *depth*, design, forward-porting, and hint phrasing (noun phrase, no finite verbs -- see `shared/slice-definition-format.md`).

None cut a rootfs or run tests -- `chisel cut` (the `install-slices` CI check) and spread cover those.

---

## CI Checks

These automated checks run on every PR. Understand what each one validates:

| Check | Failure means |
|-------|---------------|
| `lint` | yamllint failure, or `contents:`/`essential:` entries not sorted (bytewise, `LC_COLLATE=C`) |
| `install-slices` | Slice can't `chisel cut`, or package not in archive for some arch |
| `removed-slices` | SDF or slice deleted, or an SDF renamed away -- breaking unless the package is gone from the archive |
| `forward-port-missing` | New slice in branch but not in newer live releases |
| `pkg-deps` | Informational diff of declared deps vs `apt depends`; non-blocking but reviewer signal |
| `validate-hints` | `hint:` text fails the spaCy style check. Runs on every `ubuntu-*` PR that touches `slices/`, whatever the branch's format |
| `spread` | Integration test failed in the CI test container (docker backend, multi-arch; lxd is the local default) |
| `cla-check` | CLA unsigned |

All checks must be green before review. `pkg-deps` is non-blocking but reviewers use it to cross-check dependency accuracy.

## Dependency Validation

- **`Depends:` only.** Not `Recommends:` or `Suggests:`. Including `Recommends:` is an immediate rejection.
- **Stay true to deb's declared deps.** Each direct `apt Depends:` should appear as an `essential:` entry. Cross-check via `pkg-deps` CI output.
- **Maintainer postinst is not mirrored.** If upstream `postinst` invokes another package's tool (e.g. `update-mime-database`), either drop the dep or write a `mutate:` equivalent. Do not pull in the tool's package as a dependency.
- **Only slices we need.** Speculative slices (slices added "just in case") are rejected.
- **Don't over-include.** A dep or path with no demonstrated need is pruned -- "if in doubt, leave it out". Flag deps that aren't justified by `ldd`/`lddtree` or a documented runtime lookup.
- **All transitive lib providers listed.** `bins`/`libs` slices must name every shared-lib provider `lddtree` shows, even transitive ones (`libc6_libs`, `libgcc-s1_libs`, `libstdc++6_libs`, ...). `pkg-deps` CI helps, but check `lddtree` per arch.
- **No config for un-sliced tools.** A config file for a program not sliced in chisel-releases (e.g. a `logrotate` drop-in with no `logrotate` slice) is redundant -- push to drop it.
- **Use-case-agnostic.** Comments like "this slice exists for app X" are rejected. Describe what the slice ships, not who it's for.

## Append-Only Principle

Published slices are **append-only in spirit**. Removing files from an existing slice is a regression for downstream consumers. If a slimmer variant is needed, create a new slice (`core`, `minimal`, or a more specific name) rather than removing from an existing one. `check-diff.py --base <target-branch>` catches these regressions deterministically.

## Naming Conventions

Verify against the Canonical Slice Names table in `shared/slice-conventions.md`:

- `bins` not `bin` for executables (the singular `bin` is only right in `base-files`, which builds the `/bin` directory tree)
- `libs` not `lib` for shared libraries (same `base-files` exception for the `/lib` tree)
- `config` for configuration files; break large configs into `<purpose>-config`
- `scripts` for non-binary executables (not in `bins`)
- `copyright` for the deb copyright **and** any upstream `NOTICE` / `LICENSE` / `ThirdPartyNotices` (mandatory). There is no separate `license` or `notice` slice -- flag one as wrong
- `core` for minimum-functional subset; avoid `all` -- `fonts-ubuntu` is the only SDF that legitimately uses it
- `fonts` for font files (not `data`); `udev-rules`, not bare `rules`
- When deb already names `<pkg>-core`, keep verbatim

Slice names must start with `a-z`, be >= 3 characters, and use only `a-z`, `0-9` and `-`. Chisel rejects anything else at parse time, so this is a hard gate rather than a convention.

## Formatting and Path Style

Hard gates, all of them mechanical -- `check-slice.py` reports every one, so fold its output in rather than re-deriving them:

1. **Contents paths and `essential:` entries sorted** bytewise (`LC_COLLATE=C`) within each slice. Both are CI `lint` gates.
2. **Arch names**: lowercase Debian names only (`amd64`, `arm64`, `armhf`, `i386`, `ppc64el`, `riscv64`, `s390x`) -- never `x86_64`/`aarch64`.
3. **File layout**: global `essential:` right after `package:`, `copyright` slice last, `package:` matching the filename stem, one package per file.

The style rules the script can't judge -- multiarch globs, soname trailing `*`, version-glob pinning, glob narrowness, when a `symlink:` is redundant, symlink comments, inline option style -- are in the Path Entry Style section of `shared/slice-conventions.md`. Review against that, and treat arch-list *order* as a nit rather than a gate.

## Schema Version Compliance

Only one SDF field is genuinely decided by `chisel.yaml`'s `format:` -- the shape of `essential:` (list on v1/v2, map on v3+) and, with it, whether `v3-essential:` is allowed. `check-slice.py` blocks on that deterministically; fold its output in. `shared/chisel-releases.md` is the reference.

`hint:` and `prefer:` are **not** format-gated -- chisel validates them under every format. Writing one on a v1/v2 branch is a convention violation worth a should-fix, not a parse error; do not report it as CI-breaking. The gate the script cannot see: `pro:` under `archives:` is v2+, and v1 uses a separate `v2-archives:` block.

## Testing Requirements

- **Binaries in a `bins` slice should be exercised** in spread tests. "Please test every binary being delivered" is a recurring ask, though representative coverage is accepted for suites and alternatives symlinks. `scripts/check-test.py slices/<pkg>.yaml` reports the coverage and lists untested binaries -- flag a test that exercises none of them, and judge whether partial gaps matter.
- **Untestable means unshippable.** Push to drop rather than ship untested.
- **~80% coverage** is a soft target mentioned in PR coverage comments. Not a hard gate but actively watched.
- **Functional slices need functional tests.** `--version` alone is insufficient for applications. Test actual functionality.
- **One rootfs per test.** Reusing a rootfs across tests lets leftover slices mask a missing dependency -- push to split into a fresh `install-slices` per test.
- **Hermetic by default.** Inputs generated inline, no apt-installing extras, bounded waits (no naked `sleep`/infinite retry), `grep -Fiq` for assertions. Exception: packages whose function IS the network path (CA bundles, TLS/http clients) may hit one stable well-known endpoint (e.g. `https://example.com`) -- upstream does.
- Tests live at `tests/spread/integration/<pkg>/task.yaml`. `shared/spread-tests.md` has the `install-slices` contract and the chroot setup patterns a test is expected to use.

## Forward-Port Requirements

- **All PRs must be forward-ported** to every newer live release branch. PR chain goes oldest -> newest.
- `forward-port-missing` CI auto-labels PRs that lack this.
- Exception: package gone from the newer archive -- auto-ignored.
- Cross-link forward-port PRs in descriptions.
- Non-forward-port PRs: mark with `### Forward porting\nn/a` in description.
- Trivial forward-port PRs (cherry-picks of approved changes) sometimes land on one approval. Do not rely on it for substantive work.

## Contribution Process

Defer to [`CONTRIBUTING.md`](https://github.com/canonical/chisel-releases/blob/main/CONTRIBUTING.md). Key points:

- **Branch off the target release branch**, not `main`. PRs into `main` are wrong.
- **Conventional commits**: `feat:`, `fix:`, `test:`, `ci:`, `chore:`, `docs:`, `refactor:`. Subject lowercase, imperative, <=50 chars, no trailing period. Body wrap 72.
- **Two maintainer approvals** required, CLA signed, green CI before review.
- **No force-push** after review comments.
- **One cohesive change per PR.** Don't mix unrelated slice definitions.

## Copilot Warning

GitHub Copilot auto-reviews and proposes patterns that reviewers reject:
- Inner-spaced arch lists: `{ arch: [ amd64 ] }` (wrong)
- `: {}` on essential entries (wrong for v1/v2)

Do not follow Copilot suggestions blindly.

---

## Review report

Return a structured review to the caller (this is your output -- it is not shown to the user as chat). Organise findings by severity:
- **blocking** -- hard-gate violations (formatting, missing copyright, wrong deps, regressions) that would fail CI or be rejected outright
- **should-fix** -- convention / naming / testing issues reviewers reliably push back on
- **nits** -- minor style points

For each finding, give the file, the slice/path, what's wrong, and the fix. End with an overall verdict (approve / request-changes) and note any forward-port PRs still required.

When fetching the diff to review, use read-only git (`git diff`, `git show`, `git log`) -- do not modify the working tree.
