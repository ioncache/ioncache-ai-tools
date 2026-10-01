---
name: review-validate-fix-loop
description: Autonomously reviews, validates, fixes, and re-reviews code within finite nested loops, preserving decisions in a per-run ledger. Use when explicitly asked to run a bounded review-and-fix loop or resume one, not for a read-only review.
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
Do not accept model, effort, cost, or persistent-config options in this version.
Report invalid arguments without starting a run. Do not silently ignore them.

Resolve `../../scripts/review_ledger.py` relative to this installed skill,
not the current working directory or an assumed host environment variable.
Run its absolute, shell-quoted path using Python 3.11+ from the consuming
Git worktree. Read its `--help` if invocation details are unclear.

## Coordination

1. Resolve the target, objective, and comparison base using the workflow.
   Initialize one ledger, or inspect the explicitly selected resumed run.
2. Start a full review through `review-code`. Use independent read-only
   subagents for substantial standards passes, plus cross-cutting correctness.
   The coordinator owns all launches; do not require nested delegation.
3. Collect findings and validate them against requirements and actual callers.
   Record each candidate, duplicate observation, decision, reason, and evidence.
4. Declare an authorized batch of files and findings before fixing. Use one
   code writer. Run relevant checks, then delegate an independent focused
   review of the correction delta and its affected callers.
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

Use the host's native delegation tools and configured model defaults.
Give workers the objective, scope, snapshot, relevant standards and ledger
history, read-only role, and explicit completion conditions. Wait for all
required results. Failed or partial workers are not clean reviews.

Only the coordinator updates the ledger through its helper. Never hand-edit
state, reset counters, or create a replacement run to evade a limit. Use
snapshot checks before trusting evidence, especially on resumption.
These are best-effort agent instructions, not a hard workflow boundary.
