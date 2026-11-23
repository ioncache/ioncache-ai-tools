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
| Required capability or evidence absent | Record a capability only a later step can establish as `deferred`, naming that step. Report `blocked` only for an observed absence (`missing`). Do not upgrade an unexercised capability to `verified` to satisfy validation. After the environment is fixed, `resume` and let `prepare` reserve a counted preflight retry. |
| Workflow tool refuses the store's `scriptPath` | The tool rejected the call before starting a run. For an unclaimed batch, `claim` with `--launch-dir` set to a private directory the host can read. For an already claimed batch, confirm the refusal returned no run ID and `status` shows no start receipt, then run `prepare --launch-dir DIR` to get the same batch's verified copy and launch it once. Never paste the script inline. |
| Claimed job has no validated report | Inspect native activity. Collect a finished file using `finish`; let an active worker finish. No report does not mean no work occurred. |
| Reviewer file survived shutdown but its receipt did not | After reconciliation, run `finish STORE --batch ORIGINAL_BATCH --job ORIGINAL_JOB` for the started reviewer, even if its batch is now reconciled. Use the validated original result without relaunching it. Missing or invalid results remain incomplete. |
| Native failure or worker gone | Reconcile local and remote effects and establish shutdown. Retain readable reviews with `resume-review`; otherwise collect or retire the assignment before a counted retry. |
| Prepared, never-claimed batch interrupted | After repairing the cause, use `resume-prepared`. The script requires a durable unclaimed batch, not a textual assertion that it never launched. |
| Generated script changed before claim | Run `repair-script`. It preserves the changed file and regenerates from pinned data, without another assignment. Claimed scripts cannot be repaired for relaunch this way. |
| Pinned executor changed | Stop native work and interrupt scheduling. Run `restore-executor` from an intact helper with a source matching the entire recorded pin. Corrupted resources remain archived. |
| Reviewed tree changed | Preserve edits and stale reports; reconcile the review against the actual delta within its remaining allowance. Never relabel stale reports as current coverage. |
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

## Visibility and qualification

Give five-minute user-visible updates during long work and disclose blockers
immediately. Separate native activity, script checkpoints, report validation,
semantic acceptance, monitor failure and intentional cancellation. Watch
inactivity alone never authorizes cancellation or a replacement worker.

Offline checks establish only the exercised local contracts. A later live-host
qualification uses a separate bounded scenario and explicitly selected resources,
not a restart of an incident run. Do not claim complete native delivery or
publication based on schema checks, mocks, dry runs or permission availability.

Claude documents no direct filesystem, shell or module access inside a Workflow
script. Therefore Python generates the complete batch script beforehand, and the
launching agent invokes its `scriptPath`, or the verified `--launch-dir` copy,
without transporting control JSON through a model. Native agents can still fail or misreport; the collector reads their
actual files and never accepts the workflow's prose as state:
https://code.claude.com/docs/en/workflows#behavior-and-limits
