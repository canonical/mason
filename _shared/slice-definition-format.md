# Slice Definition File (SDF) Format

A _slice_ is a named subset of files from a single `.deb` package. Slices are defined in **Slice Definition Files (SDFs)** -- YAML files named `<package>.yaml` stored in the `slices/` directory of a chisel-releases branch.

Addressing: `<package_name>_<slice_name>` (underscore separates package from slice; underscores are not allowed in Debian package names). Used in `essential:` lists and on the `chisel cut` CLI.

Version-gated fields below are marked with the `chisel.yaml` `format:` that introduces them. Read `format:` from the target branch's own `chisel.yaml` before using one.

## Top-level Keys

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `package` | string | Required | Deb package name; **must match filename stem** (`slices/foo.yaml` -> `package: foo`) |
| `archive` | string | Optional | Selects archive from `chisel.yaml`'s `archives:`. Omit for default |
| `essential` | list (v1/v2) / map (v3) of `<pkg>_<slice>` | Optional | Applied to **every** slice in the file. Typically `<pkg>_copyright` |
| `slices` | map name -> body | Required | The slice definitions |

## Per-slice Keys

| Key | Type | Description |
|-----|------|-------------|
| `essential` | list (v1/v2) / map (v3) of `<pkg>_<slice>` | Cross-package dependencies |
| `contents` | map path -> entry options | Paths this slice installs. **Paths must be lexicographically sorted** |
| `mutate` | string (Starlark) | Mutation script run after all slices installed |
| `hint` | string, <= 40 chars | v3+ only. Length + printable-chars enforced by chisel core (parse error since v1.4.0); the noun-phrase _style_ is checked by `validate-hints` CI. Shown in `chisel find`/`info` output |

## Content Path Entry Options

| Key | Type | Description |
|-----|------|-------------|
| _(bare path)_ | -- | Extract from deb at this path |
| `copy` | string | Copy from different source path in deb |
| `make` | bool | Create empty directory; path must end with `/` |
| `mode` | int (octal) | Permission bits, e.g. `0755` |
| `text` | string | Inline literal file contents |
| `symlink` | string | Create symlink to this target |
| `arch` | string or list | Restrict to architectures: `amd64`, `arm64`, `armhf`, `i386`, `ppc64el`, `riscv64`, `s390x` |
| `mutable` | bool | Path may be modified by `mutate:` |
| `until` | `"mutate"` | Available during install; removed after mutate phase |
| `generate` | `"manifest"` | Path must be a directory glob ending `/**` (no other wildcards, no other options); chisel writes the manifest inside it |
| `prefer` | string, **v2+** | Resolve cross-package path conflicts. Value = name of **another** package in the release that also declares the path (that package wins); not your own package, not usable on globs |

## Debian Architecture Names

Always use Debian arch names in `arch:` fields: `amd64`, `arm64`, `armhf`, `i386`, `ppc64el`, `riscv64`, `s390x`. **Not** `x86_64`/`aarch64`.

## Wildcard Patterns

- `?` -- any single character except `/`
- `*` -- zero or more characters except `/`
- `**` -- zero or more characters including `/`

Wildcard paths accept only `until:` and `arch:` as entry options -- combining a glob with `copy`/`make`/`text`/`symlink`/`mode`/`mutable`/`prefer` is a parse error. Name the path explicitly instead.

## `mutate:` Semantics

- Written in [Starlark](https://github.com/google/starlark-go) (Google's restricted Python dialect; no imports, no exceptions, restricted stdlib). **Not Python.**
- Runs **once** after all slices in the install set are placed.
- Helpers: `content.list(d)`, `content.read(f)`, `content.write(f, s)`.
- Used for: merging passwd/group, filtering CA certs, splicing apt sources, etc.
- For merging/transforming existing files -- **not synthesis**. If a binary needs file `F`, ship `F` from the deb.
- `until: mutate` partner: file available to the script, deleted post-mutate.

## Arch-gated Essentials

Some deps only apply on certain arches. How you express that depends on the branch's `chisel.yaml` `format:`:

- **v1 / v2** -- `essential:` is a flat list; arch gating is backported via a parallel `v3-essential:` map alongside it (needs chisel >= 1.3.0):

  ```yaml
  essential:
    - libc6_libs
  v3-essential:
    dotnet-sdk-aot-10.0_libs: {arch: [amd64, arm64]}
  ```

- **v3** -- native: `essential:` itself **must** be a map (the list form is a chisel parse error: _"essential expects a map"_). Entries without arch gating are bare map keys; `{arch: ...}` values only where gated. `v3-essential:` is **rejected** on v3 (parse error) -- when forward-porting to a v3 branch, fold its entries into the `essential:` map.

  ```yaml
  essential:
    libc6_libs:
    dotnet-sdk-aot-10.0_libs: {arch: [amd64, arm64]}
  ```

Every SDF on a v3 branch uses the map form, arch-gated or not -- there is no list-form `essential:` on v3.

## `hint:` Style (v3+)

Optional one-line description of what a slice provides. Chisel caps it at 40 chars; the `validate-hints` CI check (spaCy) also enforces the style below. A hint is a **noun phrase**, not a sentence:

- sentence case: first letter uppercase.
- no finite verbs -- phrase as a noun fragment, not "Manages X" / "Views Y".
- no leading article (`a` / `an` / `the`).
- allowed chars only: letters, digits, spaces, and `. , ; ( )`. Separate fragments with `;`.
- no trailing punctuation or space; no double spaces.

e.g. `hint: System log viewer` (not `hint: Views system logs`).

## Manifest & Pro Archives

- **Manifest**: convention is `base-files_chisel` declaring `/var/lib/chisel/**: {generate: manifest}`, which makes chisel produce `/var/lib/chisel/manifest.wall`. Only touch when slicing `base-files`.
- **Pro slices**: SDF has `archive: <name>` -> `pro:`-tagged archive in `chisel.yaml` (`fips`, `fips-updates`, `esm-apps`, `esm-infra`).
