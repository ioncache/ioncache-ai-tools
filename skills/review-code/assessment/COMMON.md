# Shared evidence and assessment

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

Apply this policy when selecting findings and corrections, not just when
formatting the report. A valid observation on new code is not automatically
a required fix. Distinguish validity, scope, severity, confidence, priority,
and action. A real issue is not invalid because it is pre-existing,
inconvenient, or expensive to fix. Do not invent requirements.
Explain the affected behavior, contract, or concrete maintenance consequence.
A stylistic preference or metric violation alone is not a substantive issue.

## Extreme edge cases

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

## Judgment and next action

Assess severity by consequence, reachability, breadth, and recoverability:
High for serious impact, Medium for material but bounded impact, and Low for
limited impact. Issue category alone does not set severity. A user-visible bug,
documentation error, or test gap need not be High to warrant correction.
Keep confidence in the evidence separate from potential harm and explain
priority as when action is warranted and why.

Select one `report_action`:

- `Act`: a supported, relevant issue with a worthwhile correction under the
  applicable assessment policy.
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
