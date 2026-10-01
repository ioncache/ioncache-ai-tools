---
name: review-code
description: Reviews code for correctness, security, performance, and project standards using independent review passes. Use when asked to review files, a branch, a pull request, or a repository; reports findings without applying fixes.
---

# Read-only code review

Do not edit code, apply fixes, commit, push, or post review comments. Return
findings to the caller. A coordinating review-and-fix workflow may act on
them separately; this skill itself remains read-only.

## Scope

Honor an explicit scope, local snapshot, and comparison base supplied by
the caller. Otherwise inspect the active PR and review its change; without
a PR, review branch changes plus local staged/unstaged changes against the
default branch's merge-base. State the baseline and relevant untracked files.
Do not treat a failed lookup as an empty review.

For a local review loop, inspect the current working tree and pinned base,
not a remote PR diff that omits fixes. For focused review-fixes, inspect the
supplied correction delta and affected callers, then reconcile all outstanding
findings. Reading callers does not grant permission to expand the fix scope.

Repository/file reviews can include pre-existing issues within the requested
scope. In change reviews, prioritize introduced or worsened issues. Flag
discovered pre-existing security risks separately without attributing them
to the change. Out-of-scope does not mean invalid.

## Review method

Establish the objective, applicable project standards, existing exceptions,
and snapshot before evaluating code. Do a distinct pass for every applicable
standard and a final cross-cutting correctness pass. Do not skip standards
or stop after finding a few issues. Report coverage limitations honestly;
no pass can guarantee exhaustive bug detection.

Use independent read-only subagents for substantial independent standards
passes. Give each the same objective, snapshot, relevant standards, scope,
and required evidence format. Keep a continuous call-chain investigation
together rather than splitting it between agents. Small checks can remain
with the coordinator. Respect configured model/effort defaults.

If a caller already coordinates workers, follow the assigned pass without
spawning another layer. Return findings and coverage to that coordinator.
Do not assume identical delegation tools across hosts. If required agents
are unavailable, disclose the limitation rather than claiming delegation.

Collect all required results before reporting. A failed or partial worker
does not count as a clean pass. The coordinator reconciles duplicates and
performs the integration-level correctness review across specialist boundaries.
Check that the reviewed code did not change while workers were reading it.

## Criteria

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

Distinguish a finding's truth, scope, severity, and proposed action. A real
issue is not invalid because it is pre-existing, inconvenient, or expensive
to fix. Treat slight low-risk worsening as a suggestion; explain why serious
correctness, security, or data regressions need correction.

## Output

Return one consolidated table:

| ID | File | Issue Summary | Severity | Required Action |
| --- | --- | --- | --- | --- |

Use a short standard prefix plus a number, or `COR<N>` for correctness.
Severity is High (correctness/security), Medium (reliability/contracts/
standards), or Low (style/cosmetic). Explain the minimal correction or
specific no-fix reason without conflating invalidity and scope.

Provide evidence with each finding: behavior, triggering conditions,
requirement, and affected callers or documentation. For a loop coordinator,
also return a stable underlying-issue key, duplicate/recurrence references,
and coverage per pass. Do not silently drop ignored findings whose rationale
is contradicted by new evidence.

Finish with counts by severity and required action, plus incomplete coverage
or failed passes. Do not claim a clean review when required work is missing.
