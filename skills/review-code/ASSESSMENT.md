# Assessing supplied claims

Adjudicators and workflows assessing existing findings read all three policies:

- Evidence, actionability and judgment: [assessment/COMMON.md](assessment/COMMON.md).
- Documentation materiality: [assessment/DOCUMENTATION.md](assessment/DOCUMENTATION.md).
- Meaningful test gaps: [assessment/TESTS.md](assessment/TESTS.md).

This is assessment of supplied claims, not a discovery checklist.
Category workers receive only COMMON plus the assessment modules named in
their category entry. No actor may silently weaken those policies.

## Assignment compliance

This check applies when assessing coverage from category-worker assignments.
It does not require frozen packets for human PR comments or other supplied
claims that did not originate in this workflow.

Assess coverage separately from the truth of a finding. Read each original
report against its frozen packet, including applicability and the single assigned
purpose. Those packets describe the workers' contracts; they are not additional
discovery instructions for the adjudicator. Matching category labels and valid
bug reports do not establish that the assigned review was performed.

Validate technical language decisions against their source evidence, including
any omitted language-specific category. Unknown languages or absent dedicated
guides cannot justify a no-language decision. Preserve general documentation,
unit-test quality and other stack-adaptive purposes. A native-framework unit-test
review is not out of purpose merely because it is not Vitest; JSDoc-specific
rules do not apply to TypeScript or other non-JavaScript code.

Incorrect frozen language facts require a corrected, counted phase under
PACKETS.md, not relabeled old coverage. Newly classified files may extend the
same phase's inventory without changing its earlier facts or spending.

A worker that uses an assessment policy to perform another category's review,
or continues generic discovery after finding its own category inapplicable, has
not completed its assignment. Identify the affected attempt and report incomplete
coverage even when its observations describe real defects. Preserve and assess
those observations without relabeling them as successful coverage for any category.
The same defect can legitimately appear in several categories when each worker
reaches it through its own applicable requirements; duplication alone is not a
scope breach.

Return the compliance decision and evidence to the caller. The caller removes
rejected attempts from the active map, without rewriting their original reports,
and schedules fresh same-category replacements within the existing allowance.
Exhaustion remains incomplete. Adjudicator source inspection and another
category's findings cannot replace the missing independent assignment.

## Human report

Report only `Act`, `Decide`, and `Investigate` items, in priority order. Keep
supported corrections distinct from decisions and investigations:

| ID | File | Issue Summary | Severity | Basis | Action | Next Step |
| --- | --- | --- | --- | --- | --- | --- |

Use a short standard prefix plus a number, or `COR<N>` for correctness.
Explain the simplest coherent correction, decision, or check. Show `observed`
or `inferred` as defined in CONTRACTS.md and label unresolved claims explicitly.
Group findings sharing a correction without losing their IDs or differences
in action, severity, or basis.

Apply the caller's `main_min_severity` (default Low) after actionability
assessment, to this table only. Count otherwise-reportable below-threshold
items separately. That display preference does not discard evidence, accept
risk, or change which corrections a calling loop should make.

Keep rejected, duplicate, style-only, and low-value observations in the private
handback or ledger, with a count only in the report. Do not add a second table,
collapsed cleanup backlog, or unsolicited location list for them.

Provide evidence with each finding: behavior, triggering conditions,
requirement, and affected callers or documentation. Preserve underlying-issue
keys, duplicate/recurrence references, and coverage in the
[CONTRACTS.md](CONTRACTS.md) handback. Do not silently drop ignored findings
whose rationale is contradicted by new evidence.

Finish with reportable counts by severity and action, separate counts of
non-reportable and below-threshold candidates, scope and snapshot, execution
mode and strategy, model-selection limitations, and incomplete coverage or
failed passes. Count underlying issues, not grouped rows or duplicate sightings.
An empty table means no reportable items at that threshold, not proof of no
defects. Do not claim a clean review while required coverage is incomplete or
consequential uncertainty remains. Do not add approval, merge, or posting actions.
