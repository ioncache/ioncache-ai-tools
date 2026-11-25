# Manifest and run protocol

The manifest is a normalized interpretation of the human plan, not a second
source of requirements. JSON is used for deterministic validation. Approval
identifies its canonical JSON digest and every referenced artifact digest.
It is an approval record, not authentication or a native permission grant.
Explicit authorization the human already gave for this content and its
execution is recorded in `constraints` before the identity is computed: where
it was given and which permissions it names. It then needs no repeated
consent or manually transcribed hash. Content or permissions outside that
authorization need new approval; see [SKILL.md](SKILL.md) Prepare step 6.

## Manifest schema 1

All listed fields are required. Unknown fields are rejected. IDs use lowercase
letters, digits, and hyphens, beginning with a letter.

| Field | Content |
| --- | --- |
| `schema` | `1` |
| `objective` | Agreed outcome |
| `configuration.planning` | Independent `provider` and `location` strings |
| `configuration.design` | Independent `provider` and `location` strings |
| `configuration.execution` | `provider` and `environment` strings; optional `models` role map and `review_options` overrides under MODELS.md |
| `repository` | Exact `remote` name and `url`, plus `default_branch` |
| `artifacts` | Records with `id`, `role`, `source`, `snapshot`, `sha256` |
| `prs` | PR records below |
| `tasks` | Task records below |
| `limits` | Positive integer `assignments`, `attempts`, `review_loops`, `fix_cycles`, `review_dispatches` |
| `permissions` | Explicit booleans for `commit`, `push`, `create_pr`, `mark_ready`, `screenshots`; new plans also specify `publish_audit` and `create_follow_up_issues` |
| `constraints` | Non-empty list of scope, decision, risk-acceptance, model, and operational constraints |

`create_follow_up_issues` authorizes the existing `draft` and `ready` workers
to create deduplicated follow-ups under [FOLLOW_UPS.md](FOLLOW_UPS.md).
Omission means false and preserves older approval identities. Issue creation
has an independent feature opt-out and never becomes a readiness prerequisite.
Their optional `data.follow_up_issues` receipts carry URLs or unfiled reasons.
The controller carries a cumulative assessed inventory in private state and
returns `known_issues`, private `known_issues_report` and disclosure-filtered
`known_issues_pr_draft` in per-PR progress. This includes
material pre-existing, out-of-scope and deferred issues even when action is None.

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

The only packaged execution provider is `claude-workflows`, for Claude's
`ioncache-ai-tools:autonomous-development-run`. Copilot and Codex can prepare
manifests without a packaged executor. Generic `validate` returns provider
warnings separately from the manifest and its identity. Use
`validate --provider claude-workflows` before approval, and the same option on
`init` and `next`. A mismatch refuses that executor before creating a store or
reserving capacity. It never rewrites an approved provider into an alias.
Optional model fields also leave absent fields and existing identities unchanged.

Each PR contains `id`, `goal`, `branch`, `worktree`, `base`, `target`,
`dependencies`, `checks`, and `rollout`. Worktrees are distinct, non-overlapping
POSIX paths: relative paths resolve from the launch repository root, including
`../project.worktrees/feature`; absolute paths are also supported.
Respect the consuming project's location convention. Initialization resolves
and pins destinations separately from the approved manifest, rejects resolved
aliases that overlap, and keeps the store separate from every worktree.
Destinations cannot be option-like, contain control characters, occupy Git/review
metadata or contain the launch repository. Symlink retargeting is rejected on
later execution; restoring the original target recovers without changing approval.
Legacy manifests with otherwise valid option-like/control-character spellings
still validate with warnings and unchanged identities, but cannot initialize
execution. Artifact paths retain their contained relative-path rules.
Already initialized runs without destination pins retain their original
contained relative-path validation, including those legacy spellings, through
reservation and reconciliation. Their approved manifests are not rewritten.
The controller checks the prepared worktree's root, Git common directory and
owned branch. It uses new branches and worktrees, never implicit adoption.
`base` is a full commit ID. `target` is the intended PR base branch.
Owned branches cannot equal the default or target branch.

PR dependencies use **wait for human merge**, not automatic stacking or rebasing.
Preparation verifies the prerequisite PRs are actually merged and pins its
resulting base, which must descend from the approved base. Waiting PRs do not
prevent independent increments from proceeding. No force-push is permitted.

Each task contains `id`, `pr`, `goal`, `dependencies`, `artifacts`,
`checks`, `compatibility`, and `completion`. Do not predict an edit allowlist.
Legacy `paths` remain optional, validated relative-path hints, retained verbatim
to preserve approved schema-1 identities. They do not authorize or restrict edits
and are omitted from worker task descriptions. Scope comes from the approved
goal, requirements and explicit constraints; necessary discovered dependencies
and tests belong in that scope. Preserve unrelated work and HEAD/index ownership.
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

### Planning records

The human design stays authoritative. Incremental planning under
[PLANNING.md](PLANNING.md) maps into existing schema-1 fields without new
fields or changed identities:

| Planning record | Manifest location |
| --- | --- |
| Delivery recommendation and increment map | One `prs` entry per selected increment; its tasks in `tasks`; the reasoning and rejected alternatives in the design or plan snapshot |
| Ordering | Task and PR `dependencies`, kept acyclic; cross-PR task edges also need the PR edge |
| Boundary contracts | The authoritative design snapshot in each affected task's `artifacts`; producer and consumer obligations in task `compatibility`, `completion` and `checks` |
| Prerequisite evidence | Plan or design text, plus the applicable `checks`, task `completion` or `compatibility`, or PR `rollout` for operational state |
| Flag decision, rollout, rollback and cleanup | PR `rollout`, task `compatibility`, and checks for disabled and enabled paths |
| Issue decision | Planning or design artifacts and their `source`; issues are not manifest records. Each PR's linked issue and whether it may close it go in `constraints`, which the PR publishers read |
| Shared scope, decisions and accepted risks | `constraints` |
| Conditional candidates and unresolved uncertainty | The human-readable design only, until resolved |

Include in the approved snapshots every boundary contract and parent or child
issue content that tasks need; workers take scope from pinned snapshots.
Only selected, resolved work enters the executable manifest. Schema 1 has no
optional tasks or conditional edges. A later scope change follows the existing
approval process for a new plan and manifest identity; an initialized run's
approved manifest is never rewritten. The controller checks structure and
bookkeeping, not the semantic quality of these decisions.

`assignments` caps durable top-level reservations across the run. `attempts`
caps attempts at the same role/task or role/PR. Reservations consume capacity
before dispatch; missing results do not refund it. `review_dispatches` bounds
review-owner plus leaf calls per review assignment attempt. The existing review
ledger retains its own outer and inner allowances. Category replacement rounds
also remain bounded under review-code `PACKETS.md`; they are not another
dispatch allowance. Budget for the complete enabled category roster, separate
adjudication and owner calls. Do not combine purposes to fit a smaller limit.

The Python handoff helper saves `review_dispatch` in the active assignment before
owner calls and leaf batches. It retains charged slots, hashed request identities,
started reservations and handback references across interruption. The controller's
`review-checkpoint` command reads that checkpoint JSON from stdin and rejects
refunds, replaced reservations and reused slots. This accounting is independent
of optional progress monitoring; it is not acceptance evidence.

For a sizing estimate, let `C` be the enabled full roster, including project
categories and JSDoc where applicable, `L = review_loops`, and `F = fix_cycles`.
Read `review_options.py`'s effective `configuration.review_features` and
`skills/review-code/categories.json`; a prepared phase's `required` roster is
more precise. When applicability is not yet known, budget the larger roster.
A clean full round needs `C + 4` calls: reviewers, an adjudicator and three
owner calls. An independent validator adds two more.
An initial envelope is `L * ((C + 6) + F * (C + 8))`: budget full rounds,
one fixer per cycle, focused category review, assessment/validation and owner
handoffs. With `C=12`, `L=2`, `F=2`, this is 116 dispatches per review attempt.
Add room for category replacements, additional fix batches and selection
recovery. This is an estimate, not a guarantee or a silently applied limit.
Fixes also require room for subsequent full-scope confirmation in `L`.
Explain the proposed number before approval. Parallelism reduces latency, not
the number of counted calls.

These are logical execution limits, not hard token, time, or spending caps.
Host-native retries and report corrections also consume model usage. Establish
available native resource controls during preflight and disclose gaps.

## Script-owned dispatch

`development_handoff.py prepare STORE --models-file FILE` generates a complete
native script, never a model-transcribed state object. The private role map uses
MODELS.md. `--configured-models` explicitly selects native defaults; disabled
automatic model selection also leaves unspecified roles configured.
The first preparation pins executable resources, their digests, source and plugin
version in `EXECUTOR.json` and `executor/`, separate from the approved manifest.
All subsequent handoff commands use that pinned helper. No historical approval
digest or schema-1 ledger is rewritten.

`prepare` returns `action`, batch and assignment IDs, absolute `script` and
`helper` paths, and `script_sha256`. Claim the prepared batch, then launch its
generated script through the native Workflow tool without arguments. When the
host cannot read the store, pass `--launch-dir DIR` to `prepare` and `claim`:
Python writes a byte-identical, owner-only copy named for the run and batch into
that private directory, which must be outside the launch repository and planned
worktrees. The store copy stays authoritative; a changed launch copy is retained
and rewritten from it, never from a model response. The generated script carries
only the fields the template reads, and `prepare` keeps each script below the
Workflow tool's size limit by issuing only the leading reviewer requests that
fit; the rest stay queued for later batches. Owner dispatch reports are rejected
as correctable errors when one request could not launch alone. Never invoke the null-handoff
packaged template as a standalone run. Only Python reserves work, processes
review requests and evaluates development acceptance.

The durable `handoffs` map distinguishes prepared, claimed, collected,
released and reconciled batches. Each job also records entry through `start`, successful
file validation, and failed validation attempts. A claimed batch is conservatively
charged before native launch; neither claim nor a supplied shutdown declaration
independently proves native activity. A missing start/report does not prove a
worker never launched. Unknown claimed work requires reconciliation.
For roles whose effects stay in the private store or the reviewed worktree, a
repeated `start` is treated as the host's replacement for a restarted worker.
It returns `restart` and `reported` and instructs reconciliation instead of
repetition, up to five restarts per job. The helper cannot distinguish this from
an accidental second launch, so review-dependent roles with external effects
still refuse a repeated `start`.

Unclaimed preparation can be read again without another reservation. A collected
batch retains an idempotent receipt, including when the original response was lost.
`resume-prepared` requires an actual never-claimed batch and keeps its counters.
It cannot restore a retired assignment or replay a claimed dispatch.
`release` returns a claimed batch with no start receipt to the queue after the
host refused its script, recording the supplied refusal evidence. Its
reviewer reservations become unstarted and a dispatch claim is cleared, so
`prepare` reissues the same work in a new batch without another assignment.
Review continuation uses the existing one-use `resume-review` handoff; preparation
claims it mechanically and preserves its existing ledger and charged slots.

Workers call `submit --candidate FILE` or `finish` with their generated batch/job
IDs. The generated prompt names the candidate file as the result file plus
`.candidate.json`, inside the private store. Candidates stay private. The script supplies development identities,
validates full reports and pins submitted bytes. The collector reads these files
and existing controller evidence, not the workflow's reported outcome.
Relative candidate paths resolve from the private store; paths outside it and
symlinks are still refused. `check-report STORE --batch B --job N --candidate FILE`
checks the same candidate shape and role contract read-only, without accepting
work or spending corrections. Generated development prompts name exact outcomes
and required role data from the validator's definitions. The independent
`autonomous-development-report-contract` opt-out removes that added text only.
Malformed candidates and controller-rejected report content share two corrections
after the initial failure when `autonomous-development-report-correction` is
enabled. Missing reports and storage failures do not spend this allowance.
Counts persist with the batch; repeating a native invocation does not reset them
or launch repair models. A rejected submission may be corrected from existing
evidence; collected receipts remain immutable. Retrying collection reevaluates
current evidence without charging the same rejected receipt twice.
Owner receipts bind both the envelope and its referenced development report,
with matching outcomes. Older unbound owner receipts require explicit `finish`
validation before collection, not an inferred historical binding.
Final category acceptance for generated review batches compares active results
with the archived reviewer bytes identified by the controller's validated receipts.
Packet identities alone do not bind result contents. Restore altered handoff
results from those archives without repeating completed review work.
After shutdown reconciliation, `finish` can validate a started reviewer's original
file in its reconciled batch. This binds the current bytes if no receipt exists;
it cannot establish historical contents, change an existing binding, or relaunch
the reviewer. Inactive, incomplete attempts remain in history without contributing
to final coverage.
Unavailable or corrupt retained evidence requires restoration, not report
correction, and does not spend correction allowance. Legacy direct-controller
assignments without generated batches retain their existing category checks;
they do not acquire historical collection evidence.
Exhaustion keeps the evidence incomplete and does not refund a role attempt.
With `autonomous-development-report-recovery` enabled, the launcher can use
`recover-report STORE --batch B --job N --candidate FILE --evidence TEXT
--shutdown-evidence TEXT` once for an exhausted, started job in its claimed batch.
Precheck the preserved candidate and establish native shutdown first. Recovery
records the attempt before validation, keeps its evidence and candidate digest,
uses unchanged validators and requires normal collection. It never repeats work,
changes a limit or resets a counter. Failed recovery remains consumed; a validated
receipt is idempotent, not another grant to alter accepted reports.
See RECOVERY.md for exact recovery choices, executor restoration and the
coverage limits of offline checks.

`publish_audit: true` authorizes the selected worker to publish a reviewed export
to the modified repository's GitHub wiki, prepend or update its PR's row in
`Automated-Pull-Request-Audits`, and link the report, JSON and index in the PR body.
The wiki must already be initialized and writable. This does not authorize
uploading raw private evidence, changing repository settings, or creating an
audit branch in the implementation repository.
Older schema-1 manifests without this field retain their original identity and
sequence; absence means false, never retroactive publication consent.
`autonomous-development-audit` is an independent, enabled-by-default feature
setting. When disabled, scheduled audit assignments record `{"disabled": true}`
without network publication. Other development and review safeguards remain active.
See [AUDIT.md](AUDIT.md).

## Durable controller

Use `../../scripts/development_run.py` relative to the installed skill directory.
It returns JSON and never launches a model, runs an acceptance command, commits,
pushes, or invokes a hosting API. Agents execute assigned operations and supply
evidence; the controller validates bookkeeping and local Git/review invariants.
It does not prove the truth of model reports or remote-operation receipts.

Private storage contains `RUN.json`, `MANIFEST.json`, approved `inputs/`, `reports/`,
optional review `progress/`, and native `models/` observations. It must be
outside every repository and all worktrees, without either containing the
other. Initialization checks review-storage locations before creating the run.
Keep it durable for the chosen environment and do
not upload it wholesale. The code does not provision shared cloud storage.
Published state is atomic, revisions reject stale writers, and one outstanding
assignment prevents overlapping writers within the run.

```sh
python3 "/absolute/plugin/scripts/development_run.py" next "/private/run" --revision 0 \
  --provider claude-workflows
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

Every report contains `assignment`, observed `worker` identity or JSON `null`, `outcome`
(`complete`, `blocked`, or `waiting`), `summary`, non-empty `evidence`, `artifacts`
(approved ID-to-digest map), and role-specific `data`. New workers also include
`model_report`, the helper-written private observation path from MODELS.md.
Older reports without it remain valid and their model identity stays unknown.
Top-level `evidence` is a nonempty list of nonempty strings. For draft and ready
reports, `data.evidence` is a single nonempty string about the observed PR state,
alongside text `commit`, text `url`, and `state` exactly `draft` or `ready`.
A worker cannot invent a
host ID or treat an unobservable identity as verified. Preserve visibility
limitations; an explicit verified-identity requirement still needs evidence.
Keep the full report;
returning its path is not itself evidence of successful work.

Preflight records each required capability as `{"status", "evidence"}` with
status `verified`, `available`, `deferred` or `missing`, as defined in WORKERS.md.
Only unverified artifact access, a `missing` capability, or a deferred
capability that read-only evidence could establish (`native_permissions`, and
`audit_publication` when enabled) rejects a completed preflight. The handoff
helper adds verified `fresh_workers` and `result_delivery` from the collected
batch, and the controller keeps the normalized records in `capabilities`.
Legacy `true` values remain valid as `verified`. Prompts for commit, draft,
ready, evidence and audit assignments state that their approved permissions are
the human's explicit authorization for that operation.

Preflight discloses observed ambient repository instructions in evidence,
optionally listing `data.ambient_sources`. Their presence is not a capability
failure. Review workers ignore them and use only their explicit purpose-specific
ruleset. This does not require a new approval identity, a suppression setting,
or another preflight for an existing run.

Review results supply the absolute external `data.ledger` path, plus `data.plan` and `data.handoff` for
the final full phase's frozen category plan and handoff in this run's private
`reports/`. Retain complete plans and attempt history in the shared ledger as
specified by `PACKETS.md`, not just these file references.
New review assignments pin `review_storage` under
`<private-run-store>/reviews/<worktree-identity>/`. Pass it as `init --storage`.
The ledger and all snapshot objects live there, so keeping the private store
preserves the full review after worktree cleanup. Never place them inside a
repository. Legacy migration and offline inspection are defined in
`skills/review-validate-fix-loop/LEDGER.md`.

If an existing run's private store is not a valid external location,
new reviews use
`$XDG_STATE_HOME/ioncache-ai-tools/development-recovery/<run-id>/reviews/<worktree-identity>/`,
or the equivalent under `~/.local/state` when XDG state is unset. The returned
assignment pins that path. Keep both locations: original reports, history,
approval and used attempts stay in the original store and are not reset.
Historical archives use the same recovery root. If that location is also inside
a repository, set `XDG_STATE_HOME` to external storage and retry the same run.
Existing ledgers are not moved; preserve their recorded storage as well.

If the entire pinned review store is lost with no usable copy, use the ledger's
`release-ownership` procedure in `skills/review-validate-fix-loop/LEDGER.md`.
Stop the native workers first, then retain and retire the old assignment.
Release does not resume it, refund its dispatches, or authorize another attempt.
Resume the controller and reserve a counted retry only within its remaining
approved limits. When the usual store was released, new assignments use
`reviews/<assignment-id>/<worktree-identity>/` beneath the selected private or
recovery store. Existing assignments keep their pins. Reappearing old storage
does not replace the retry's history or ownership.

If storage becomes ineligible during an active review, stop its native workers
and recover the existing ledger instead of retiring the assignment:

```sh
python3 "/absolute/plugin/scripts/development_run.py" recover-review-storage "/private/run" \
  --revision 8 --ledger "/original/reviews/<worktree-identity>/<review-id>/REVIEW_LEDGER.json" \
  --reason "A repository was created around the review storage" \
  --shutdown-evidence "Native host confirms this review's workers and processes exited"
```

Use the current controller revision and original ledger path. The command
validates and copies the complete review directory into the external recovery
location above, then updates the same assignment's storage pin. Original evidence
stays untouched. Resume the returned `assignment.recovered_ledger`, not a new
ledger. Review history, revision, findings and allowances do not change; only the
controller revision advances to record the new pin and supplied recovery evidence.
Assignment identity, attempts and consumed dispatches are retained. The command
uses the existing autonomous-development opt-outs and does not stop or verify
native workers itself.

With retained dispatch accounting, recovery also arms one continuation of the
same assignment. Run `development_handoff.py prepare`: Python consumes
`review_resume_ready` through the same `claim-review` checks, restores
the running outcome and returns the existing assignment instead of reserving
another. The owner uses `resume_ledger` and the saved dispatch checkpoint.
Completed reports are inspected, not repeated. Started calls without handbacks
remain charged and incomplete until their original evidence is assessed.
New report reservations require normalized, distinct paths. Older non-normalized
reservations remain charged history; they do not prevent an owner continuation,
but their normalized paths cannot be reused. Replacement work needs a fresh
canonical path and remaining capacity.

An identical copy left by an interrupted controller save can be reused on retry.
Different destination evidence is preserved, not overwritten; choose another
external `XDG_STATE_HOME` and retry. After a lost response, read `status` first:
if the assignment already has the recovered path, continue from it. Do not copy
back into rejected storage or rewrite `RUN.json` manually.

The controller verifies the reported ledger's completion, base, current snapshot, exact allowances,
and passing named acceptance checks. It also runs the shared category-record
checker and binds the full plan to that root, base and snapshot. Missing
changed files, missing categories, missing adjudication or unresolved
applicability cannot authorize a commit. Complete-with-exceptions results remain
visible in PR progress; they are not relabeled as clean reviews.
The file inventory covers the pinned comparison base through the current
worktree, including committed changes and non-ignored untracked files.
Additional context files may be reviewed, but cannot substitute for changed files.

Task review finishes before commit. Full-PR review follows draft publication.
Approved audit publication adds `audit-initial` after `draft`, and `audit-final`
after the final commit and any UI evidence, before `ready`. These are separate
assignment keys with independent retry accounting. Final readiness requires an
accepted audit receipt for the current code commit while the feature is enabled.
Commit receipts must extend the reviewed HEAD and preserve the accepted content.
Commit accounting uses the first implementation baseline, not the latest retry.
Additions left by failed attempts must be included; unchanged setup files need
not be committed.
Readiness requires that same accepted content and a current publication receipt.
Audit receipts contain `stage`, `code_commit`, `bundle`, `wiki_commit`, `url`,
`data_url`, `index_url`, and `pr_url`. The controller checks them against the retained exported
bytes and helper receipt. The publication helper verifies GitHub's observed PR
head, the pushed wiki commit and the PR body's links. This is not independent
authentication of a hand-edited local receipt. Older branch/comment receipts
remain in history but cannot satisfy a pending wiki-publication readiness step;
reconcile for a counted review and audit.

## Durable monitoring

`watch STORE [--interval 1] [--stale-after 300]` emits flushed JSON lines when
the compact state changes. The first line is immediate. It reads durable files
only, without controller locks, configuration synchronization, Git commands,
model calls or writes. It works from any directory and remains available when
execution or progress recording is disabled. Protect its terminal output like
`status` output; it is not a public audit.

It shows the current assignment, PR positions, counted assignments, run condition,
and review-owner/leaf dispatches, reported categories and supplied loop/cycle
counts. A stopped run exposes a bounded condition and a private
`diagnostic_reference` to `RUN.json#/reason`, not the raw rejection message.
Use private `status` or the referenced record for full recovery diagnostics.
A reported leaf is not an accepted review. Polling can coalesce fast
updates; this is not a transcript stream. Worker silence, disabled recording and
missing observations must not be described as no work having happened.

Exit codes are `0` for complete, `1` for any other stopped outcome, `2` for
unavailable state/progress, and `3` for no observed advancement within the
threshold. The stored outcomes remain compatible: `completed` is displayed as
condition `complete`, assignment-exhausted `failed` as `exhausted`, and an explicit
`interrupt` retains outcome `blocked` with condition `interrupted`. Ordinary
blocked and waiting results remain distinct. Legacy states without timestamps
measure inactivity from the start of observation.

The handoff helper records advisory `started` and `reported` progress for the
job's reserved dispatch number, when progress is enabled. The owner also records
`checkpoint --loop N --cycle N` after ledger transitions. Records contain only
bounded role/category/counter metadata and timestamps, never findings, prompts
or evidence bodies. Separate dispatch files permit concurrent writers without
taking the controller lock. Progress cannot advance acceptance, refund attempts,
authorize replacement workers or change `RUN.json`.
`autonomous-development-progress: false` disables new progress writes and
instructions independently. Assignment-level watching and all safeguards remain.
Unreadable or symlinked progress reports unavailability without following it.

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

For an interrupted review with readable evidence, retain its assignment instead
of retiring it. After stopping its native workers and reconciling partial effects:

```sh
python3 "/absolute/plugin/scripts/development_run.py" resume-review "/private/run" \
  --revision 8 --ledger "/external/reviews/<worktree-identity>/<review-id>/REVIEW_LEDGER.json" \
  --reason "Continue the retained review" \
  --shutdown-evidence "Native host confirms this assignment's workers exited"
```

Then run `development_handoff.py prepare` for that store. This arms one
continuation, not an automatic retry of an unknown live worker. After a lost
claim response or another interruption, reconcile native shutdown and use the
same command again. Existing dispatch counts, reservations, report paths and
assignment identity remain unchanged. Exhausted capacity cannot launch another
owner or be reset by recovery. Relocate ineligible storage first.

Older active assignments without a dispatch checkpoint require
`--used-dispatches N --dispatch-evidence "Native history establishing charged slots"`
on `resume-review`. Include owner calls, failed calls and reserved slots; do not
infer zero from absent monitoring. The caller supplies this evidence, just as
it supplies shutdown evidence; the helper does not independently inspect a host.
Existing checkpoints cannot be replaced this way. If spending cannot be
established, retain the incomplete outcome without launching more workers.

If accepted code drifts, use `reconcile` with `--pr`,
`--revision`, and `--reason` after collecting or retiring the outstanding worker.
It schedules another review without reverting files, changing the original
comparison base, or refunding attempts. Review the actual changed-file inventory,
not a predicted path list. This does not authorize unrelated changes or rollback.
It checks available review and assignment capacity before clearing acceptance.
Exhaustion leaves the state unchanged, not a run that fails on the next reservation.

For an already accepted, unchanged patch rebased onto its target, use
`rebase-review STORE --revision N --pr ID --new-base COMMIT --reason TEXT`
at an assignment boundary instead. The enabled-by-default
`autonomous-development-rebase-review` feature requires a full new-base commit ID,
approved-base ancestry, target-ref reachability, branch ancestry and valid
retained review history. It replays the reviewed snapshot onto the new base with
`git merge-tree --write-tree` and requires exact tree equality, including binary
content, untracked files and modes, without writing the real Git index or objects.
It appends durable `review_rebases` evidence, updates the accepted checkout and
effective comparison base, and leaves the original review record and allowances
unchanged. Future coverage checks use that effective base for this exact accepted
review. An altered patch still requires counted review. Stale completed UI
evidence and final audits are scheduled again within existing allowances before
readiness; insufficient delivery capacity leaves acceptance unchanged.
Publication, audit and UI evidence checks remain bound to the actual current commit.
See RECOVERY.md for the command and verification limits.

Accepted reviews without category-coverage records or a bound file inventory
cannot authorize further commits or readiness. Use the same `reconcile` command
for a counted review with the current contract; retain prior evidence, original
bases and spent allowances.

A cached review must also retain its absolute external ledger location. Legacy
`.review-loop` references cannot identify the migrated store reliably after an
`XDG_STATE_HOME` change. Migrate any remaining legacy records, then use `reconcile`
for a counted review that records the actual storage location. Do not rewrite
the cached reference or infer a new location from current environment settings.

A released review store or explicitly failed review cannot authorize downstream
work through cached acceptance, even when the code is unchanged. Store releases,
valid abandonment records and failed stops after accepted completion are checked
before dispatch and successful handback for commit, draft, readiness, evidence and
audit assignments, and before audit export or publication. Preserve existing
commits and remote effects, stop and retire any outstanding worker, then use
`reconcile` for a counted review within the remaining allowances. Failure
reports and historical archives remain available.
The release check uses the accepted storage identity. Review closure is read
without requiring snapshot objects or comparing the pre-commit review against
the current HEAD. A retained failed stop still invalidates acceptance when its
snapshot objects are lost. Unavailable history alone is not evidence of
revocation; it does not revoke a pinned acceptance without a release or
readable invalidation record. Once observed, an explicit review closure remains
revoked in a private acceptance-specific receipt, even if its ledger later
becomes unavailable. A new counted review creates a different acceptance;
rejected operations do not refund or consume assignments.
Recorded `recover-ownership` locations are checked for release or closure of the
same review, even after ownership selects another store. Failed stop evidence
must extend the accepted history. The cached reference and its original evidence
are not rewritten.

The native adapter must claim each review-dependent assignment with
`claim-dispatch --assignment <id> --provider claude-workflows` before launch.
The helper holds the worktree ownership lock through the authority check and
durable claim write. Ledger closure and store release use that same lock.
If revocation wins, do not launch; retire the unused reservation with shutdown
evidence and reconcile. If the claim wins, dispatch has begun: later revocation
still invalidates successful handback, but does not undo native effects.
A claim consumes no extra assignment and cannot be replayed. After a lost
response, inspect native work and effects, then collect or retire the assignment
before a counted retry. Never infer a fresh launch from an existing claim.

Successful review-dependent handbacks hold that same ownership lock from
authority validation through saving acceptance and advancing the PR position,
including final readiness. Closure that wins first rejects acceptance; a saved
handback that wins first remains recorded. Report identity and structure are
validated before acquiring the lock. Blocked reports, interruption, retirement
and identical recorded-report replay do not require it.

Review-store recovery, continuation preparation and continuation claims require
the ledger's independent freshness witness. They hold the ownership lock through
the readiness or claim write. An older valid copy cannot restore spent review
allowances. Interrupted history publication or missing freshness evidence keeps
spending unavailable: close or release the affected review, retire its assignment
after shutdown, and use a counted retry. If stale history is trapped in ineligible
storage, copy its complete run directory, including objects, to unused external
`<worktree-identity>/<run-id>` storage. Use `abandon` on the copy, then
`recover-ownership` of that closed copy before retiring and retrying the assignment.
Retain the original evidence. A witnessed failed stop or abandonment revokes
cached acceptance even if its ledger or closure write was interrupted.

`status` reports missing, unreadable, or changed snapshots in `input_error`.
Status, interruption, and retirement do not require available snapshot bytes,
but still check approval and manifest integrity. Execution, acceptance, resume,
and reconciliation require valid inputs. The run owner may restore exact
approved bytes from the selected source to the declared input paths; changing
the manifest or its digests is not recovery.

Snapshots inherit the existing review helper's boundaries: tracked and
non-ignored untracked files, with no reserved `.review-loop/` exclusion. Symlink targets are
recorded as text, not followed. Ignored inputs, external systems, submodules,
and special files need explicit limitations or a separately supported approach.

Questions and guidance-checker failures do not change run state. Explicit
cancellation interrupts scheduling and separately stops all owned native
workers/processes. Report anything that could not be stopped. Status,
interruption, and retirement remain available when the feature is disabled;
no permission is granted and unrelated work remains available.
