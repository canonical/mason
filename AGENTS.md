# mason

- each capability area is its own skill under `skills/`
- what each skill takes from `_shared/` is declared in `.shared.yaml` at the repo root: `shared:` -> skill -> source path (relative to `_shared/`) -> `path:`, where the copy lands relative to the skill. omit the entry body to keep the source's own relative path. `make sync-shared` writes the copies -- byte-for-byte, nothing added, and no listing file beside them, so a skill dir holds only what ships -- and they are committed, so installed skills are self-contained. `make check-shared` (run in ci) fails when a copy drifts. being an exact duplicate is also how a copy is recognised: an undeclared one is a leftover and gets swept, so dropping or retargeting an entry moves the file rather than orphaning it.
