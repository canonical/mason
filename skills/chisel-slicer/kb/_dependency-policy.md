# Runtime dependency evidence

Use the [official slicing guide](https://ubuntu.com/chisel/docs/latest/how-to/slice-a-package/)
for package inspection and the [Debian relationship definitions](https://www.debian.org/doc/debian-policy/ch-relationships.html)
for dependency field semantics. Package dependencies are discovery input; a
slice's dependencies must supply the selected functionality.

- Start with `Depends:` and `Pre-Depends:`. Retain runtime needs, including
  interpreters, configuration, data and dynamically loaded plugins. Do not copy
  every package dependency or automatically include `Recommends:` / `Suggests:`;
  include one only when the selected functionality demonstrably needs it.
- Inspect maintainer scripts and relevant source. Chisel does not execute
  maintainer scripts. Reproduce required generated files, alternatives and other
  runtime effects through contents or mutation; omit installation-only tools
  when their effects are unnecessary or implemented another way.
- Resolve shared libraries for the target release and architecture. Host
  library resolution is not evidence for a different target. Verify that the
  retained `essential:` graph supplies every required provider, including
  transitive shared libraries and runtime lookups absent from linker output.
- Match dependencies to actual slice contents, including siblings in the same
  package. An existing SDF alone does not establish that the needed files ship.
- Resolve alternatives and virtual packages through target provider metadata,
  respecting version and architecture constraints. Use host apt metadata only
  when its suites, components and architecture match the target manifest.
- Inspect each required unsliced package before expanding its dependencies.
  Track visited packages and edges; discard cycle edges only with evidence
  that they are outside the selected runtime functionality.

Record the retained graph, existing slices reused, new slices required and
significant exclusions with reasons. Verify the graph with independent cuts and
functional tests under `kb/_spread-tests.md`; static references alone do not
establish a working dependency closure.

For package inspection, run `_deb-list.py` from the target checkout for each
required architecture. For Pro or custom archives, use an already authorised
archive setup. Do not infer absence from private archives using public archive
evidence; apply `kb/_verification.md` when inspection cannot complete.
