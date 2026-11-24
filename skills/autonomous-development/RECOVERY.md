# Execution and recovery

The launching agent runs the deterministic helpers and invokes native batches.
Python owns reservations, dispatch accounting, file validation and transitions.
Workers own only their assigned work and reports. Native workflow output is an
activity observation, never the authoritative state or completion receipt.

Use the returned pinned `development_handoff.py` for handoffs and its sibling
`development_run.py` for status and lifecycle commands. Keep the same run,
approved inputs, executor pin, assignment history and consumed allowances.
Do not edit `RUN.json`, refund counters, or repair an executor by changing the
tree under review.

## Select recovery from evidence

| Condition | Agent-executable recovery |
| --- | --- |
| `prepare` reply lost | Repeat `prepare`. The same unclaimed batch and generated script are returned without another reservation. |
| `claim` reply lost | Read `status`, inspect native activity and existing files. A claim is a reservation for launch, not proof of a native start or of no start. Never blindly launch again. |
| `collect` reply lost | Repeat `collect` for that batch. Its saved receipt prevents duplicate advancement. |
| JSON malformed or required field missing | Read the validator's exact error. Correct only the report from existing evidence within its remaining allowance, then resubmit. |
| Report allowance exhausted, preserved candidate is correctable | Stop the original worker, inspect its effects, run `check-report`, then use the job's one `recover-report` submission with evidence and shutdown evidence. Run `collect` afterward; no worker or external effect is repeated. |
| Required capability or evidence absent | Record a capability only a later step can establish as `deferred`, naming that step. Report `blocked` only for an observed absence (`missing`). Do not upgrade an unexercised capability to `verified` to satisfy validation. After the environment is fixed, `resume` and let `prepare` reserve a counted preflight retry. |
| Workflow tool refuses the store's `scriptPath` | The tool rejected the call before starting a run. For an unclaimed batch, `claim` with `--launch-dir` set to a private directory the host can read. For an already claimed batch, confirm the refusal returned no run ID and `status` shows no start receipt, then run `prepare --launch-dir DIR` to get the same batch's verified copy and launch it once. Never paste the script inline. |
| Workflow tool refuses a claimed script for another reason | For example, the script exceeds the tool's size limit. Confirm the refusal returned no run ID and `status` shows no start receipt, then run `release STORE --batch B --evidence TEXT` with how the host refused it. The batch becomes `released`, its reviewer reservations return to the queue, and the next `prepare` issues a new batch without another assignment. A stale launch of the released script fails its `start` check. A batch with any start receipt cannot be released; collect or reconcile it. |
| Owner request too large to launch alone | `finish` or `submit` rejects the owner's dispatch report as a correctable error naming the request. Shorten its prompt within the remaining correction allowance; a frozen reviewer packet that cannot fit leaves the review blocked. A request queued by an older executor makes `prepare` refuse without creating a batch: run `interrupt`, then `resume-review` with native shutdown evidence, then `prepare`, so the owner replans it. |
| Worker restarted by the host | Claude restarts a stalled agent from the same prompt, at most five times, and a relaunched run starts unfinished agents over. For roles whose effects stay in the private store or the reviewed worktree, a repeated `start` reports the restart: the replacement reconciles the earlier attempt's effects and does only the remaining work, or returns at once if a validated report exists. The helper cannot tell a restart from an accidental second launch, so `commit`, `draft`, `ready`, `evidence` and audit roles still refuse a repeated `start`; inspect their remote effects, then collect, or retire with shutdown evidence for a counted retry. After five restarts, `start` refuses; handle the job as for a missing report. |
| Claimed job has no validated report | Inspect native activity. Collect a finished file using `finish`; let an active worker finish. No report does not mean no work occurred. |
| Reviewer file survived shutdown but its receipt did not | After reconciliation, run `finish STORE --batch ORIGINAL_BATCH --job ORIGINAL_JOB` for the started reviewer, even if its batch is now reconciled. Use the validated original result without relaunching it. Missing or invalid results remain incomplete. |
| Native failure or worker gone | Reconcile local and remote effects and establish shutdown. Retain readable reviews with `resume-review`; otherwise collect or retire the assignment before a counted retry. |
| Prepared, never-claimed batch interrupted | After repairing the cause, use `resume-prepared`. The script requires a durable unclaimed batch, not a textual assertion that it never launched. |
| Generated script changed before claim | Run `repair-script`. It preserves the changed file and regenerates from pinned data, without another assignment. Claimed scripts cannot be repaired for relaunch this way. |
| Pinned executor changed | Stop native work and interrupt scheduling. Run `restore-executor` from an intact helper with a source matching the entire recorded pin. Corrupted resources remain archived. |
| Accepted branch rebased onto its target with the same patch | At an assignment boundary, use `rebase-review` with the new target-base commit. It verifies the saved snapshot patch, records the base transition and preserves the original review and allowances. |
| Reviewed patch changed | Preserve edits and stale reports; reconcile the review against the actual delta within its remaining allowance. Never relabel stale reports as current coverage. |
| Run stopped before an audit assignment, or completed without a usable publication | Use `development_audit.py archive STORE --pr ID --public FILE`, inspect both files, then `publish-archive STORE --pr ID --approved IDENTITY`. No reservation or run-state change is required. If the PR URL was not recorded, supply `--pull-request URL`. Existing authorization, opt-outs, ownership and exact accepted-commit checks still apply; see `AUDIT.md`. |
| Archive's accepted commit differs from the PR head | Retain the archive. Use counted review reconciliation, or `rebase-review` for a supported unchanged target rebase, then export and inspect new evidence. If no authorized recovery remains, report publication incomplete. Do not force-push, relabel coverage or rewrite history. |
| Archive publication response or receipt lost | Repeat the same `publish-archive`. A validated receipt acknowledges the historical publication without remote writes, even after run history advances. With no receipt, inspect existing effects: matching navigation can be recovered, but changed run evidence requires a fresh archive and inspection. |
| Archive retry reports partial or superseded publication | Preserve the newer audit pointers and retain the archive. Inspect the wiki and PR to establish which effects completed. Use `--republish` only when intentionally restoring this archive, not as an automatic retry fallback. It retains fresh-evidence and exact-head checks; otherwise keep the newer audit or export and inspect new evidence. |
| Lock, settings, storage or checker unavailable | Preserve the error. Status and necessary investigation remain available. Retry a contended helper after the writer finishes; do not grant permission or invent success. |
| Allowance exhausted | Preserve the incomplete result and explain what remains. Do not restart the run, combine review purposes, or raise limits implicitly. Continue unrelated authorized work where possible. |

For a never-claimed batch:

```sh
python3 "/private/run/executor/scripts/development_handoff.py" repair-script "/private/run" \
  --batch B000001
python3 "/private/run/executor/scripts/development_handoff.py" resume-prepared "/private/run" \
  --batch B000001 --reason "Exact inputs and executor restored"
```

Restore a damaged pin only after native shutdown. The source must match every
recorded resource; a newer release is not an equivalent recovery source:

```sh
python3 "/intact/plugin/scripts/development_handoff.py" restore-executor "/private/run" \
  --source "/matching/plugin" --shutdown-evidence "Native worker and owned processes exited"
```

The supplied shutdown evidence is a caller declaration, not independent host
verification. Record the actual observed native IDs/status where available.
Do not infer shutdown from a stopped shell or absent monitor output. Use
`CONTRACT.md` for `interrupt`, `resume-review`, `retire`, `resume` and ledger
recovery commands; use actual current revisions.

## Report generation and correction

Workers run their generated `start` command before work. A duplicate start
requires inspection, not another execution of side effects. They then write a
candidate or full report and invoke their supplied `submit` or `finish` command.

For development candidates, the script supplies assignment and approved artifact
identities. The model supplies only outcome, summary, evidence and role-specific
data, with optional worker/model observations. Review leaves retain their full
purpose-specific JSON contract. An owner can submit `outcome`, empty `requests`,
and a `report` development candidate to generate its final report and pointer.
Dispatch requests must carry the real frozen packets and distinct private paths.

Generated development prompts include each role's required `data` fields, types
and meanings from the same definitions the validator uses. The outcome is exactly
`complete`, `blocked` or `waiting`, not `completed`. Top-level `evidence` is a
nonempty list of strings; draft/ready `data.evidence` is one nonempty string
describing the observed publication state. `autonomous-development-report-contract`
disables only the added contract text, never validation.

Use the supplied `check-report` command before submitting. It checks candidate
shape and role requirements without writing files, accepting work or spending
corrections. A relative candidate path is resolved against the private run store,
not the worker's working directory. Escapes and symlinks remain rejected.

Validation checks structure, identities, available referenced files and reserved
roles. Acceptance still checks real worktree/ledger/publication evidence through
the existing controller. Valid JSON is not proof that work happened.
Owner envelopes and referenced development reports must agree on their outcome.
Both files are bound to their submitted bytes, and collection consumes that same
verified snapshot. Generated owner paths are separate from leaf report paths.
Final category acceptance uses the archived reviewer bytes, not just matching
packet identities. An altered handoff result must be restored from that archive.
Restoring unreadable ledger or archive evidence does not spend report corrections.

If collection rejects report content, correct it with `submit` or `finish` within
the same allowance. Rejected reports remain archived; successful collection is
immutable. Retrying collection of the same rejected receipt does not spend another
correction, and restored underlying evidence can be checked again without changing
the report. Missing files and storage failures do not spend report corrections.
An older owner receipt without a referenced-report digest requires `finish` to
validate and bind the current reference before collection. This does not establish
what that reference contained before binding.

The default permits an initial validation and two corrections in the same worker.
`autonomous-development-report-correction: false` permits the initial validation
only; it does not disable validation. Failed candidates and counters persist
across native relaunches. No extra model workers are launched for correction.
Consumed assignments and review dispatches bound fresh replacement work across
the run. Host-internal retries and token/cost usage are not measured by those
counters; disclose native resource-control gaps.

Never repeat a commit, push, publication, implementation or reservation to fix
its JSON acknowledgment. Regenerate the report from recorded and observed state.
Successful submissions are digest-bound; changed reports need reconciliation,
not silent replacement. Retain partial evidence even when a later batch fails.

### Exhausted report recovery

After the original worker has exited, the launcher can correct a preserved
candidate from existing evidence and run:

```sh
python3 "/private/run/executor/scripts/development_handoff.py" check-report "/private/run" \
  --batch B000022 --job 1 --candidate "reports/A0008.json.candidate.json"
python3 "/private/run/executor/scripts/development_handoff.py" recover-report "/private/run" \
  --batch B000022 --job 1 --candidate "reports/A0008.json.candidate.json" \
  --evidence "Inspected the existing PR and corrected only its report" \
  --shutdown-evidence "Original native worker exited; no worker can still write the report"
python3 "/private/run/executor/scripts/development_handoff.py" collect "/private/run" --batch B000022
```

Use actual IDs and observed evidence. Shutdown evidence is a caller declaration,
not independent host verification. The enabled-by-default
`autonomous-development-report-recovery` feature permits one recovery attempt
per started job after its normal allowance is exhausted. It is recorded before
validation, so a crash or invalid candidate does not grant another attempt.
Precheck first. Recovery uses the same report validators and collection still
performs the same acceptance checks. It grants no native permission, changes no
assignment/dispatch allowance and repeats no external operation.
The candidate digest, recovery evidence and result remain in the batch record;
ordinary correction counters are not reset. A successful receipt can be reread
before collection, and collection remains idempotent. An invalid recovery stays
incomplete; preserve its evidence and use existing retirement or other authorized
work rather than inventing another recovery allowance.

## Accepted-review rebase

After an authorized rebase, with no outstanding assignment, run:

```sh
python3 "/private/run/executor/scripts/development_run.py" rebase-review "/private/run" \
  --revision 17 --pr "planned-pr-id" --new-base "<full target-base commit ID>" \
  --reason "Branch rebased onto its target without changing its reviewed patch"
```

This verifies an existing rebase; it does not perform one or push a branch.
The base must descend from the approved and previously accepted bases, be
reachable from the PR's target ref, and be an ancestor of the branch HEAD.
The helper prefers the approved remote's target-tracking ref, using the local
target branch only when that ref is absent. Fetch a stale or missing target
through the already authorized Git workflow, then retry.

The helper reconstructs the original reviewed and current snapshot trees in a
temporary private Git repository. This includes binary content, modes,
symlink targets and non-ignored untracked files. It uses `git merge-tree --write-tree`
to replay the reviewed snapshot onto the new base and requires the result tree
to match the current snapshot exactly. Matching patch IDs alone cannot prove
equivalence: the same edit in a different repeated section must not pass.
Source-repository reads keep Git's existing trust checks; replay uses a separate
repository without the source's local, global or system configuration.
Missing Git support or objects reports unavailability; restore them and retry.
Conflicts, a different result tree, an invalidated/abandoned ledger or a missing
retained snapshot cannot use this path. Changed patches need a counted review.

Successful recovery appends old/new bases, heads, snapshot and patch identities,
the observed target ref and the reason to `review_rebases`. It refreshes the
accepted checkout and future comparison base, not the original review ledger,
snapshot, category coverage or review history. The original ledger can still
report checkout drift; the separate rebase evidence explains that transition.
No review or assignment is launched, and no allowance is reset.
Completed UI evidence and final audits for an older commit are scheduled again
before readiness, with UI evidence first when both need refreshing. Old reports
remain historical evidence, not receipts for the new commit. Recovery checks
that the remaining assignment and per-role attempts can cover this PR's delivery
steps before changing acceptance; insufficient capacity leaves the state intact.
Readiness reservation and handback require UI evidence and any enabled final
audit to identify the accepted commit.

`reconcile` checks review and assignment capacity before dropping acceptance.
If review attempts are exhausted, it leaves the state intact for a provable
clean-rebase recovery. It does not grant a review to changed code when no
allowance remains. `autonomous-development-rebase-review: false` disables this
specialized recovery without disabling ordinary review or inspection.

Git contracts used here:
https://git-scm.com/docs/git-merge-tree
https://git-scm.com/docs/git-diff
https://git-scm.com/docs/git-hash-object
https://git-scm.com/docs/git-update-index
https://git-scm.com/docs/git#_environment_variables

## Visibility and qualification

Give five-minute user-visible updates during long work and disclose blockers
immediately. Separate native activity, script checkpoints, report validation,
semantic acceptance, monitor failure and intentional cancellation. Watch
inactivity alone never authorizes cancellation or a replacement worker.

Offline checks establish only the exercised local contracts. A later live-host
qualification uses a separate bounded scenario and explicitly selected resources,
not a restart of an incident run. Do not claim complete native delivery or
publication based on schema checks, mocks, dry runs or permission availability.

Some host limits are observed or unknown rather than documented. The Workflow
tool's 524,288-byte script limit appears in its tool schema and refusal message,
not in the workflow documentation. What happens when a token budget such as
`+500k` runs out is undocumented; treat a thrown `agent()` call as a native
failure for the job. Native transcripts record a `pickedEffortModel` that can
differ from the agent's model; its meaning is undocumented, so do not record it
as the observed model or effort.

Claude documents no direct filesystem, shell or module access inside a Workflow
script. Therefore Python generates the complete batch script beforehand, and the
launching agent invokes its `scriptPath`, or the verified `--launch-dir` copy,
without transporting control JSON through a model. Native agents can still fail or misreport; the collector reads their
actual files and never accepts the workflow's prose as state:
https://code.claude.com/docs/en/workflows#behavior-and-limits
