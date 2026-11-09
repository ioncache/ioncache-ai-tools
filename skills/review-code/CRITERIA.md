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

For non-trivial design or contract decisions, apply
[engineering judgment](../engineering-judgment/SKILL.md) within the assigned
read-only scope. Coordinators must pass relevant ownership and compatibility
constraints to reviewers explicitly; do not assume they inherit this guidance.

- Does each new file, abstraction, function, and test serve the objective?
  Flag unnecessary duplication, unrelated behavior, and unjustified abstraction.
- Does the solution keep responsibilities and shared rules coherent across
  affected packages or services? Do not prefer a smaller patch that shifts work
  to the wrong owner or leaves consumers inconsistent.
- Do parameter, return, error, and side-effect contracts match actual callers?
  Trace affected call sites rather than judging signatures in isolation.
- Every correctness pass works through these angles, recording non-applicability
  rather than silently skipping one:
  - Swallowed errors and silenced signals: filters, catches, fallbacks, and noise
    lists that hide failures from a caller or observer.
  - Races against cached or asynchronous state, including stale reads.
  - Cleanup and teardown that stop at the first failure or leave partial state.
  - Mode, flag, and configuration interactions, including boundary values.
  - Module-boundary contracts, especially moved code and newly shared consumers.
  - Security boundaries and performance under realistic load or hostile input.
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

Lead with correctness, security, and contract findings:

| ID | File | Issue Summary | Severity | Basis | Required Action |
| --- | --- | --- | --- | --- | --- |

Use a short standard prefix plus a number, or `COR<N>` for correctness.
Severity is High (correctness/security), Medium (reliability/contracts/
standards), or Low (style/cosmetic). Explain the simplest coherent correction or
specific no-fix reason without conflating invalidity and scope.
Show `observed` or `inferred` beside severity as defined in CONTRACTS.md.
Honor the caller's `main_min_severity` (default Low) for this table only.
Count below-threshold findings separately; the threshold never discards
candidates or changes validation, severity, or a calling loop's fix policy.

Put standards, documentation, and style findings in a second table grouped by
rule. For example, use "35 functions lack @example" with collapsed locations
instead of 35 main-table rows. Keep candidate IDs, severity, basis, and action
within each group; split groups when severity, basis, or action differs. Use
collapsible details or a linked private result file for the full location list.
Classify by the actual consequence: a misleading documented contract belongs
in the main table when it causes a concrete correctness or caller-contract failure.

Provide evidence with each finding: behavior, triggering conditions,
requirement, and affected callers or documentation. Preserve underlying-issue
keys, duplicate/recurrence references, and coverage in the
[CONTRACTS.md](CONTRACTS.md) handback. Do not silently drop ignored findings
whose rationale is contradicted by new evidence.

Finish with candidate counts, not grouped-row counts, by severity and required
action, scope and snapshot, execution mode and strategy, model-selection
limitations, and incomplete coverage or failed passes.
An empty main table is not a clean review when findings were filtered out.
An empty findings list is not a clean review unless required coverage
completed. Do not add approval, merge, or posting actions.
