# mason

- each capability area is its own skill under `skills/`
- `_shared/` holds everything a skill ships but does not own -- knowledge-base markdown and helper scripts alike.
    - `.shared.yaml` at the repo root declares who gets what: `shared:` -> skill -> source path (relative to `_shared/`) -> `path:`, where the copy lands relative to the skill. `make sync-shared` copied the files so installed skills are self-contained. `make check-shared` (run in ci) fails when one drifts.
- `VERSION` at the repo root is the source of truth for the version; everything else that records one (`.claude-plugin/plugin.json`, `.tessl-plugin/plugin.json`) is a copy and must be synced to it. `tests/meta/test_version_sync.py` fails on drift.
- agents do not bump versions or make release commits. leave `VERSION` and the manifests at the released number; the maintainer bumps them and tags.
