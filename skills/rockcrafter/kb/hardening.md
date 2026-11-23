# Hardening a Rock

What every rock should do to run with the least privilege and the least content.
The keys themselves (`run-user`, `permissions`) are in the
[`rockcraft.yaml` reference](https://ubuntu.com/containers/rockcraft/docs/stable/reference/rockcraft-yaml/);
an internal user other than `_daemon_` is in
[Add an internal user to a rock](https://ubuntu.com/containers/rockcraft/docs/stable/how-to/crafting/add-internal-user-to-a-rock/).

## Run as non-root

- Set `run-user: _daemon_` unless the workload truly needs root. A rock that
  runs as root says why in the report.
- Pebble runs services as `run-user`, so every path a service writes
  (`/var/lib/<app>`, `/run/<app>`, logs) must be owned by that user. Give it
  ownership in the part that ships the path, with `permissions:`.
- A non-root service cannot bind a port below 1024: configure the workload on
  a higher port rather than running it as root.

## Ship only the workload

- Prefer a chiseled rock (`kb/rock-slices.md`): no shell, package manager or
  tools unless the workload calls them.
- Stage only what the workload needs at run time. Build tools go in
  `build-packages` / `build-snaps`, never into the rock.
- Pin what is built from source to a release tag, so a rebuild ships the same
  code.

## Prove it

The rock's tests check that the service runs as `run-user` and that the paths it
writes are writable (`kb/rock-tests.md`).
