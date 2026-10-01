# Review-validate-fix loop: design

This design records the agreed workflow and ledger contract for
a `review-validate-fix-loop` skill, based on the discussion on 2026-09-30.
Phase 1 has a skill and helper implementation in this checkout; Phase 2
and optional enhancements remain future work. Scope and completion criteria
are grouped under [Delivery phases](#delivery-phases).

Related: [Roadmap](ROADMAP.md#review-workflow) and the existing
[`review-code` skill](../skills/review-code/SKILL.md).

## Purpose

Review a defined body of code, validate the findings, fix actionable issues,
and repeat until the review finds no remaining issues requiring action or a
limit prevents further work. Track the work outside conversation context so
it survives interruption, supports resumption, and produces useful reports.

The intended capabilities are:

- Reuse `review-code` rather than maintain a second review methodology.
- Delegate independent review work to subagents.
- Make review and remediation decisions autonomously, recording every
  decision and its justification.
- Require a durable `REVIEW_LEDGER` of findings, evidence, decisions,
  fix attempts, verification, and run progress.
- Bound both full review loops and their nested fix/review-fixes cycles.
- Accept invocation parameters rather than require permanent configuration.
- Add actual cost budgeting after the initial loop-count controls.

Success means no remaining actionable findings were detected within the
declared scope and effort, with required verification completed. It is not
a claim that the code is bug-free.

## Delivery phases

Phase 1 and Phase 2 are committed scope. The optional enhancements are
recorded separately and are not promises to implement every idea discussed.
Phase 2 choices do not block Phase 1.

### Phase 1: Initial implementation

#### Initial scope

Deliver the autonomous review loop, reviewer subagents, nested fix cycles,
finite outer and inner limits, mandatory ledger, resumption, invocation
arguments, and intermediate and final reports. Upgrade `review-code`
while preserving its standalone read-only use.

A small ledger helper is recommended to validate and persist the record
reliably. There are no per-phase effort or model options. Respect existing
harness and agent settings. Loop counts must not be presented as token or
spending limits.

The workflow, ledger, and termination contracts below define this phase.
Cost-budget requirements and optional enhancements are outside its scope.

#### Initial implementation choices

The implementation uses the following choices:

- Invocation accepts a target, `--max-loops` and `--max-fix-cycles` (both
  default to 3), or `--resume` with an existing ledger path. Invalid options
  are reported rather than ignored. No persistent configuration is added.
- With no target, review the active PR or current branch changes against a
  pinned merge-base, including local edits. If no local default-branch ref
  exists, explicitly narrow to changes since `HEAD`; lookup errors must
  not be mistaken for absent references.
- `scripts/review_ledger.py` provides `init`, `apply`, `status`, and `diff`.
  Events go through stdin with an expected revision. Schema version 1 stores
  run metadata, snapshots, and ordered events; `review_loop_state.py` derives
  current state by replay rather than maintaining a second editable summary.
- Snapshot manifests reference content-addressed files under each run's
  `objects/` directory. They include Git-enumerated tracked and non-ignored
  untracked files, modes, HEAD, and index metadata. Ignore `.review-loop/`
  bookkeeping. Do not dereference symlinks or overwrite worktree files.
- Updates use a per-worktree file lock and atomic replacement. One running
  or resumable run is allowed per worktree; concurrent code work needs
  isolated worktrees. Revision checks reject stale coordinator updates.
- Run artifacts are retained locally, never automatically committed or
  uploaded. The helper creates private-by-default storage without modifying
  consuming projects' ignore files.
- The coordinator uses native read-only agents for substantial independent
  passes, retains integration review, and uses one code writer. No model or
  effort overrides are supplied.

The [workflow reference](../skills/review-validate-fix-loop/WORKFLOW.md) and
[ledger protocol](../skills/review-validate-fix-loop/LEDGER.md) document the
executable contract. These choices are not runtime questions for the user.
Host-specific wiring follows the
[implementation boundary](#cross-harness-implementation-boundary).

#### Initial completion criteria

- The nested workflow runs without routine user decision gates and obeys
  the [termination rules](#termination-and-loop-limits), including stopping
  the entire run on inner exhaustion with actionable issues remaining.
- The ledger preserves decisions, evidence, counters, and code references
  across interruption and resumption. Distinct runs have isolated ledgers,
  even within one session; resuming a run in another session preserves its
  ledger. Reports distinguish completion, accepted exceptions, and
  incomplete work.
- Invocation behavior and defaults are documented, standalone review
  remains read-only, and the
  [Phase 1 evaluation scenarios](#phase-1-evaluation) are exercised.

### Phase 2: Required follow-up

#### Cost-budget scope

Add actual cost budgeting to the existing loop-count controls. Include
run-level usage attribution, accounting across resumes, handling of
missing or delayed measurements, and capacity reserved for verification
and reporting. Preserve the Phase 1 workflow and ledger history.

This is required follow-up work, not an optional enhancement. The
[cost-budget requirements](#cost-budget-requirements) define its behavior.
Separate token-count limits are optional and are not required by this phase.

#### Cost-budget implementation choices

- Measurement providers and suitable native controls for each harness.
- Supported monetary units, pricing sources, attribution boundaries, and
  whether particular providers require a dedicated session.
- Invocation parameters for budgets, accounting-failure behavior,
  verification/reporting reserves, and handling of concurrent in-flight work.
- Usage records and report fields, including uncertainty and the distinction
  between estimated cost and actual charges.

Resolve these choices during Phase 2 without introducing mid-run user
decision gates. Selecting a backend or reserve policy is not a prerequisite
for shipping Phase 1.

#### Cost-budget completion criteria

- Measurements identify their source, units, freshness, and coverage.
  Run accounting includes coordinator and worker work without double
  counting and preserves consumption across resumes.
- Exhaustion and unavailable accounting follow the documented policy
  autonomously, preserve the ledger, and leave incomplete work visible.
  Reported guarantees match the implemented budget mechanism.
- The [Phase 2 evaluation scenarios](#phase-2-evaluation) are exercised.
  Loop-count-only operation remains available without a usage provider.

### Deferred optional enhancements

These are candidates, not a committed third phase or prerequisites for
either committed phase:

| Enhancement | Possible scope |
| --- | --- |
| Per-phase effort controls | Separate reasoning-effort choices for review, validation, fixing, and review-fixes. |
| Per-phase model controls | Optional model overrides for individual phases. |
| Token limits | Token-consumption caps in addition to monetary and loop-count budgets. |
| Parallel fixing | Isolated concurrent corrections with an explicit integration policy. |
| Narrow enforcement hooks | Mechanical guards against accidental writes or other invalid phase actions. |
| Stricter external runner | Ownership of launches, transitions, counters, and cancellation for stronger enforcement. |

If an enhancement is selected, define its implementation choices and
completion criteria separately. Do not silently expand Phase 1 or Phase 2
to include it. The [enforcement approach](#enforcement-approach) describes
the limits of hooks and runners.

## Scope and authority

The caller selects a PR, branch change, set of files, or repository-wide
review. The coordinator records that scope and the change's objective
before reviewing. Reading related code to understand a finding does not
automatically authorize editing that code.

Invoking the loop authorizes autonomous, in-scope review and remediation.
The agent decides validity, severity, fix suitability, and whether to
ignore or abandon a finding. It must record every decision and why it was
made. The loop does not pause to ask the user for these decisions.

Invoking `review-code` alone remains read-only. The loop does not
implicitly authorize commits, pushes, PR comments, thread resolution,
deployment, or unrelated refactoring.

Autonomy does not override existing tool permissions. If a required
operation is unavailable or prohibited, record the limitation and stop
the affected work. Do not bypass permissions or create a workflow that
repeatedly asks the user to make review decisions.

Preserve pre-existing working-tree changes. Identify the initial review
baseline and each reviewed working-tree snapshot, including relevant
uncommitted, untracked, and deleted files. A snapshot need not be a commit.
Do not push between rounds merely to update the PR diff.

If another actor changes the reviewed code during a phase, reconcile the
change before applying findings or claiming verification. Evidence from an
older snapshot is not automatically valid for the new one.

## Relationship to review-code

The existing skill provides project-standard passes, call-site contract
checks, a correctness pass, and a consolidated findings table. The loop
should reuse these review criteria and keep standalone review useful.

The proposed upgrade to `review-code` would:

- Allow independent passes to run in subagents, then consolidate their
  findings. All reviewers receive the same objective, standards, and code
  snapshot. Retain a cross-cutting review of interactions between areas.
- Accept an explicit local snapshot and baseline instead of repeatedly
  fetching a remote PR that does not include the loop's local fixes.
- Distinguish change reviews from repository-wide reviews. Whether a
  finding predates a change affects scope, not whether the finding is true.
- Replace the promise of an exhaustive single pass with explicit coverage
  and limitations. Finding an issue in a later pass is not grounds to hide it.
- Preserve separate standards passes without requiring that independent
  passes execute sequentially.

These changes are part of the Phase 1 `review-code` upgrade. Its report IDs
identify findings within a pass; the ledger maintains stable run-scoped
identities across passes and rounds.

## Workflow

An outer loop consists of review, validation, fixing, and reviewing fixes.
Fixing and reviewing fixes form a nested sub-loop:

```text
Full review -> Validate -> Fix -> Review fixes
                           ^          |
                           |          +-- Actionable issues: validate
                           +-------------- and fix within this sub-loop
                                      |
                                      +-- No remaining actionable issues:
                                          next full review
```

Establish scope, effective invocation parameters, the ledger, and the
baseline before starting the first outer loop.

1. Review the current snapshot across the agreed scope using the applicable
   `review-code` passes. Collect all assigned results before fixing.
   Failed or incomplete review work is not an empty successful review.
2. Validate candidate findings and reconcile them with existing ledger
   entries. The agent records the disposition and reasoning for each.
3. Fix actionable findings and run relevant checks. Associate changes
   and attempts with their findings.
4. Review the fixes. Validate new findings within this sub-loop and return
   directly to fixing while actionable issues remain and capacity remains.
   Do not restart the full review merely because a correction needs work.
5. When the fix sub-loop has no remaining actionable issues, return to a
   full review if outer-loop capacity remains.

If full review and validation require no corrections, record fixing and
reviewing fixes as unnecessary. That outer loop can provide final
confirmation, subject to the [completion criteria](#termination-and-loop-limits).
If corrections were made, final full-scope confirmation uses another
outer loop and consumes its allowance.

Reaching the inner limit with actionable issues remaining stops the
entire run. It must not advance to another outer review. The detailed
counting and exit rules are under
[Termination and loop limits](#termination-and-loop-limits).

Validation of review-fixes findings belongs to the current cycle and
precedes its exit decision. A failed review or unfinished validation does
not satisfy the condition for returning to full review.

The coordinator checkpoints the ledger at phase boundaries and records
work as it progresses, not only in its final response.

### Finding validation

Keep three judgments separate: whether the finding is real, whether it is
in scope, and whether the proposed correction is appropriate and authorized.

For a correctness finding, identify the reachable behavior, triggering
conditions, expected result, and supporting evidence. A reproduction or
regression check is preferable when practical. For documentation and
standards findings, use the applicable requirement and caller-facing
contract; an executable failing test is not always the right evidence.

Documentation covers usage, use cases, examples, contracts, and business
rules. Readable implementation does not remove those needs. Neither a
coverage percentage nor an unsupported label such as "boilerplate" is
sufficient to accept or reject a documentation finding.

A separate validator should challenge the finding rather than repeat the
reviewer's explanation. Agent agreement, even across different models,
does not establish validity. Uncertain requirements are not an invitation
to invent intent or to pause for a user decision.

Investigate uncertainty within the available allowance. If the agent
decides not to change the code, record the unresolved evidence, residual
risk, and reason for that decision. Continue independent work, but do
not present accepted uncertainty as a disproven finding or a clean result.
Difficulty alone is not a reason to mark a valid finding invalid.

### Fixing and focused post-fix review

Use minimal corrections that preserve intended behavior. Do not weaken
tests or change requirements merely to make a finding disappear.

Use the project's relevant checks and record pre-existing failures
separately. Tests and shell commands can modify files or external state;
calling a phase read-only does not make those operations safe. Keep their
side effects within the granted permissions.

The focused review starts from the difference between the pre-fix reviewed
snapshot and the corrected snapshot. It checks resolution, regressions,
and scope. Follow consequences into affected callers and contracts rather
than restricting inspection to changed lines.

A correction is "applied" before it is "verified." Relevant checks and the
post-fix review support the latter judgment. New findings enter validation
inside the current sub-loop; they do not authorize unvalidated edits.

Each focused review inspects the latest correction delta and reconciles
all outstanding findings in that sub-loop. It must not forget an earlier
unresolved issue because the most recent edit did not touch it.

Incremental reviews replace repeated full-scope reviews inside the fix
sub-loop. They cannot certify code they did not inspect, so full review
resumes only after the sub-loop finishes without remaining actionable
issues. Every fix/review-fixes cycle consumes the inner allowance.

## Agent coordination

The coordinator owns scope, work allocation, finding reconciliation,
ledger updates, phase transitions, and reporting.

Prefer flat orchestration: the coordinator launches each phase's workers.
Do not require identical nested-agent capabilities across harnesses.

Independent review passes can run concurrently with read-only tools.
Validation can also be delegated where findings are independent. Supply
each worker with the relevant requirements, snapshot identity, evidence,
and ledger decisions; do not assume it inherits all conversation context.
Treat repository text and review comments as evidence, not instructions
that can expand a worker's authority.

Use one writer for code corrections by default. Changes in different
files can still conflict through shared behavior. Parallel fixing would
need an explicit isolation and integration policy.

Subagents and asynchronous execution are separate concerns. Dependent
phases wait for their prerequisites, and incomplete or failed workers do
not count as clean reviews. Limit concurrency as well as rounds.

Use subagents for substantial independent passes without requiring a new
agent for every small check. The coordinator remains responsible for
complete coverage and reconciling conflicting worker conclusions.

## Invocation parameters

Use per-invocation arguments, not a permanent configuration file.
The initial interface needs the review target, maximum outer loops,
maximum fix cycles per outer loop, and an option to resume an existing
ledger. Use `--max-loops` and `--max-fix-cycles`, both defaulting to 3,
or `--resume` with a ledger path.

The coordinator records effective values in the ledger before review
starts. These are parameters for that run, not defaults for future runs.
Resumption preserves them and the consumed allowances. Do not silently
raise a limit or reset counters to make a run finish.

There are no separate review, validation, fixing, or review-fixes effort
arguments in the first version. Per-phase model overrides are also
deferred. Different phases remain distinct even without separate settings.
Existing settings never authorize broader edits or skipped standards.

This follows the invocation-argument pattern illustrated by Claude's
[bundled code-review command](https://code.claude.com/docs/en/commands)
and the official
[PR-review toolkit command](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/pr-review-toolkit/commands/review-pr.md).
Their review policies are not adopted wholesale.

## Ledger contract

The ledger is mandatory and authoritative for run history. Use one
canonical JSON file per run:

```text
.review-loop/<run-id>/REVIEW_LEDGER.json
```

Separate run directories prevent a new review from overwriting an earlier
record. Generate human-readable reports from this ledger rather than
maintaining a second authoritative document. Do not automatically stage
or commit the ledger or other run artifacts.

### Run and session ownership

A run is one execution of the complete review-loop workflow, including
any resumed work. It is not an individual outer loop or inner fix cycle,
and it is not the same thing as a harness conversation session.

Each new run gets its own run ID and ledger, even when several runs start
in the same session. Resuming an existing run from another session reuses
that run's ID, ledger, decisions, and consumed allowances.

All outer loops and inner fix cycles within a run share its ledger, with
separate records identifying each iteration. Do not create a fresh ledger
for every iteration or use one repository-wide or session-wide ledger for
unrelated runs. This preserves finding history within a run without
silently carrying suppression decisions into a different run.

### Records

The contract includes these records, stored in event history and exposed
as current state by `status`:

| Area | Information |
| --- | --- |
| Run | Schema version, run ID, objective, scope, initial baseline, effective parameters, current phase, record revision, and outcome. |
| Outer loop | Number, reviewed snapshot, assigned passes and workers, coverage, phase results, and started/completed state. |
| Fix cycle | Parent outer-loop number, cycle number, findings being corrected, before/after snapshots, verification, and review-fixes result. |
| Finding | Stable ID, originating loop or cycle, affected behavior and locations, severity, evidence, validation, disposition, and related findings. |
| Decision | Agent, loop/cycle and phase, decision, justification, evidence references, and previous state when a judgment changes. |
| Fix attempt | Finding IDs, files changed, correction attempted, outcome, and failure reason where applicable. |
| Verification | Checks and review results tied to a snapshot, including failures, skipped checks, and inconclusive or unavailable evidence. |
| Usage | Future measurement records with source, units, attribution, consumption, and uncertainty; initially not collected, never implied to be zero. |

Loop and cycle records distinguish started from completed work. Starting
an operation consumes its count even if it later fails or is interrupted.
Snapshots include relevant working-tree changes rather than relying on
the current commit alone. Content-addressed objects preserve correction
deltas without requiring a commit or push.

### Finding states

Keep validation and disposition separate:

| Dimension | States |
| --- | --- |
| Validation | `pending`, `valid`, `invalid`, `uncertain` |
| Disposition | `open`, `ignored`, `out_of_scope`, `fix_applied`, `fix_failed`, `fixed` |

Validation, severity, and disposition are independent. A real issue may
be intentionally accepted or outside scope. A failed fix is not an invalid
finding. Do not label an applied edit as verified merely because the
fixing agent says it is complete.

Pending validation and open or failed required fixes cannot disappear
from completion checks. An uncertain finding may be deliberately left
unfixed, but must retain its uncertainty and recorded risk.

Mark a finding `fix_applied` when the correction is written. Mark it
`fixed` only after relevant verification and review-fixes support that
judgment. A failed attempt records `fix_failed` and remains actionable
unless the agent makes a separate, justified disposition decision.

### Identity, suppression, and decision history

Assign stable IDs such as `F001`. Identify duplicates by the underlying
issue, cause, and affected behavior, not only line numbers or wording.
Attach repeated observations to the existing entry. Reopen a recurring
issue by returning it to an actionable state and recording why.
Finding IDs are scoped to their run; `F001` in a different run is a
different record.

Feed relevant ledger history into subsequent rounds. Suppress repeat
reporting of an ignored finding while its rationale still applies.
If code or evidence invalidates that rationale, reopen the entry explicitly.
The ledger must not become a permanent blind spot.

Record every substantive decision, including validation, severity,
suppression, correction choice, failed attempts, accepted risks, reopening,
and stopping. Retain the deciding agent, evidence, and justification.
Preserve earlier decisions when conclusions change. Reaching a limit
must not itself turn a finding into `ignored`, `invalid`, or `fixed`.

### Persistence and resumption

Only the coordinator writes the ledger; workers return evidence and
recommendations. A small helper should validate required fields, reasons,
state transitions, and counters, and preserve a complete valid record
across interrupted writes. Update the current state and decision history
together rather than allowing them to diverge.

Record intent before mutating code and the result afterward. If a write
or ledger update is interrupted, the next invocation reconciles actual
files with the last durable checkpoint before continuing.

If an existing record is missing, malformed, or inconsistent, report the
condition instead of silently starting a replacement run or reconstructing
success from memory. Never overwrite another run's record.

Keep evidence relevant and avoid copying credentials or sensitive payloads
into the ledger. Persistence and version-control policy must account for
the information a consuming project's reviews can expose.

On resumption, reconcile recorded work with actual files and verification
evidence. Carry forward counters and any usage for the same run. Continue
the recorded loop and cycle without granting a fresh allowance. Do not
reset limits merely because context was compacted or a session was resumed.
Exclude ledger and snapshot bookkeeping from the code-review diff.

## Termination and loop limits

"No new issues" alone is not a sufficient stopping condition. An unresolved
finding may recur without being new, and a failed reviewer may return no
findings at all.

### Counting

An outer loop counts when its full review starts. An inner cycle counts
when its fixing phase starts and includes verification and review-fixes.
Both limits are finite positive counts. Failure or interruption does not
refund a count; resuming unfinished work does not start a new count.
Persist each increment before launching the corresponding phase.

The inner maximum applies per outer loop. A new inner allowance is
available only after the previous sub-loop has finished without remaining
actionable issues and a new full review finds work to correct.

| Condition | Transition |
| --- | --- |
| Review-fixes leaves actionable issues and inner capacity remains | Validate the findings and return to fixing within the same outer loop. |
| Review-fixes leaves actionable issues and the inner limit is reached | Stop the entire run as incomplete. Do not start another outer review. |
| Review-fixes leaves no actionable issues and outer capacity remains | Start the next full review. |
| Fixes are reviewed, but no outer capacity remains for final full review | Stop with final full-scope confirmation incomplete. |
| Full review and validation require no further edits or pending work | Complete, subject to the evidence and exception rules below. |

Stop the whole run on inner exhaustion even if unused outer loops remain.
This prevents restarting the outer loop to reset the fix allowance.
Do not automatically increase limits or relax acceptance criteria.

### Completion and other outcomes

Completion requires a completed full review of the latest agreed scope,
required verification results, and no pending validation or actionable
findings. A final no-edit outer loop provides full-scope confirmation
after corrections. Fixing and review-fixes are then recorded as unnecessary.

Keep these outcomes distinct:

| Outcome | Meaning |
| --- | --- |
| Completed | Required coverage and verification finished, with no remaining actionable findings or accepted unresolved issues. |
| Completed with exceptions | Required work finished, but the agent deliberately accepted valid or uncertain issues and recorded the reasons and risks. |
| Limit reached | An inner or outer allowance was exhausted with unresolved work or final confirmation incomplete. |
| Stalled | Findings recur or corrections oscillate without useful progress. |
| Blocked | A required operation, dependency, or verification is unavailable; this is not a pause for a review-policy decision. |
| Interrupted | The user or environment interrupted the run. |
| Failed | The workflow or required evidence could not be completed reliably. |

An unresolved finding does not become invalid because it is inconvenient
or because a limit expired. All accepted issues and coverage limitations
remain visible in the final report.

## Cost-budget requirements

These requirements apply to
[Phase 2: Required follow-up](#phase-2-required-follow-up), not the initial
implementation. Optional token limits are tracked separately under
[Deferred optional enhancements](#deferred-optional-enhancements).

Prefer suitable native usage and budget controls. `ccusage` is a possible
measurement backend, not a required dependency or an enforcement boundary.
Selecting providers and mapping their outputs belongs to implementation.
The ledger contract must accommodate usage without pretending that the
first release measures or limits spending.

### Attribution and units

Record the accounting baseline before the run. Count coordinator work and
all review, validation, fixing, and post-fix agents. Avoid double-counting
subagents when a parent total already includes them.

Session-total differences identify run usage only when unrelated work is
not mixed into the same window. A dedicated session simplifies attribution,
but whether to require one is undecided.

Preserve distinctions between cumulative token usage, estimated USD,
native billing credits, and actual charges. Token consumption is not
current context-window occupancy. Mixed-model estimates require the
applicable pricing and correct treatment of cache and reasoning categories.
Do not add categories that a provider already includes in another total.

Record source, freshness, units, and completeness. Unknown usage or missing
pricing is not zero. Phase-level breakdowns should be reported only when
the source supports that attribution.

### Budget behavior

Check consumption between phases and before launching more agents.
Reserve capacity for verification and reporting. When a configured limit
is exhausted, stop launching work, preserve progress, and report what
remains. Do not silently downgrade models or effort to stretch the budget.

Parallel work and delayed accounting can overshoot checkpoint-based
limits. Distinguish a measured soft budget from a host-enforced limit;
neither should be described as an exact billing ceiling without evidence.
The response to unavailable accounting is a
[Phase 2 implementation choice](#cost-budget-implementation-choices).

The ledger must retain the same run's cumulative consumption across
resumes, independently of any accounting window in the selected backend.

## Enforcement approach

The recommended initial approach is best-effort skill orchestration,
validated ledger checkpoints, normal harness permissions, and loop-count
controls. This is not a universal hard enforcement boundary.

A small helper can enforce ledger structure, required decision reasons,
counter updates, and allowed transitions. It cannot prove that a review
happened or force an agent to use the helper.

Narrow hooks might later catch accidental writes in a review phase.
They cannot establish finding validity or guarantee the complete workflow,
and their permissions and failure behavior require host-specific checks.
Do not use a Stop hook to force continuation until every finding is fixed.
Stopping with unresolved findings is legitimate.

Autonomous decision-making does not require a strict external runner.
If stronger mechanical workflow guarantees become necessary, a runner must
own agent launches, phase permissions, counters, and cancellation. Reuse
native controls where they already supply the required behavior rather
than rebuilding them. This runner is not part of the first release.

## Cross-harness implementation boundary

The supported harnesses must provide the same observable workflow,
ledger, autonomous decision policy, and honest completion outcomes.
Agent-launch mechanisms, permission mappings, argument transport, and
eventual usage adapters are implementation details, not separate design
decisions or prerequisites for agreeing on this workflow.

The implementation handles missing capabilities explicitly without
bypassing permissions or claiming work was performed when it was not.

Phase 1 uses shared skill instructions and native host delegation, not a
new per-host runner or hook. Automated fixtures exercise the helper and
persisted workflow; they are not certification of complete interactive
conversations across all supported hosts.

Snapshot limitations are explicit: ignored files and external systems
are not captured; Git-enumerated special files and submodules are unsupported.
Fix declarations reject symlink paths. Unexpected changes outside declared
files or to HEAD/index stop correction recording. Read-only-phase drift
invalidates earlier judgments and requires another counted full review.

## Reporting

Generate reports between outer loops, between fix cycles, and at the end
from the ledger, reconciled with the latest code and verification evidence.
Report findings by severity and disposition, changes attempted, verified
resolutions, accepted exceptions, failed fixes, outstanding uncertainty,
coverage, and both loop counters.
Report consumption only when it is actually measured.

Keep recurring findings separate from newly discovered ones. State why the
run stopped and which checks or reviews were incomplete. Do not report
zero unresolved issues merely because a budget expired or a worker failed.

## Evaluation by phase

### Phase 1 evaluation

Start evaluation on a bounded change where a person can inspect the
outcome without providing routine mid-run decisions. Evaluate at least
these scenarios before adopting the initial implementation:

`python3 scripts/review_ledger_self_check.py` exercises the mechanical
contracts in isolated repositories, including a failing executable boundary
case corrected before verification. Agent review quality still requires
supervised use; fixture-supplied review reports do not prove semantic quality.

- A valid finding is corrected and verified; an unsupported finding is
  rejected with evidence rather than a subjective dismissal.
- An ignored finding is not repeatedly reported, but is reopened when
  new evidence invalidates its rationale.
- A correction introduces a regression in an unchanged caller, which
  the focused review detects and returns to fixing in the same outer loop.
- An inner limit is reached with actionable issues remaining. The entire
  run stops even though unused outer loops remain.
- The final permitted inner cycle resolves its issues. Another full
  review is allowed only if outer capacity remains.
- Outer capacity runs out after corrections, and missing final full-scope
  confirmation is reported rather than treated as success.
- A full review requires no corrections, so unnecessary fix phases are
  skipped and no inner cycles are consumed.
- The agent accepts a valid or uncertain finding without asking the user,
  preserves its justification, and reports completion with exceptions.
- Two passes report the same issue, or successive fixes oscillate.
- A worker fails or returns partial results without making the run appear
  clean.
- Interruption and resumption preserve ledger history and remaining
  limits, while detecting external changes to the code.
- Two distinct runs in one session have separate ledgers and do not
  inherit each other's suppression decisions.
- Resuming a run in another session reuses its ledger and allowances;
  advancing outer loops or inner cycles never creates a replacement ledger.
- A run preserves user edits and never requires committing or pushing
  merely to advance to another round.

### Phase 2 evaluation

In addition to preserving Phase 1 behavior, evaluate:

- Coordinator and subagent consumption is attributed to the run without
  counting the same usage twice.
- Delayed or missing usage follows the selected accounting-failure policy
  without presenting unknown consumption as zero.
- Resumption preserves cumulative consumption even when a provider starts
  a new accounting window.
- Concurrent work and budget exhaustion stop new work as specified,
  preserve recorded decisions, and disclose overshoot or incomplete work.
- Verification and reporting reserves follow the documented policy
  without silently spending past the configured stopping conditions.
- Reports distinguish estimated monetary cost, actual charges where
  available, and other usage units rather than treating them as equivalent.
- The initial loop-count workflow still works when cost budgeting is not
  enabled and no usage provider is available.
