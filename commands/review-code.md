---
name: review-code
description: Review code for correctness, security, performance, and code quality
---

If a specific file, set of files, or scope was provided when this command was
invoked, review that. Otherwise, fetch the active pull request and review its
diff. If there is no active PR, review the current branch's uncommitted changes
against the default branch.

## Core Review Principles (apply to every review)

Before evaluating how well any piece of code is written, apply these two
questions to everything in the diff:

1. **Does this code serve the change's objective?** For every file, function,
   abstraction, and test introduced, ask whether it's necessary to deliver what
   this change sets out to accomplish. Reasons to flag: it's duplicating
   something that already exists, it's solving a problem outside the stated
   scope, or it adds abstraction that isn't required by any actual caller in
   this change. Recommend removal with a clear reason, the quality or
   cleverness of the code is not a reason to keep it.

2. **Cross-reference contracts at call sites.** For every function, verify that
   its declared parameter types and return type match what callers actually
   pass in and what they actually do with the return value. Read the
   implementation, then read every call site. Do not evaluate a function
   signature or its documentation in isolation.

## Review Process

**This review must be exhaustive and complete in a single pass.** Do not stop
after finding a few issues. Do not defer findings to a future review. Every
issue visible in the current diff must be reported now, findings that appear
only after a follow-up push are a review failure, not a follow-up feature.

If the project has its own coding-standard files (a rules directory, an
instructions directory, linter config with documented conventions), do one full
pass per standard: read it in full, then check every changed file and every
changed function and line against that standard before moving to the next one.
Do not combine passes. Do not skip passes.

After all standards passes, do one final pass for **Correctness**, logic
errors, edge cases, off-by-one (general reasoning, no external standard needed).
Use `COR` as the prefix for this pass.

As you work through each pass, collect all findings into a single table
produced at the end. Do not output per-pass headings or lists, accumulate
silently and output the table once all passes are fully complete.

Each finding gets an ID of the form `<PREFIX><N>` where `<PREFIX>` is a short
uppercase identifier for that pass (derived from the standard's name, or `COR`
for the correctness pass) and `<N>` is a sequential number within that prefix,
starting at 1.

Produce the table in this format:

| ID | File | Issue Summary | Severity | Required Action |
| --- | ---- | ------------- | -------- | --------------- |

Rules for each column:

- **Severity**: High / Medium / Low, High = correctness bug or security; Medium
  = reliability, API contract, or standards violation on new code; Low = style,
  naming, cosmetic
- **Required Action**: The minimal fix, or "No fix, [reason]" if the issue is
  invalid, targets pre-existing code, or is defense-in-depth for an impossible
  scenario

After the table, provide a one-line summary: how many High / Medium / Low
findings, and how many require a fix vs no fix.

## Principles

1. **Review Only New or Modified Code**

   - Do not comment on issues that existed before the current changes (file
     length, missing docs, legacy patterns).
   - Focus feedback on code that was added, changed, or deleted.

2. **No Retroactive Enforcement**

   - Don't flag existing violations unless the change introduces a new issue or
     significantly worsens what's already there.
   - Example: a file already has 400 lines and the change adds 10 more. Don't
     complain about file length. If the change adds 100+ lines, suggest
     splitting only the new code.

3. **Actionable Feedback**

   - Be specific about what changed.
   - Skip generic complaints about the codebase.

4. **Respect Project-Specific Exceptions**

   - If project conventions allow exceptions or best-effort patterns, don't
     enforce stricter rules than the project itself does.

5. **No Blame for Existing Code**
   - Do not attribute responsibility for existing issues to the current author.

## Handling Slight Regressions (Suggestion vs Requirement)

This applies only to pre-existing issues that a change slightly worsens, not to
issues in entirely new code (see above). When a change slightly worsens an
existing issue, favor suggestions over requirements unless the regression is
serious:

- **High**, correctness bugs, security vulnerabilities, data issues: recommend
  fixing before merging and explain why.
- **Medium**, reliability, API contract violations, standards violations on new
  code: recommend a fix or a follow-up plan with justification.
- **Low**, style, naming, cosmetic: note as optional with a suggested
  improvement.

When in doubt, suggest rather than require. Explain why for High findings,
offer examples for suggestions.

## Checklist

- [ ] Every piece of new code considered for whether it should exist, with
      justification when recommending removal
- [ ] Every function's parameter and return types checked against actual call
      sites
- [ ] Feedback is limited to new/changed code
- [ ] No comments on pre-existing issues unless made worse by the change
- [ ] Suggestions are actionable for the current author
- [ ] No blame or requests to fix existing code
- [ ] Project-specific conventions and exceptions are respected
- [ ] Slight regressions handled appropriately (suggestion vs requirement)
- [ ] Security issues always flagged, regardless of existing code state
