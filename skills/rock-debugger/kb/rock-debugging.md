# Debugging a rockcraft build

Where a failing `rockcraft pack` leaves its evidence, and how to reach the build
environment non-interactively.

## Logs

- `rockcraft pack -v` prints `Logging execution to '<path>'` at start and `Full execution log: '<path>'` on failure; logs live in `~/.local/state/rockcraft/log/rockcraft-*.log`. A failure's console tail usually already names the cause (`Failed to cut requested chisel slices`, `:: <scriptlet error>`, `Bad rockcraft.yaml content`).

## The build instance

- Build instances live in the LXD project `rockcraft`: `lxc --project rockcraft list`. They're kept between packs (incremental builds); `rockcraft clean` deletes them.
- `rockcraft pack --debug` opens a shell inside the instance at the point of failure (interactive -- not usable by a non-interactive agent). Instead, after a failure, start the kept instance and run commands non-interactively: `lxc --project rockcraft start <inst>; lxc --project rockcraft exec <inst> -- bash -c '<cmd>'`.
- Inside the instance the project is at `/root/project`, parts at `/root/parts/<part>/{src,build,install}`, plus `/root/stage`, `/root/prime`.

## A failing test

The failure block spread prints for a task shows each command it ran (`+ ...`)
and what came back; the last command is the one that failed. Re-run only that
task while fixing (`rockcraft test craft:<system>:spread/general/<task>`). With
docker on the host, reproduce without a test VM:

```bash
rockcraft.skopeo --insecure-policy copy oci-archive:<name>_<version>_<arch>.rock docker-daemon:<name>:latest
docker run --rm <name>:latest exec <command from the task>
```

How rock defects surface at run time:

| Symptom | Usual cause |
|---|---|
| `error while loading shared libraries: libfoo.so.N` | the slice shipping the library is missing -- add its `_libs` slice |
| "no such file or directory" for a binary that exists, or exit 127 | the command path is wrong, or the binary's interpreter (`#!` line or ELF loader) is not in the rock |
| `Permission denied` writing a path | the path is not owned by `run-user` -- `permissions:` |
| service exits at once, nothing answers | read `docker logs <container>`: Pebble prints the service's own error |
| `bind: permission denied` on a port | a privileged port under a non-root `run-user` -- configure a port above 1024 |

Decide whether the rock or the test is wrong from what the workload is
documented to do, not from what makes the task pass. Fix a wrong assertion;
never drop or weaken a check of real behaviour to get green.
