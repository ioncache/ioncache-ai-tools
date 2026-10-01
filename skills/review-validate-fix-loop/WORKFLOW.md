# Coordinator workflow

## Scope and starting

Interpret the target as `repository`, `branch`, a PR reference, or specific
files/directories. With no target, use the active PR if present; otherwise
use the branch change against the local default branch. Resolve its
merge-base once. If no default-branch reference is available, use `HEAD`
for local changes and explicitly record that narrower scope. A read error
is not evidence that there is no PR or default branch.

For repository or path reviews, pre-existing issues within the target are
in scope. For branch/PR changes, focus corrections on introduced or worsened
issues and record discovered out-of-scope risks separately. Pin the base
commit in the ledger. Include local staged, unstaged, and relevant untracked
files. Do not repeatedly review a remote diff that excludes local fixes.
Do not check out a different branch or overwrite existing work to review a PR.
If the PR is not represented by the current worktree, report the mismatch.

Initialize the helper with the resolved `--objective`, `--scope` description,
`--base` commit, and limits. Defaults are three outer loops and three inner
cycles per outer loop. Store effective choices in the ledger before reviewing.
The helper allows only one running or resumable run per worktree. Independent
runs need isolated worktrees or a terminal prior run.

## Review and validate

Start with `start_review`, which increments the outer count before any worker
launch. Use `review-code` with the recorded base and current snapshot. Divide
independent standards passes among read-only agents; do not delegate a single
trace merely to add agents. Retain an integration-level correctness pass.

Record every candidate through `finding`, including low-confidence candidates
that require validation. Use an underlying-behavior key consistently within
the run. Repeated keys append observations instead of creating new findings.
Provide changed locations, severity, and concrete evidence, not only a verdict.

After all required reviews finish, record `review_done` with each pass's
worker, coverage evidence, and verification checks. If a worker fails or a
required check cannot be performed, record `stop` with an incomplete outcome.
Do not fabricate a successful pass or label an unavailable check unnecessary.

Validate findings independently of the reviewer where practical. Record a
`decision` for every pending finding. A reachable failure, caller contract,
documented standard, or unmet usage-documentation requirement can validate an
issue. Model agreement alone cannot. Distinguish truth from scope and risk
acceptance. New evidence can reopen an ignored or resolved entry; repeat
wording alone should not re-report it as new.

The agent can decide to ignore a valid or uncertain issue with a specific
reason, evidence, and residual risk. It must not ask the user to adjudicate
review findings. Unaccepted uncertain findings remain open; investigate,
make a recorded decision, or stop as blocked/stalled.

## Nested correction cycles

If there are actionable valid findings, use `start_fix` with their IDs and
an exact list of files the batch may change, including new tests/docs. This
records intent and consumes one inner cycle. Use one writer and do not stage
or commit changes. Preserve pre-existing edits in those files.

Run the smallest relevant checks and record `fix_done`, with a per-finding
applied/failed result and check evidence. An attempted fix is not yet a verified
resolution. The helper rejects changes outside the declared files or changed
HEAD/index metadata. It never reverts code to resolve such conflicts.

Use `diff` with the cycle's `before` and `after` snapshots for focused review.
The reviewer checks each attempted correction, affected callers, regression
risk, weakened checks, and unrelated changes. All outstanding inner-cycle
findings remain relevant, not only the latest changed lines. Record candidates
and `fixes_reviewed`, then validate the new candidates in this same cycle.

For each applied fix, record `fixed` only with passing relevant verification
and completed review-fixes, or record `fix_failed` when it is not resolved.
An uncertain correction is not verified. Record `advance` after decisions:

- Remaining actionable findings with capacity: start another fix cycle.
- Remaining actionable findings at the inner limit: the whole run stops.
- No actionable findings: the next outer review may start if capacity remains.
- No remaining outer capacity after fixes: final full-scope confirmation is
  incomplete, even when the focused review passed.

A full review with no actionable findings and no pending validation can
`advance` directly to completion. Fix phases are unnecessary and consume no
inner cycles. Accepted valid or uncertain issues yield completion with
exceptions, not a clean result.

## Resumption, drift, and failures

`status` reads the ledger, replays its events, verifies snapshot objects, and
compares the current worktree to the last evidence snapshot. It is also the
report source; it does not mutate the run.

A running run can continue its recorded phase after interruption. If it was
explicitly stopped as interrupted/blocked, send `resume` with a reason after
checking the actual files. Retain counts, original scope, and finding history.
Inspect partially applied edits before doing more work in an interrupted fix.

Read-only-phase drift requires `reconcile` with evidence. This invalidates
old judgments and consumes another outer loop when full review restarts;
it never refunds completed or interrupted work. During fixing, only declared
file edits with unchanged HEAD/index can be recovered through `fix_done`.
Unexpected edits require stopping with an explanation, not a silent reset.

Stop for unrecoverable errors, missing capabilities, or oscillating fixes.
Do not repeatedly relaunch a failing worker within a phase to evade counts.
The coordinator's ledger reasons record the failure and its consequences.
Malformed storage, missing evidence, or helper errors must be surfaced.

## Reporting and limitations

Report run ID, outcome, loop/cycle usage, findings by severity and disposition,
verified resolutions, accepted risks, failed attempts, and incomplete coverage.
Reports between iterations distinguish new findings from repeated observations.
Do not claim token or cost limits; Phase 1 does not collect usage.

Saved snapshots cover tracked and non-ignored untracked files across the
worktree, excluding `.review-loop/`. Ignored inputs and external systems are
not snapshotted. Submodules and special files are currently unsupported and
cause explicit errors. Symlinks are saved as target text, never dereferenced;
the helper rejects symlink paths in fix declarations.

Artifacts are local, private-by-default files under `.review-loop/<run-id>/`.
They may contain project source. Do not stage, commit, or upload them. They
are retained until explicitly removed; do not auto-delete evidence. The
helper does not modify a consuming project's ignore files.

Every new run has a separate ledger, even within one conversation. A resumed
run uses its existing ledger even in a new session. Iterations share one
history so ignored findings stay suppressed while their rationale holds.
