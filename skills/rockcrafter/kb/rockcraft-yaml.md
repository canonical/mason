# `rockcraft.yaml`

How to fill in the file `rockcraft init` wrote. Every key and its constraints
are in the
[`rockcraft.yaml` reference](https://ubuntu.com/containers/rockcraft/docs/stable/reference/rockcraft-yaml/),
and the part lifecycle (`PULL -> OVERLAY -> BUILD -> STAGE -> PRIME`, which
pack-rock names on a failure) is in the
[craft-parts lifecycle](https://ubuntu.com/containers/rockcraft/docs/stable/common/craft-parts/explanation/lifecycle/).
This file holds only the choices the reference leaves to the author.

## Top-level keys

- `name`: the rock's name, as given to `rockcraft init`.
- `summary` and `description`: what the rock contains and how to use it,
  replacing init's placeholders.
- `license`: optional. Set it only when the user states one.
- `base` / `build-base`: `kb/rock-slices.md`.
- `run-user`: `kb/hardening.md`.

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

## Services

Pebble is the rock's entrypoint and runs its services
([Pebble in rocks](https://ubuntu.com/containers/rockcraft/docs/stable/explanation/pebble/),
[layer specification](https://documentation.ubuntu.com/pebble/reference/layer-specification/)).
A CLI-only rock declares none.

- One service per long-running process, started in the foreground: Pebble
  supervises it, so it must not daemonize.
- `command` starts with the binary's absolute path. Put the default arguments a
  user may replace in `[ ]`.
- `override: replace` and `startup: enabled`.
- `entrypoint-service` only when the rock should behave like a single-binary
  image, so that `docker run <img> <args>` passes the args to that service.

## Build snaps

Check every `build-snaps` / `stage-snaps` entry (`go/1.23/stable`,
`node/22/stable`) with `snap info <snap>` -- don't assume a channel exists or is
current.
