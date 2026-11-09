skill behaviour tests using [`pats`](https://github.com/lczyk/pats) 1.x

```
go install github.com/lczyk/pats/cmd/pats@v1.0.0-beta.9
pats init     # builds and pins the sandbox image
pats run
pats score
```

- `pats.yaml` -- sandboxes, agents, scorers, suites
- `tasks/<vector>/<task>/` -- one task each: `task.yaml` (the prompt inline), any ground truth
- `bin/` -- the steps tasks share (`stage`, `collect`) and the sandbox's `provision`
- `scorers/` -- one uv script per scorer, helpers in `_lib.py`
