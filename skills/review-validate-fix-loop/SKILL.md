---
name: review-validate-fix-loop
description: Autonomously reviews, validates, fixes, and re-reviews code within finite nested loops, preserving decisions in a per-run ledger. Use when explicitly asked to run a bounded review-and-fix loop or resume one, not for a read-only review.
argument-hint: "[target] [--help] [--max-loops N] [--max-fix-cycles N] [--lead-model MODEL] [--reviewer-model MODEL]"
---

# Review, validate, fix

Run Phase 1 of the [workflow](WORKFLOW.md). Read the
[ledger protocol](LEDGER.md) before starting. The helper records evidence and
enforces bookkeeping; it does not review code, prove judgments, or grant permissions.

## Invocation

Accept a target plus `--max-loops N` and `--max-fix-cycles N` (both default
to 3), or `--resume .review-loop/<run-id>/REVIEW_LEDGER.json`.
Examples: `review-validate-fix-loop branch --max-loops 4`,
`review-validate-fix-loop repository --max-fix-cycles 2`.
Also accept the shared role model, effort, selection, fallback, strategy, and
help options in [../review-code/OPTIONS.md](../review-code/OPTIONS.md).
Normalize them with the shared options helper before target discovery or ledger
creation. Bare invocation uses defaults without a configuration prompt;
`--help` returns without starting a run. Report invalid arguments rather than
ignoring them. There is no `--non-interactive`, cost, parent-model, fixing-model,
or persistent-config flag. The main-table severity floor remains a conversational
preference. Explicit role choices still obey host restrictions.

Resolve `../../scripts/review_ledger.py` relative to this installed skill,
not the current working directory or an assumed host environment variable.
Run its absolute, shell-quoted path using Python 3.11+ from the consuming
Git worktree. Read its `--help` if invocation details are unclear.

## Coordination

1. Normalize options, then resolve the target, objective, and comparison base using the workflow.
   Initialize one ledger, or inspect the explicitly selected resumed run.
2. Record `start_review` before any full-review launch, then invoke
   `review-code` with the pinned request and ledger snapshot. In nested mode
   the review coordinator owns specialist launches. In flat mode the loop
   launches and collects workers, then delegates adjudication. The loop owns
   the request, all ledger writes, and limits in both modes.
   Pass through normalized review options, the resolved `specialists` or
   `sweep-first` strategy, and main table severity floor. Preserve option
   provenance in existing ledger reason/evidence fields. Allocate private result files outside the reviewed
   tree; workers write reports, never the loop ledger. A sweep is part of the
   counted review, not a free preliminary round.
3. Check the evidence handback, adopting independent coordinator validation
   of specialist findings rather than repeating every investigation. Validate
   coordinator-originated findings under the shared caller-validation role;
   a scripted owner schedules independent reasoning rather than judging evidence
   mechanically. Record each candidate, duplicate observation, decision, reason,
   and evidence through the protocol.
   Apply the shared actionability policy, not just the report's severity floor.
4. Declare an authorized batch of files and valid, in-scope `Act` findings
   before fixing. Do not automatically fix style observations, decisions, or
   uncertain investigations. Use one code writer. Run relevant checks, then
   delegate an independent focused review of the correction delta and its
   affected callers using the same review-role options.
5. Validate review-fixes findings inside this cycle. Resolve applied-fix
   outcomes, then advance. If actionable issues remain, fix them in the
   same outer loop. Inner exhaustion stops the entire run.
6. When the sub-loop is clean, start another full review within the outer
   limit. Only a final full review requiring no new edits can complete the run.
7. Report from the ledger between cycles/loops and at termination. Distinguish
   completion, accepted exceptions, limits, failures, and incomplete verification.

## Autonomy and safeguards

Make review-policy decisions without pausing for user input. Explain them
in the ledger, including accepted uncertainty and reasons not to fix.
Difficulty or exhausted limits do not make a finding false or resolved.
Never weaken tests or invent requirements to make the run look successful.

Preserve the user's changes and normal permission controls. Do not commit,
push, post comments, resolve threads, deploy, or change unrelated behavior.
Tests can have side effects; run only operations within granted permissions.
If required capabilities or permissions are unavailable, record a blocked
outcome rather than bypassing them or claiming complete coverage.

Use the host's native delegation tools and the
[shared orchestration instructions](../review-code/ORCHESTRATION.md).
Check override authority before model research and reuse applicable selection
evidence within a review. Unspecified roles attempt automatic selection by
default where permitted, otherwise use configured defaults and disclose the
limitation. Explicit choices follow their declared fallback. Supply the [review contract](../review-code/CONTRACTS.md),
including relevant ledger history and explicit completion conditions.
Failed or partial workers are not clean reviews.

Only the outer loop updates the ledger through its helper. Never hand-edit
state, reset counters, or create a replacement run to evade a limit. Use
snapshot checks before trusting evidence, especially on resumption.
These are best-effort agent instructions, not a hard workflow boundary.

A surrounding autonomous-development controller does not inherit commit or
publication authority from this skill. Its reviewers remain separate from
implementation, including small reviews. Task reviews do not replace full-PR
review, and focused correction reviews do not replace full-scope confirmation.
Finish the active cycle with stable HEAD/index before separately authorized
commits. The review/fix owner retains the ledger; the controller keeps references.
Loop completion does not waive the caller's acceptance requirements or establish
PR readiness. Exceptions must stay within the approved decision authority.
