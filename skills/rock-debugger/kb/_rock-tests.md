# Rock Tests

Rock tests are [spread](https://github.com/canonical/spread) tasks run by
`rockcraft test` on its `craft` backend: rockcraft packs the rock, boots a test
VM, and the suite's `prepare` loads the packed rock (`$CRAFT_ARTIFACT`) into
docker there. Every task then exercises the rock through docker.

## Layout

`rockcraft init --profile=test --name <rock-name>` scaffolds the suite next to
`rockcraft.yaml` without touching it:

```
rockcraft-test.yaml            # an older rockcraft scaffolds spread.yaml: rename it and drop its `project:` key
spread/.extension              # the craft backend -- leave as scaffolded
spread/general/<task>/task.yaml
```

- `--name` must be the rock's `name`: the image is loaded as `<name>:latest`.
- One directory per task under `spread/general/`; replace the scaffolded
  `test` task, never leave its placeholder.
- `rockcraft test` runs every task; `rockcraft test craft:ubuntu-24.04:spread/general/<task>`
  runs one.

## What to test

A test proves the workload works, not that files exist. `--version` alone is
not a test.

- **CLI rock**: run each shipped binary that matters through Pebble with a
  representative input, and assert on its output:

  ```yaml
  summary: xxd dumps its input as hex
  execute: |
    printf 'A' | docker run --rm -i <name>:latest exec /usr/bin/xxd -p | MATCH "^41$"
  ```

- **Service rock**: start it detached, wait with a bound, then talk to it from
  the VM; stop it in `restore`:

  ```yaml
  summary: redis answers a ping
  execute: |
    docker run -d --name kv -p 6379:6379 <name>:latest
    retry --times 30 --delay 1 -- redis-cli -p 6379 ping | MATCH "^PONG$"
  restore: |
    docker rm -f kv || true
  ```

  Install tools the task needs in the VM (`apt install --yes retry redis-tools`)
  in `prepare`, never into the rock.
- **The rock as a whole**: the service runs as `run-user` (not root), and the
  paths it writes are writable -- these are what break when `permissions:` or a
  slice is missing.

Keep each task to one behaviour so a failure names it. Bound every wait; spread
kills a task only at `kill-timeout`. `MATCH` (spread's grep) fails the task when
nothing matches.

## Results

`rockcraft test` exits non-zero when a task fails; spread's summary names the
failed tasks and prints their output. A test VM that cannot start (no LXD, no
network) leaves the tests unrun, not failed.
