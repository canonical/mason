# `rockcraft.yaml`

A rock is an OCI image built from a declarative `rockcraft.yaml`. Rockcraft runs
the build in an LXD (or multipass) instance through the craft-parts lifecycle and
packs the result into `<name>_<version>_<arch>.rock` (an OCI archive). Every rock
ships [Pebble](https://github.com/canonical/pebble) as its entrypoint; its services
are in `kb/pebble-services.md`.

## Lifecycle

Each part runs `PULL -> OVERLAY -> BUILD -> STAGE -> PRIME`, then the rock is
packed from `prime/`.

| Step | What happens | Key vars / dirs |
|---|---|---|
| PULL | fetch `source` | `$CRAFT_PART_SRC` (`parts/<part>/src/`) |
| OVERLAY | edit the base layer (`overlay-*`; not on `bare`) | `$CRAFT_OVERLAY` |
| BUILD | run the plugin / `override-build` | `$CRAFT_PART_BUILD`, output -> `$CRAFT_PART_INSTALL` |
| STAGE | merge every part's install dir, apply `organize`/`stage` | `$CRAFT_STAGE` (`stage/`) |
| PRIME | filter to the final payload, `override-prime` | `$CRAFT_PRIME` (`prime/`) |

`override-<step>` scriptlets replace the default step; `craftctl default` runs the
default inside one. `after: [<part>]` orders parts (no cycles).

## Top-level keys

```yaml
name: <name>               # lowercase, hyphenated
title: <Title>
version: "<XX.YY>"         # quoted -- see Version below
summary: <one line, < 80 chars>
description: |
  <what the rock contains and how to use it>
license: <SPDX id>         # optional -- only when the user states one
base: bare                 # or ubuntu@XX.YY -- see kb/rock-slices.md
build-base: ubuntu@XX.YY   # required with base: bare
run-user: _daemon_         # non-root, see kb/pebble-services.md
platforms:
  amd64:                   # Debian arch names only
package-repositories: ...  # only for a PPA, see Parts
services: ...              # kb/pebble-services.md
parts: ...
```

## Parts

- **Ubuntu packages**: one `plugin: nil` part with the packages in
  `stage-packages`. Packages from a PPA also need the repository declared:

  ```yaml
  package-repositories:
    - {type: apt, ppa: <owner>/<name>, priority: always}
  ```
- **Source build**: one part with the build plugin and a pinned source
  (`source-type: git`, `source-tag: <tag>`), and a second `plugin: nil` part
  whose `stage-packages` is the runtime (`kb/rock-slices.md`).
- **Framework extension** (`extensions: [<name>-framework]`): the extension
  generates the parts and the service, and the project must follow the layout
  it expects.

## Version

| Source of the main payload | `version:` |
|---|---|
| Ubuntu archive (`stage-packages` / slices) | `XX.YY` -- the patch level moves with SRUs |
| git `source-tag: vXX.YY.ZZ` | `XX.YY.ZZ` (pinned upstream release) |
| git `source-tag: vXX.YY` or `source-branch` | `XX.YY` |

Always quote it (`"1.27"`) so YAML doesn't turn it into a float.

## Build snaps

Check every `build-snaps` / `stage-snaps` entry (`go/1.23/stable`,
`node/22/stable`) with `snap info <snap>` -- don't assume a channel exists or is
current.
