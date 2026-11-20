# Pebble Services and the Rock's User

Pebble is the rock's entrypoint (`/usr/bin/pebble enter`) and runs its declared
services. A CLI-only rock declares none.

```yaml
services:
  <svc>:
    override: replace
    startup: enabled
    command: <absolute-path-binary> [ <default-args> ]
    # on-failure: shutdown   # typical for single-service rocks
```

- `command` starts with an absolute path. `[ <default-args> ]` are overridable
  via `docker run <img> --args <svc> <args>`; without brackets the args are fixed.
- `entrypoint-service: <svc>` makes the rock behave like a classic single-binary
  image (`docker run <img> --flag` passes args to it).
- Top-level and per-service `environment:` set env vars; `checks:` adds Pebble
  health checks.

## Non-root

`run-user: _daemon_` (UID/GID 584792) unless the workload truly needs root.
Pebble runs services as `run-user`, so every path a service writes
(`/var/lib/<app>`, `/run/<app>`, logs) must be owned by `584792:584792` -- set it
with a part's `permissions:`:

```yaml
permissions:
  - {path: var/lib/foo, owner: 584792, group: 584792, mode: "755"}
```

A non-root service cannot bind ports below 1024: configure a higher port rather
than running as root.
