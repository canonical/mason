# agents.md

- This file represents long-term project memory.
- This file gets edited ONLY by humans, NEVER by agents.
- If there are observations or rules you think ought to be saved to long-term project memory, and if you are working in an interactive session, you MAY prompt the user with that suggestion. NEVER make edits yourself.

---

## general

- Each capability area is its own skill under `skills/`
- `_shared/` holds everything a skill ships but does not own -- knowledge-base markdown and helper scripts alike. `.shared.yaml` at the repo root declares who gets what: `shared:` -> skill -> source path (relative to `_shared/`) -> `path:`, where the copy lands relative to the skill. `make sync-shared` copied the files so installed skills are self-contained. `make check-shared` (run in ci) fails when one drifts.
- `VERSION` at the repo root is the source of truth for the version; everything else that records one (`.claude-plugin/plugin.json`, `.tessl-plugin/plugin.json`) is a copy and must be synced to it. `tests/meta/test_version_sync.py` fails on drift.
- Agents do not bump versions or make release commits. leave `VERSION` and the manifests at the released number; the maintainer bumps them and tags.
- Skills can be tested locally with [`pats`](https://github.com/lczyk/pats) testing framework. do not run pats tests yourself unless explicitly instructed
- Derive technical requirements from upstream sources and reproducible verified runs.
- In pats skills tests, the agents under test work through an egress proxy in order to prevent the agents under test from cheating.

## skill design

- The skills are to be succinct and provide the needed information without needless repetition.
- The SKILL.md contents ought not to duplicate knowledge from the knowledgebase, and vice-versa.
- For each task make sure to define: what is a successful completion, what can block the task and what part of the task can remain unverified. Distinguish failed checks from unavailable checks. Make sure that these rules are consistent throughout the workflow.
- It should be clear what every helper script does. Each helper script ought to have one distinct purpose, and few (ideally one) concrete ways of running it. The helper scripts ought not to duplicate one another's functionality.
- Skills are explicitly designed to work online. Offline work is out of scope. Skills may assume network access to the Ubuntu archive, GitHub and upstream documentation. An unreachable network is an unavailable check to report, not something to work around: do not write offline fallbacks or bundle copies of upstream material for offline use.
- The skills should not make special accommodations for tests and should instead be able to natively deal with the access refusal.
- Markdown guidance should instruct agents when to use helper scripts, not describe their implementation or repeat their
  output contracts. Scripts should make their purpose and results clear through their names, usage help and output. Agents can read the scripts when more detail is needed.
- Shared markdown must not specify which skills use it. Their inclusion is defined via `.shared.yaml`. Describe the subject and task rules, not the consuming skills.
