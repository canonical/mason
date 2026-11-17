skill behaviour tests using [`pats`](https://github.com/lczyk/pats) 1.0

```
go install github.com/lczyk/pats/cmd/pats@v1.0.0
pats init     # builds and pins the sandbox image
pats run
pats score
```

- `pats.yaml` -- sandboxes, agents, scorers, suites
- `tasks/<vector>/<task>/` -- one task each: `task.yaml` (the prompt inline), any ground truth
- `tasks/easy/<vector>/` -- parked tasks every model passes. only `pats run -S easy` runs them
- `bin/` -- the steps tasks share (`stage`, `collect`) and the sandbox's `provision`
- `scorers/` -- one uv script per scorer, helpers in `_lib.py`

the rock suites (`rock-crafter`, `rock-debugger`) run in the `rock-lxd`
sandbox: an lxd system container with nesting, provisioned with real rockcraft,
since packing and `rockcraft test` both start lxd instances. locally they need
an lxd server (`lxc` remote); in ci the pats action sets lxd up on the runner
and the `ci-rock-*` suites run a subset of their tasks, as each pair takes
minutes. their steps run with `--rock` (`stage`, `collect`, `provision`); a
debug task's project lives in its `project/`, with spread tasks stored as
`task.spread.yaml` (pats reads any `task.yaml` as a task).
