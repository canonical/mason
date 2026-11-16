You grade a code review of a chisel package slices file (canonical/chisel-releases, Ubuntu 26.04). Your working directory holds:

- `review.md` -- the review under test: the reviewer's final message.
- `reviewed.yaml` -- the slices file it reviewed.
- `key.yaml` -- the defects seeded into an otherwise upstream file (`defects`, each with `what` and `severity`), and the expected verdict. An empty `defects` list means the file is the upstream file, unchanged.

Grade two things.

1. Recall. For each seeded defect: did the review identify it -- the right slice / path / dependency, and a diagnosis that is correct in substance (not merely mentioning the name)? Credit 1 for a correct finding, 0.5 for a finding that points at the right place with a vague or partly wrong diagnosis, 0 otherwise. Severity labels don't need to match exactly.

2. Precision. List every other finding the review raises as blocking or should-fix (ignore nits, unavailable-check notes and process remarks). For each, decide: valid (demonstrably true from the file, the Ubuntu package or chisel's documented conventions, including knock-on effects of a seeded defect), unverifiable (plausible, you can't settle it), or invalid (wrong). The seeded list is not exhaustive: the upstream file may have real issues, and those count as valid. You may use the network to check package facts or chisel docs, but don't spend long on it.

Score:
- with seeded defects: recall_mean x (1 - 0.25 x invalid_count), floored at 0.
- with none (control): 1 - 0.25 x invalid_count, floored at 0.
Unverifiable findings cost nothing.

Before the score line, write a short table: each seeded defect with its credit, then each other finding with valid / unverifiable / invalid and one line of reason.
