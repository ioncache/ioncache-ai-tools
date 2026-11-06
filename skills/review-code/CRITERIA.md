# Shared review criteria

These criteria apply to inline reviews, specialists, coordinators, and flat
adjudicators. They do not authorize delegation or edits. Follow the assigned
role and scope; loading this file must not start another review.

## Coverage

Establish the objective, applicable project standards, existing exceptions,
and snapshot before evaluating code. Do a distinct pass for every applicable
standard and a final cross-cutting correctness pass. Do not skip standards
or stop after finding a few issues. Report coverage limitations honestly;
no pass can guarantee exhaustive bug detection.

- Does each new file, abstraction, function, and test serve the objective?
  Flag unnecessary duplication, unrelated behavior, and unjustified abstraction.
- Do parameter, return, error, and side-effect contracts match actual callers?
  Trace affected call sites rather than judging signatures in isolation.
- Are correctness, security, performance, edge cases, and failure behavior sound?
  Support findings with reachable scenarios and evidence.
- Do usage documentation, examples, and stated business rules match the contract?
  Readable implementation is not a substitute for caller-facing documentation.
- Are project-specific standards and exceptions respected? Do not retroactively
  impose unrelated conventions on untouched code in a change review.

Distinguish truth, scope, severity, confidence, and action. A real issue is not
invalid because it is pre-existing, inconvenient, or expensive to fix. Treat
slight low-risk worsening as a suggestion; explain why serious correctness,
security, or data regressions need correction. Do not invent requirements or
present cosmetic suggestions as correctness defects.

## Human report

The invoking agent or coordinator returns one consolidated table:

| ID | File | Issue Summary | Severity | Required Action |
| --- | --- | --- | --- | --- |

Use a short standard prefix plus a number, or `COR<N>` for correctness.
Severity is High (correctness/security), Medium (reliability/contracts/
standards), or Low (style/cosmetic). Explain the minimal correction or
specific no-fix reason without conflating invalidity and scope.

Provide evidence with each finding: behavior, triggering conditions,
requirement, and affected callers or documentation. Preserve underlying-issue
keys, duplicate/recurrence references, and coverage in the
[CONTRACTS.md](CONTRACTS.md) handback. Do not silently drop ignored findings
whose rationale is contradicted by new evidence.

Finish with counts by severity and required action, scope and snapshot,
execution mode, model-selection limitations, and incomplete coverage or failed
passes. An empty findings list is not a clean review unless required coverage
completed. Do not add approval, merge, or posting actions.
