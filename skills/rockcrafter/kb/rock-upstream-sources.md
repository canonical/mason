# Sources of Truth for Rocks

When this knowledge base and upstream disagree, upstream wins:
**tool behaviour** (rockcraft / chisel / pebble) > **docs** > **conventions**
(rocks published by Canonical) > this knowledge base.

- Rockcraft docs: <https://ubuntu.com/containers/rockcraft/docs/stable/>
  - `reference/rockcraft-yaml/` -- every key and its constraints
  - `reference/plugins/` -- build plugins and their keys
  - `reference/commands/#test` -- `rockcraft test` and `init --profile=test`
  - `reference/extensions/` -- framework extensions (flask, django, fastapi,
    go, expressjs, spring-boot)
  - `how-to/chiseling/install-slice/` -- installing a custom slice
- Rockcraft source: <https://github.com/canonical/rockcraft>
- Pebble: <https://github.com/canonical/pebble> (layer and service format)
- Published rocks for the same workload (e.g. `canonical/*-rock` repositories)
  show accepted conventions.
