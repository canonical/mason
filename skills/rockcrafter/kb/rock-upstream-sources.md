# Sources of Truth for Rocks

When this knowledge base and upstream disagree, upstream wins:
**tool behavior** (rockcraft / chisel / pebble) > **docs** > **conventions**
(rocks published by Canonical) > this knowledge base.

- Rockcraft docs: <https://ubuntu.com/containers/rockcraft/docs/stable/>
  - `reference/rockcraft-yaml/` -- every key and its constraints
  - `reference/plugins/` -- build plugins and their keys
  - `reference/commands/#test` -- `rockcraft test` and `init --profile=test`
  - `reference/extensions/` -- framework extensions (flask, django, fastapi,
    go, expressjs, spring-boot)
  - `explanation/bases/`, `explanation/chisel/` -- bases and how slices are
    installed
  - `how-to/chiseling/install-slice/` -- installing a custom slice
  - `how-to/crafting/add-internal-user-to-a-rock/` -- users other than
    `_daemon_`
- Rockcraft source: <https://github.com/canonical/rockcraft>
- Spread: <https://github.com/canonical/spread> -- the task format
- Pebble docs: <https://documentation.ubuntu.com/pebble/> -- the layer and
  service format (`reference/layer-specification/`)
- Pebble source: <https://github.com/canonical/pebble>
- Published rocks for the same workload (e.g. `canonical/*-rock` repositories)
  show accepted conventions.
