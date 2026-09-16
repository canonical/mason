# Verification and completion

Include every dependency package added or changed in verification. Keep check
status separate from finding severity.

- **Passed:** the check ran and met its acceptance criteria. Static checks do
  not prove installability or runtime behaviour.
- **Failed:** evidence shows a defect: SDF blocks, unjustified warnings, missing
  or malformed tests, unfinished scaffolds, inadequate assertions, unresolved
  source conflicts, or a cut/spread failure caused by the proposed change.
  Report the defect and fix it when changes are in scope.
- **Unavailable:** the check could not establish a result because a tool,
  backend, input, archive or documentation endpoint was inaccessible, or a
  checker crashed. Record the cause, affected scope and command or source needed
  to complete verification. A denied fetch is not evidence of package absence.

Network access is required. Report network failures and access refusals as unavailable;
do not work around them with offline fallbacks, cached upstream substitutes or
test-specific behaviour. Do not turn an observed product failure into an
unavailable check. Inspect diagnostics when a cut or spread command fails:
non-zero exit alone does not distinguish a defect from an inaccessible service.

## What blocks work

Stop the affected work when the checkout or target is unknown, maintenance
cannot be established for a write, required package contents or dependency
providers cannot be inspected, or a required dependency cycle remains unresolved.
Do not invent missing evidence. Independent checks may still proceed.

Missing runtime tools/backends or unreachable documentation can leave checks
pending after the files are written and statically checked. They never excuse
omitting tests. Incomplete release discovery leaves forward-port coverage
unverified; it does not establish that a release is EOL or that no ports remain.

## Completion and reports

- **Change complete:** all intended SDFs and tests are written,
  coverage reviewed, and applicable checks passed with no unresolved defects.
- **Ready for remaining verification:** the files and available checks are
  finished, but only permitted unavailable checks remain. Name them explicitly;
  do not claim full completion or a passing runtime test.
- **Blocked:** a defect cannot be fixed in scope, or missing evidence prevents
  safe changes. State the unresolved requirement.
- **Review verdict:** request changes for demonstrated blocking or should-fix
  defects; otherwise use incomplete when required evidence is unavailable, or
  approve when the review is complete. A request-changes report must still list
  unavailable checks. Assess the whole task before choosing the verdict.

For each applicable check, record passed/failed/unavailable, evidence, release
and architecture where relevant. Include justified warnings, representative
coverage choices, verification gaps and remaining forward ports. Existing CI
results count only when they cover the reviewed revision and relevant scope;
future CI is not evidence of success.
