# Manifest and run protocol

The manifest is a normalized interpretation of the human plan, not a second
source of requirements. JSON is used for deterministic validation. Approval
identifies its canonical JSON digest and every referenced artifact digest.
It is an approval record, not authentication or a native permission grant.

## Manifest schema 1

All listed fields are required. Unknown fields are rejected. IDs use lowercase
letters, digits, and hyphens, beginning with a letter.

| Field | Content |
| --- | --- |
| `schema` | `1` |
| `objective` | Agreed outcome |
| `configuration.planning` | Independent `provider` and `location` strings |
| `configuration.design` | Independent `provider` and `location` strings |
| `configuration.execution` | Independent `provider` and `environment` strings |
| `repository` | Exact `remote` name and `url`, plus `default_branch` |
| `artifacts` | Records with `id`, `role`, `source`, `snapshot`, `sha256` |
| `prs` | PR records below |
| `tasks` | Task records below |
| `limits` | Positive integer `assignments`, `attempts`, `review_loops`, `fix_cycles`, `review_dispatches` |
| `permissions` | Explicit booleans for `commit`, `push`, `create_pr`, `mark_ready`, `screenshots` |
| `constraints` | Non-empty list of scope, decision, risk-acceptance, model, and operational constraints |

Artifacts include all three roles: `requirements`, `design`, and `plan`.
`source` identifies the authoritative issue, document, or file. `snapshot` is a
normalized relative file path within the private manifest bundle. `sha256`
identifies its exact bytes. Snapshot paths cannot escape the bundle. The helper
copies them into the run, so deleting the intake bundle does not destroy evidence.

The helper checks snapshot bytes, not the current contents of a remote issue or
page. Workers must verify current source identities with their selected service
tools and report every approved artifact identity. Missing access, changed
requirements, or an unreadable snapshot is not permission to substitute a summary.
Repository documents may be the selected sources; hosted services are optional.

Each PR contains `id`, `goal`, `branch`, `worktree`, `base`, `target`,
`dependencies`, `checks`, and `rollout`. Worktrees are distinct, non-overlapping
paths relative to the launch repository root. The initial implementation uses
new branches and worktrees; it never adopts an existing checkout implicitly.
`base` is a full commit ID. `target` is the intended PR base branch.
Owned branches cannot equal the default or target branch.

PR dependencies use **wait for human merge**, not automatic stacking or rebasing.
Preparation verifies the prerequisite PRs are actually merged and pins its
resulting base, which must descend from the approved base. Waiting PRs do not
prevent independent increments from proceeding. No force-push is permitted.

Each task contains `id`, `pr`, `goal`, `paths`, `dependencies`, `artifacts`,
`checks`, `compatibility`, and `completion`. A path allows that file or directory
subtree; `.` explicitly allows the entire worktree. Paths are not shell patterns.
Cross-PR task dependencies also require the corresponding PR dependency.
Cycles, unknown references, empty PRs, and duplicate IDs are invalid.

Every task and PR has at least one check:

```json
{
  "name": "unit tests",
  "command": "npm test -- --run",
  "cwd": ".",
  "expected": "Exit zero with all required tests passing"
}
```

Commands come from the consuming project, not this example. Record semantic
acceptance evidence when a command alone cannot establish the outcome. Required
checks cannot be replaced by `not_applicable` in the final review handback.

`assignments` caps durable top-level reservations across the run. `attempts`
caps attempts at the same role/task or role/PR. Reservations consume capacity
before dispatch; missing results do not refund it. `review_dispatches` bounds
review-owner plus leaf calls per review assignment attempt. The existing review
ledger retains its own outer and inner allowances.

These are logical execution limits, not hard token, time, or spending caps.
Control workers and host-native retries also consume model usage. Establish
available native resource controls during preflight and disclose gaps.

## Durable controller

Use `../../scripts/development_run.py` relative to the installed skill directory.
It returns JSON and never launches a model, runs an acceptance command, commits,
pushes, or invokes a hosting API. Agents execute assigned operations and supply
evidence; the controller validates bookkeeping and local Git/review invariants.
It does not prove the truth of model reports or remote-operation receipts.

Private storage contains `RUN.json`, `MANIFEST.json`, approved `inputs/`, and `reports/`. It must
be outside the repository. Keep it durable for the chosen environment and do
not upload it wholesale. The code does not provision shared cloud storage.
Published state is atomic, revisions reject stale writers, and one outstanding
assignment prevents overlapping writers within the run.

```sh
python3 "/absolute/plugin/scripts/development_run.py" next "/private/run" --revision 0
python3 "/absolute/plugin/scripts/development_run.py" record "/private/run" \
  --revision 1 --report "/private/run/reports/A0001.json"
```

`next` reserves one assignment or reports completion/waiting/exhaustion. The
request contains the approved settings, constraints, pinned artifact paths,
worktree, task/PR scope, limits, and exact result path. Preserve the full request.
It also names the complete shared `manifest_file`, its canonical `approval`
identity, and prerequisite PR progress. Missing or changed shared input leaves
the assignment incomplete.
`record` requires the assigned ID and complete report. Repeating an identical
recorded report is idempotent; altered or stale reports cannot advance another
assignment.

Every report contains `assignment`, actual `worker` identity, `outcome`
(`complete`, `blocked`, or `waiting`), `summary`, non-empty `evidence`, `artifacts`
(approved ID-to-digest map), and role-specific `data`. A worker cannot invent a
host ID or treat an unobservable identity as verified. Keep the full report;
returning its path is not itself evidence of successful work.

Review results refer to the existing `.review-loop/<id>/REVIEW_LEDGER.json`.
The controller verifies its completion, base, current snapshot, exact allowances,
and passing named acceptance checks. Complete-with-exceptions results remain
visible in PR progress; they are not relabeled as clean reviews.

Task review finishes before commit. Full-PR review follows draft publication.
Commit receipts must extend the reviewed HEAD and preserve the accepted content.
Readiness requires that same accepted content and a current publication receipt.

## Interruption and resumption

```sh
python3 "/absolute/plugin/scripts/development_run.py" interrupt "/private/run" \
  --revision 4 --reason "Worker result unavailable"
python3 "/absolute/plugin/scripts/development_run.py" retire "/private/run" \
  --revision 5 --reason "Reconciled partial effects" \
  --shutdown-evidence "Native host confirms the assigned worker and its processes exited"
python3 "/absolute/plugin/scripts/development_run.py" resume "/private/run" \
  --revision 6 --reason "Ready to retry within remaining allowances"
```

Use actual current revisions. Prefer collecting a finished report to retiring
it. `retire` records supplied shutdown evidence; it does not stop or verify a
native process. The caller must do that first. Reconcile real Git and remote
state before retrying an operation whose response was lost. Never automatically
repeat a commit, push, or PR creation.

If accepted code drifts within the approved paths, use `reconcile` with `--pr`,
`--revision`, and `--reason` after collecting or retiring the outstanding worker.
It schedules another review without reverting files, changing the original
comparison base, or refunding attempts. Drift outside approved paths requires
an explicit scope decision, not an automatic rollback or wider fix.

Snapshots inherit the existing review helper's boundaries: tracked and
non-ignored untracked files, excluding `.review-loop/`. Symlink targets are
recorded as text, not followed. Ignored inputs, external systems, submodules,
and special files need explicit limitations or a separately supported approach.

Questions and guidance-checker failures do not change run state. Explicit
cancellation interrupts scheduling and separately stops all owned native
workers/processes. Report anything that could not be stopped. Status,
interruption, and retirement remain available when the feature is disabled;
no permission is granted and unrelated work remains available.
