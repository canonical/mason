---
name: mason
description: >-
  Entry point for the mason agent kit. Routes a plain-language request to the right mason
  skill, or prints usage when the intent is unclear. Use when user runs /mason (with a request
  or bare), says "mason help", or "what can mason do".
argument-hint: "[request]  (no args -- prints usage)"
---

# mason

Agent kit for chisel / chisel-releases work.

`/mason` has no actions of its own -- it either routes or prints usage:

- **route** -- if the request clearly maps to a skill below, load that skill's `SKILL.md`
  from its sibling directory (e.g. `../chisel-slicer/SKILL.md` relative to this file) and
  follow it, passing the request through as plain language. authoring or adding an SDF ->
  `chisel-slicer`; reviewing one -> `chisel-slice-reviewer`; moving one between release
  branches -> `chisel-slice-porter`.
  e.g. `/mason "please help me write an sdf for foobar"` -> `chisel-slicer`, foobar.
- **usage** -- no args, "help", or intent not obviously covered by a skill below: print the
  usage block below verbatim, then stop. Do not load or run anything else -- never guess.

```
mason -- agent kit for chisel / chisel-releases work

skills:
  /chisel-slicer <pkg>              author + test + commit an SDF (no PR)
  /chisel-slice-reviewer <sdf>      read-only review of an SDF
  /chisel-slice-porter <pkg> <from> <to>
                                    move a slice between release branches

usage:
  /chisel-slicer curl
  /chisel-slice-reviewer slices/curl.yaml
  /chisel-slice-porter curl ubuntu-24.04 ubuntu-26.04
  or plain language: "write a slice for curl", "review slices/curl.yaml"

docs: https://github.com/canonical/mason
```
