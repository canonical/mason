# mason

- each capability area is its own skill under `skills/`
- a skill that needs something from `_shared/` lists it in its `shared.list`; `make sync-shared` copies it into `<skill>/shared/` (with a "generated" banner) and the copy is committed, so installed skills are self-contained. `make check-shared` (run in ci) fails when a copy drifts from its source.
