# Rock Tests

Rock tests are [spread](https://github.com/canonical/spread) tasks run by
`rockcraft test` on its `craft` backend: rockcraft packs the rock, boots a test
VM, and the suite's `prepare` loads the packed rock into docker there. Every
task then exercises the rock through docker. The command and its options are in
the [commands reference](https://ubuntu.com/containers/rockcraft/docs/stable/reference/commands/#test),
and the task format (`task.yaml` keys, `MATCH`, `kill-timeout`) in spread's
README. This file holds what a rock's suite should contain.

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

## What to test

A test proves the workload works, not that files exist. `--version` alone is
not a test.

- **CLI rock**: run each shipped binary that matters through Pebble with a
  representative input, and assert on its output:

  ```yaml
  summary: jq filters JSON
  execute: |
    echo '{"a": 1}' | docker run --rm -i <name>:latest exec /usr/bin/jq .a | MATCH "^1$"
  ```

- **Service rock**: start it detached, wait with a bound, then talk to it from
  the VM; stop it in `restore`:

  ```yaml
  summary: nginx serves its default page
  execute: |
    docker run -d --name web -p 8080:8080 <name>:latest
    retry --times 30 --delay 1 -- curl -sf http://localhost:8080/ | MATCH "nginx"
  restore: |
    docker rm -f web || true
  ```

  Install tools the task needs in the VM (`apt install --yes retry curl`) in
  `prepare`, never into the rock.
- **The rock as a whole**: the service runs as `run-user` (not root), and the
  paths it writes are writable -- these are what break when `permissions:` or a
  slice is missing.

Keep each task to one behavior so a failure names it, and bound every wait:
spread only kills a hung task at `kill-timeout`.

## Results

`rockcraft test` exits non-zero when a task fails; spread's summary names the
failed tasks and prints their output. A test VM that cannot start (no LXD, no
network) leaves the tests unrun, not failed.
