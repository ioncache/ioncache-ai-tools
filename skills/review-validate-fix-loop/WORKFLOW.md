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

Start with `start_review`, which increments the outer count before launching
the review coordinator or any worker. Use `review-code` with the recorded
base and current ledger snapshot; do not create a second run or snapshot.
Follow the [shared orchestration instructions](../review-code/ORCHESTRATION.md):
the dedicated review coordinator owns specialist launches in nested mode;
the loop owns launches and collection in flat mode, then uses a separate
adjudicator. Keep the small-review shortcut only where caller independence
requirements permit it; autonomous development always separates review from
implementation. Retain the cross-cutting correctness pass. The outer loop
remains the sole ledger writer and owns limits and fixes.
Pass the chosen strategy separately from topology, following the shared
capacity and risk rules for `sweep-first` or `specialists`. Count the sweep
and its follow-ups inside the same review.
Do not use it to skip standards, independent validation, or whole-file reads.
Assign reports in private scratch outside the reviewed tree and forward their
paths for direct adjudicator reads. These reports are separate from the loop's
ledger artifacts; only the outer loop translates their evidence into events.

Record every candidate through `finding`, including low-confidence candidates
that require validation. Use an underlying-behavior key consistently within
the run. Repeated keys append observations instead of creating new findings.
Provide changed locations, severity, and concrete evidence, not only a verdict.
Keep every candidate even when non-reportable or below the human report's
severity floor. Apply the shared actionability policy before selecting fixes;
the severity display floor alone does not change fix policy or completion.

After all required reviews finish, record `review_done` with each pass's
worker, coverage evidence, and verification checks. If a worker fails or a
required check cannot be performed, record `stop` with an incomplete outcome.
Do not fabricate a successful pass or label an unavailable check unnecessary.

Coordinator/adjudicator assessment supplies independent validation of
specialist findings. Check the handback for evidence completeness, matching
assignments and snapshots, and unresolved contradictions. Investigate gaps,
not every completed investigation again. Independently validate findings
originating from the coordinator/adjudicator. Inline review must not claim
independent validation that did not happen. Follow the shared
[caller-validation role](../review-code/ORCHESTRATION.md#independent-caller-validation)
when the owner is scripted or cannot provide the required independence.
Mechanical checks cannot replace those assessments.

Record a `decision` for every pending finding after `review_done`, following
the [handback mapping](LEDGER.md#review-handback-mapping). A reachable failure,
caller contract, documented standard, or unmet usage-documentation requirement
can validate an issue. Model agreement alone cannot. Distinguish truth from
scope, actionability, and risk acceptance. Apply
[../review-code/CRITERIA.md#actionability](../review-code/CRITERIA.md#actionability), not a
blanket rule that valid observations on new code require edits. Inaccurate
documentation and missing test coverage are actionable under that policy;
accurate documentation in a nonpreferred style is not. Preserve `report_action`,
reachability, confidence, priority, and the rationale in decision evidence.
New evidence can reopen an ignored or resolved entry; repeat wording alone
should not re-report it as new.

Record non-reportable underlying issues as ignored with their reasons, even
when valid against a style convention. Do not feed them into a fix batch.
Attach duplicate observations to the canonical issue without overwriting its
assessment merely because another reviewer found it.
`Decide` and `Investigate` require a decision or evidence, not an automatic
code change. Keep consequential unresolved issues open until resolved or
explicitly accepted with evidence and residual risk.

The agent can decide to ignore a valid or uncertain issue with a specific
reason, evidence, and residual risk. It must not ask the user to adjudicate
review findings. Unaccepted uncertain findings remain open; investigate,
make a recorded decision, or stop as blocked/stalled.

## Nested correction cycles

Only in-scope, valid `Act` findings are eligible for `start_fix`. Use their IDs
and an exact list of files the batch may change, including new tests/docs.
Eligibility comes from the semantic assessment, not visibility in the report
or a ledger disposition alone. This records intent and consumes one inner cycle.
Use one writer and do not stage or commit changes. Preserve pre-existing edits
in those files.

Run the smallest relevant checks and record `fix_done`, with a per-finding
applied/failed result and check evidence. An attempted fix is not yet a verified
resolution. The helper rejects changes outside the declared files or changed
HEAD/index metadata. It never reverts code to resolve such conflicts.

Use `diff` with the cycle's `before` and `after` snapshots for focused review.
Use the same review boundary with a `focused` request. Include each attempted
correction, affected callers, regression risk, weakened checks, and unrelated
changes. All outstanding inner-cycle findings remain relevant, not only the
latest changed lines. Do not silently expand this into a full review. Record
candidates and `fixes_reviewed`, then validate the new candidates in this same
cycle using the same specialist/coordinator ownership rules.

For each applied fix, record `fixed` only with passing relevant verification
and completed review-fixes, or record `fix_failed` when it is not resolved.
An uncertain correction is not verified. Record `advance` after decisions:

- Remaining eligible `Act` findings with capacity: start another fix cycle.
- Remaining eligible `Act` findings at the inner limit: the whole run stops.
- Unresolved consequential decisions or investigations: resolve them in
  validation, explicitly accept the risk with evidence, or stop as blocked/stalled.
  Do not start a fix cycle solely for them or advance past an open issue.
- No open issues or pending validation: the next outer review may start if
  capacity remains.
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
If a blocked/interrupted run cannot resume safely, send `stop` with outcome
`failed` or `stalled`. This terminates the run without reverting files or
changing its evidence snapshot, finding history, or consumed allowances.
Do not delete the ledger or reconstruct an earlier worktree just to abandon it.

Stop for unrecoverable errors, missing capabilities, or oscillating fixes.
Use `blocked` for recoverable worker/capability failures and `interrupted`
for interruptions. Use terminal `failed` for unrecoverable errors or
`stalled` when further progress is abandoned. Do not copy a worker's `failed`
outcome into the run outcome without deciding whether the run can resume.
Do not repeatedly relaunch a failing worker within a phase to evade counts.
The coordinator's ledger reasons record the failure and its consequences.
Malformed storage, missing evidence, or helper errors must be surfaced.

## Reporting and limitations

Report run ID, outcome, loop/cycle usage, reportable findings by severity and
action, verified resolutions, consequential accepted risks, failed attempts,
and incomplete coverage. Use the shared human-report policy; count non-reportable
observations without dumping their details or presenting them as residual risks.
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
