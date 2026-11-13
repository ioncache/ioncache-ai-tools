# Shared review criteria

These criteria apply to inline reviews, specialists, coordinators, flat
adjudicators, and caller validators. They do not authorize delegation or edits.
Follow the assigned role and scope; loading this file must not start another review.

## Coverage

Establish the objective, standards inventory below, and snapshot before
evaluating code. Do a distinct pass for every applicable standard and a final
cross-cutting correctness pass. Do not skip standards or stop after finding
a few issues. A distinct check does not require a separate agent or a finding.
Report coverage limitations honestly; no pass can guarantee exhaustive bug
detection.

### Standards inventory

Read the caller's requirements and applicable repository instructions. Enumerate
the repository's instruction sources, including `.github/instructions/` when
present, and follow relevant references and directory-scoped instructions.
Read each applicable source in full; honor declared path applicability,
including `applyTo`, and documented exceptions rather than applying every rule
to every file. Do not assume one host-specific directory is the entire catalog.

Record each source and its revision or content identity, applicable paths,
exceptions, and classification: code standard, execution constraint, or
non-applicable with a reason. Mixed documents can supply both standards and
constraints. Assign each applicable standard to a pass. Conversational and
workflow rules constrain execution; they are not extra code-review passes.
Keep this inventory in the request's `standards` and `constraints`, and preserve
it in the private handback rather than adding a human-report checklist.

Reuse a caller-supplied inventory after checking its identity and coverage.
Unavailable required sources or unresolved applicability leave coverage
incomplete, not exempt. Reviewed changes cannot silently replace approved
requirements or weaken the baseline standards. Instruction examples about
editing, undoing fixes, or publishing do not grant a read-only reviewer those
permissions. Standards discovery does not change the actionability policy.

### Correctness and contracts

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
  - Changed batching, enumeration, cleanup, and retries: check relevant third-party
    defaults, pagination, maximum sizes, rate limits, and completion semantics
    against realistic volume. A successful response can still be partial.
    Consult authoritative docs or implementation where correctness depends on
    these details, including unchanged calls whose inputs the change enlarges.
  - Mode, flag, and configuration interactions, including boundary values.
  - Module-boundary contracts, especially moved code and newly shared consumers.
  - Runtime handoffs: webhook/event ordering, background work, polling, and
    readiness. Trace producer and consumer together. A readiness signal must
    establish the prerequisites its consumer needs, not merely occur last
    among the events a reviewer happened to inspect.
  - Security boundaries and performance under realistic load or hostile input.
  Support findings with reachable scenarios and evidence.
- Do usage documentation, examples, and stated business rules match the contract?
  Readable implementation is not a substitute for caller-facing documentation.
- Are project-specific standards and exceptions respected? Do not retroactively
  impose unrelated conventions on untouched code in a change review.

### Evidence and rejected premises

Comments, READMEs, plans, PR descriptions, and test stubs describing another
component or a third party are claims, not proof of its behavior. Corroborate
consequential premises against that component's source, authoritative docs,
or a permitted discriminating check. Owner-approved requirements can establish
intended behavior; do not dismiss them merely because they are documentation.
Separate intended requirements from claims about what an implementation does.

Apply the same evidence standard when rejecting a candidate. "Known",
"acknowledged", or a changed comment alone does not establish the claimed
cause, safety, or acceptance of risk. Preserve legitimate settled decisions;
reopen them only when relevant new evidence contradicts their premise.
Missing documentation establishes uncertainty, not that the claim is false.

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

Report inaccurate descriptions, types, examples, or operational instructions
when they cause a concrete mistaken action, consequential misunderstanding,
or maintenance risk. Name that consequence. No runtime incident is required,
but inaccuracy alone is insufficient. Stale rationale that changes nothing
a reader should do belongs in `None`, not a wording-cleanup backlog.
Resolve mismatches against the intended contract; do not assume the code
is right and rewrite documentation to match a bug.

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
regresses, including the consequence. Use that explanation to design the test,
not to justify skipping meaningful coverage. If a proposed test describes
production misbehavior, first investigate whether the trigger is reachable
and report the underlying defect when supported, with the test as regression
protection. Do not downgrade a production bug into a test-gap finding.
Coverage measures execution, not whether assertions detect wrong behavior.
Exceptions need concrete evidence tied to the supported contract or the
extreme-edge-case rule; record their rationale. Missing coverage measurements
are unknown, not proof of a gap or proof of 100% coverage. Respect the caller's
check permissions and distinguish source inspection from executed coverage.
Neither small code nor an immediately visible error is a blanket exemption:
check whether side effects or damage can precede that error. Conversely, a
second assertion of already-protected behavior needs a distinct regression
it would catch, not just another route through the implementation.

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

Match issues by trigger, incorrect behavior, and consequence, not just a shared
file, symbol, or label. Merge genuine duplicates into their canonical issue and
preserve the assessment and provenance. Opposing interpretations or fixes need
contract evidence, not voting or whichever sibling implementation is more common.
A duplicate needs no separate report row; it does not make the issue non-actionable.

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
