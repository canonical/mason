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
since packing and `rockcraft test` both start lxd instances. locally they need
an lxd server (`lxc` remote); in ci the pats action sets lxd up on the runner
and the `ci-rockcrafter` suite runs a subset of both, as each pair takes
minutes. their steps run with `--rock` (`stage`, `collect`, `provision`); a
debug task's project lives in its `project/`, with spread tasks stored as
`task.spread.yaml` (pats reads any `task.yaml` as a task).

## the rock sandbox's workarounds

rockcraft's build instances are lxd containers inside the sandbox, itself an
lxd container. out of the box no rock packs there. `provision --rock` sets
three things, each for a fault that is not ours to fix. drop one when its
fault is gone.

- **the lxd socket belongs to the `pats` group** (`snap set lxd daemon.group=pats`).
  pats starts the agent with a uid and a gid and no supplementary groups, so
  adding the agent user to `lxd` reaches nothing
  ([lczyk/pats#18](https://github.com/lczyk/pats/pull/18)).
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
  directory: /root/snap/rockcraft/<rev>: Permission denied`. a privileged
  instance has no id map. it is still held by the sandbox's own user namespace.

what to look for when one comes back: `rockcraft pack` fails with `LXD
requires additional permissions` (the first), `Failed to enable snapd service`
(the second) or the `Permission denied` above (the third).

`rockcraft test` does not run in this sandbox, and nothing here makes it: its
spread backend boots an lxd virtual machine, and a container has no `/dev/kvm`
(`Instance type "virtual-machine" is not supported on this server`). spread
reports every task as aborted, `test-rock.py` reports the check unavailable,
and `rock-tests-passed` tops out at 0.5.
