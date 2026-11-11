# Shared review criteria

These criteria apply to inline reviews, specialists, coordinators, and flat
adjudicators. They do not authorize delegation or edits. Follow the assigned
role and scope; loading this file must not start another review.

## Coverage

Establish the objective, applicable project standards, existing exceptions,
and snapshot before evaluating code. Do a distinct pass for every applicable
standard and a final cross-cutting correctness pass. Do not skip standards
or stop after finding a few issues. A distinct check does not require a separate
agent or a finding. Report coverage limitations honestly; no pass can guarantee
exhaustive bug detection.

For non-trivial design or contract decisions, apply
[engineering judgment](../engineering-judgment/SKILL.md) within the assigned
read-only scope. Coordinators must pass relevant ownership and compatibility
constraints to reviewers explicitly; do not assume they inherit this guidance.

- Does each new file, abstraction, function, and test serve the objective?
  Evaluate duplication, unrelated behavior, and unjustified abstraction against
  their actual consequences, not a preference for another implementation.
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

## Actionability

Apply this policy when selecting findings and corrections, not just when
formatting the report. A valid observation on new code is not automatically
a required fix. Distinguish validity, scope, severity, confidence, priority,
and action. A real issue is not invalid because it is pre-existing,
inconvenient, or expensive to fix. Do not invent requirements.

### Substantive issues and documentation

Recommend corrections for supported defects, inaccurate documentation, and
missing test coverage under the criteria below. Explain the affected behavior,
contract, or concrete maintenance consequence. A stylistic preference or
metric violation alone is not a substantive issue.

Incorrect behavior descriptions, parameter or return types, examples, and
operational instructions should be fixed. No runtime failure is required.
Resolve mismatches against the intended contract; do not assume the code is
right and rewrite documentation to match a bug.

Accurate documentation that differs only in style or shape is not an actionable
finding. For example, an accurate inline JSDoc object type instead of a named
typedef violates a presentation convention, not the documented contract.
Being new code or violating a documented style rule does not change that.

### Extreme edge cases

Exclude extreme, speculative edge cases requiring contrived inputs,
unsupported usage, or a chain of unestablished assumptions. Exceptions are
performance, security, privacy, and correctness issues with a credible
triggering path and meaningful impact. Merely applying one of those labels
does not qualify an observation.

Name the caller, boundary, or operating condition and support the trigger and
consequence with evidence. Evidence-backed source reasoning is sufficient;
do not require an observed incident. Ordinary dependency failures and supported
error paths are not extreme edge cases. A rare but credible serious failure
must not disappear behind an "edge case" label.

### Test gaps

Missing coverage of new or changed code is actionable by default. Aim for
100% coverage with meaningful assertions covering supported behavior, including
branches and failure paths. Do not decide a test is unnecessary merely because
the implementation looks simple or the path seems less important.

Identify the uncovered behavior and what an assertion must detect if it
regresses. Use that explanation to design the test, not to justify skipping it.
Coverage measures execution, not whether assertions detect wrong behavior.
Exceptions need concrete evidence tied to the supported contract or the
extreme-edge-case rule; record their rationale. Missing coverage measurements
are unknown, not proof of a gap or proof of 100% coverage. Respect the caller's
check permissions and distinguish source inspection from executed coverage.

### Judgment and next action

Assess severity by consequence, reachability, breadth, and recoverability:
High for serious impact, Medium for material but bounded impact, and Low for
limited impact. Issue category alone does not set severity. A user-visible bug,
documentation error, or test gap need not be High to warrant correction.
Keep confidence in the evidence separate from potential harm and explain
priority as when action is warranted and why.

Select one `report_action`:

- `Act`: a supported, relevant issue with a worthwhile correction, including
  inaccurate documentation and missing test coverage as defined above.
- `Decide`: an unresolved choice that materially affects correctness, risk,
  or a significant design commitment. State the decision and what depends on it.
- `Investigate`: a credible consequential uncertainty with a specific useful
  check. Investigate within the pass's permissions and budget where possible;
  otherwise identify the missing evidence and what it affects.
- `None`: no warranted action, including refuted claims, style-only deviations,
  and evidence-backed low-value observations.

Merge duplicate observations into their canonical issue and preserve its
assessment. A duplicate needs no separate report row; it does not make the
underlying issue non-actionable.

Do not turn uncertainty into a confirmed defect, automatic fix, or silent
acceptance. A failed required check remains a coverage limitation; hiding its
candidate does not complete the review. Do not impose finding quotas, inflate
severity to retain a finding, or suppress consequential uncertainty to improve
the apparent ratio of accepted findings.

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
