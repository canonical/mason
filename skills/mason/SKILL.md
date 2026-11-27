---
name: mason
description: >-
  Entry point for the mason agent kit. Routes a plain-language request to the right mason
  skill, or prints usage when the intent is unclear. Use when user runs /mason (with a request
  or bare), says "mason help", or "what can mason do".
---

# mason

Agent kit for chisel / chisel-releases and rocks work.

`/mason` has no actions of its own -- it either routes or prints usage:

- **route** -- if the request clearly maps to a skill below, load that skill's `SKILL.md`
  from its sibling directory (e.g. `../chisel-slicer/SKILL.md` relative to this file) and
  follow it, passing the request through as plain language. authoring or adding a package slices file ->
  `chisel-slicer`; reviewing one -> `chisel-slice-reviewer`; moving one between release
  branches -> `chisel-slice-porter`; building a rock, writing a `rockcraft.yaml`, or fixing
  a failing `rockcraft pack` or failing rock tests -> `rockcrafter`.
  e.g. `/mason "please help me write a slices file for foobar"` -> `chisel-slicer`, foobar.
- **usage** -- no args, "help", or intent not obviously covered by a skill below: print the
  usage block below verbatim, then stop. Do not load or run anything else -- never guess.

```
mason -- agent kit for chisel / chisel-releases and rocks work

skills:
  /chisel-slicer <pkg>              author + test a slices file (no PR)
  /chisel-slice-reviewer <slices-file>
                                    read-only review of a slices file
  /chisel-slice-porter <pkg> <from> <to>
                                    move a slice between release branches
  /rockcrafter <app>                draft, check, pack + test a rock,
                                    or fix one whose pack or tests fail

usage:
  /chisel-slicer jq
  /chisel-slice-reviewer slices/jq.yaml
  /chisel-slice-porter jq ubuntu-24.04 ubuntu-26.04
  /rockcrafter "build a rock for nginx on ubuntu 24.04"
  or plain language: "write a slice for jq", "review slices/jq.yaml"

docs: https://github.com/canonical/mason
```
