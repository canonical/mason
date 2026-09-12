# mason

Agent guidance for `canonical/mason` agent skill repository. This file gets edited **ONLY** by humans, not by agents. if there are thigns you think ought to be saved to long-term project memory, and if you are working in an interactive session, prompt the user with that suggestion. NEVER make edits yourself.

---

## general

- Eeach capability area is its own skill under `skills/`
- `_shared/` holds everything a skill ships but does not own -- knowledge-base markdown and helper scripts alike. `.shared.yaml` at the repo root declares who gets what: `shared:` -> skill -> source path (relative to `_shared/`) -> `path:`, where the copy lands relative to the skill. `make sync-shared` copied the files so installed skills are self-contained. `make check-shared` (run in ci) fails when one drifts.
- `VERSION` at the repo root is the source of truth for the version; everything else that records one (`.claude-plugin/plugin.json`, `.tessl-plugin/plugin.json`) is a copy and must be synced to it. `tests/meta/test_version_sync.py` fails on drift.
- Agents do not bump versions or make release commits. leave `VERSION` and the manifests at the released number; the maintainer bumps them and tags.
- Skills can be tested locally with [`pats`](https://github.com/lczyk/pats) testing framework. do not run pats tests yourself unless explicitly instructed
- Derive technical requirements from upstream sources and reproducible verified runs.

## skill design

- The skills are to be succinct and provide the needed information without needless repedition
- The SKILL.md contnents ought not to duplicate knowlege from the knowlegebase, and vice-versa.
- For each task make sure to define: what is a successful completion, what can block the task and what part of the task can remain unverified. Distinguish failed checks from unavailable checks. Make sure that these rules are consistent throughout the workflow.
- It should be clear what every helper script does. Each helper script ought to have one distinct purpose, and few (ideally one) concrete ways of running it. The helper scripts ought not to duplicate one another's functionality.

