skill behaviour tests using [`pats`](https://github.com/lczyk/pats) 1.0

```
go install github.com/lczyk/pats/cmd/pats@v1.0.0
pats init     # builds and pins the sandbox image
pats run
pats score
```

- `pats.yaml` -- sandboxes, agents, scorers, suites
- `tasks/<vector>/<task>/` -- one task each: `task.yaml` (the prompt inline), any ground truth
- `bin/` -- the steps tasks share (`stage`, `collect`) and the sandbox's `provision`
- `scorers/` -- one uv script per scorer, helpers in `_lib.py`

the rock suites (`rockcrafter-create`, `rockcrafter-debug`) run in the `rock-lxd`
sandbox: an lxd system container with nesting, provisioned with real rockcraft,
since packing starts lxd instances and the tests run docker. locally they need
an lxd server (`lxc` remote); in ci the pats action sets lxd up on the runner
and the `ci-rockcrafter` suite runs a subset of both, as each pair takes
minutes. their steps run with `--rock` (`stage`, `collect`, `provision`); a
debug task's project lives in its `project/`, with spread tasks stored as
`task.spread.yaml` (pats reads any `task.yaml` as a task).

## the rock sandbox's workarounds

rockcraft's build instances are lxd containers inside the sandbox, itself an
lxd container. out of the box no rock packs there and no test runs. four
things are set for it, each for a fault that is not ours to fix: the first
three by `provision --rock`, the last in `pats.yaml`. drop one when its fault
is gone.

- **build instances see no apparmor** (two `lxc.mount.entry` lines on the inner
  lxd's default profile, over `/sys/kernel/security` and `/sys/module/apparmor`).
  a second-level container gets no apparmor namespace of its own, and snapd in
  it dies loading the `snap-confine` profile: `You need policy admin privileges
  to manage profiles`
  ([canonical/lxd#14770](https://github.com/canonical/lxd/issues/14770)). with
  no apparmor in sight snapd runs without it.
- **build instances are privileged** (`security.privileged=true` on the same
  profile). rockcraft maps the project dir's owner to the instance's root and
  makes each build instance by copying a base one. nested, lxd shifts the
  copy's files a second time, and rockcraft stops at `cannot create user data
  directory: /root/snap/rockcraft/<rev>: Permission denied`
  ([canonical/lxd#19608](https://github.com/canonical/lxd/issues/19608)). a
  privileged instance has no id map. it is still held by the sandbox's own user namespace.
- **a snap's output goes through pipes** (a wrapper, `/usr/local/bin/rockcraft`
  and `lxc`, ahead of `/snap/bin` on `PATH`). in this container a snap cannot
  write to a regular file it inherits as stdout or stderr: the output is lost
  and rockcraft exits 120. an agent's shell hands every command such a file.
- **`rockcraft test` runs with `CI` set** (`env` on `rock-lxd`). its spread
  backend boots an lxd virtual machine, and a container has no `/dev/kvm`
  (`Instance type "virtual-machine" is not supported on this server`). with
  `CI` set rockcraft takes its `ci` backend, the one a github workflow gets:
  the tests run on the machine itself, over root's login to `localhost`. the
  sandbox so has `sudo: true` and an ssh server, and a test's `docker` is the
  sandbox's own.

what to look for when one comes back: `rockcraft pack` fails with `Failed to
enable snapd service` (the first) or the `Permission denied` above (the
second), rockcraft exits 120 and prints nothing (the third), or spread aborts
every task with `allocate must print ADDRESS=<SSH address>` (the fourth).

the `ci` backend runs only the tests of a project that lists the machine's own
system (`ubuntu-24.04` under `systems:`), which is why `rock-lxd` has a `base`.
`provision --rock` checks that `rockcraft init` writes that system, and fails
the image build when it does not: set `base` to the system it names. a project
listing only other systems fails its tests here with `nothing matches provider
filter`, though a machine with kvm would run them.
