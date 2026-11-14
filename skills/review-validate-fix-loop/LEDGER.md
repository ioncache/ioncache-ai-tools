# Ledger protocol

Resolve `../../scripts/review_ledger.py` relative to the skill directory.
Invoke the helper by its absolute path, quoted in the shell, from any directory
within the consuming worktree. Ledger arguments can be absolute or relative to
the worktree root, never the invocation directory. All helper results are JSON
on stdout; errors use stderr and exit 2.

```bash
python3 "/installed plugin/scripts/review_ledger.py" init \
  --objective "Correct the branch's behavior" --scope "branch changes and callers" \
  --base "<resolved-commit>" --max-loops 3 --max-fix-cycles 3
python3 "/installed plugin/scripts/review_ledger.py" status \
  ".review-loop/<run-id>/REVIEW_LEDGER.json"
```

`init` returns the ledger path and revision 0. `apply` accepts one JSON event
on stdin. Supply the revision from the latest successful response. A stale
revision is rejected; inspect history before retrying rather than duplicating
an event whose response was lost.

```bash
python3 "/installed plugin/scripts/review_ledger.py" apply \
  ".review-loop/<run-id>/REVIEW_LEDGER.json" --revision 0 <<'JSON'
{"type":"start_review","actor":"coordinator","reason":"Begin all applicable standards and correctness passes"}
JSON
```

Every event requires `type`, `actor`, and a non-empty `reason`. Only the
fields below are accepted in addition to those common fields. The helper
adds `snapshot`, `sequence`, and `time`; do not supply them.

| Event | Additional fields | Use |
| --- | --- | --- |
| `start_review` | None | Begin a full review and consume one outer loop. |
| `finding` | `key`, `summary`, `locations`, `severity`, `evidence` | Add a candidate or append a duplicate observation. |
| `review_done` | `passes`, `checks` | Finish a full review and enter validation. |
| `decision` | `id`, `validation`, `disposition`, `severity`, `evidence` | Record a reasoned judgment, risk acceptance, reopening, or verified fix outcome. |
| `start_fix` | `findings`, `files` | Declare finding IDs and exact worktree-relative files; consume an inner cycle. |
| `fix_done` | `results`, `checks` | Record results for every attempted finding and enter review-fixes. |
| `fixes_reviewed` | `passes` | Finish focused review and enter inner validation. |
| `advance` | None | Finish validation, enforce limits, or finish the run. |
| `stop` | `outcome` | Stop as `blocked`, `interrupted`, `failed`, or `stalled`. A blocked/interrupted run may be abandoned as `failed` or `stalled`. |
| `resume` | None | Reopen a blocked/interrupted run without changing allowances. |
| `reconcile` | `evidence` | Invalidate evidence after drift or required coverage changes outside fixing; settle completed focused outcomes first, or retain interrupted focused outcomes for fresh full verification. |

`locations`, `evidence`, `findings`, and `files` are non-empty string arrays.
File declarations are exact paths, not globs. `severity` is `High`, `Medium`,
or `Low`. A finding key describes the underlying cause and affected behavior,
not a changing line number. Reuse it only for the same issue.

Validation values are `valid`, `invalid`, and `uncertain`; newly discovered
findings start `pending`. Disposition decisions accept `open`, `ignored`,
`out_of_scope`, `fixed`, and `fix_failed`. `fix_done` sets `fix_applied`
automatically. Preserve truth separately from disposition; explain accepted
uncertainty and residual risk in the reason/evidence.

Ordinary `fixed` verification requires an applied correction in the current
cycle, passing checks, and completed review-fixes.
In full-review `validating`, it may instead reconfirm an invalidated pending/open
finding whose latest prior decision was `valid/fixed`, after fresh full coverage
and passing current checks. The caller supplies new independent resolution
evidence; ledger bookkeeping cannot establish its truth.

When a focused plan must be retired before `fixes_reviewed`, a fresh full
review may provide first verification instead. The finding must still be
pending/open after reconciliation. Its latest retained fix cycle must be in
an invalidated loop with no completed focused review, an `applied` result,
passing fix checks, and an after snapshot equal to the current snapshot.
No decision newer than that fix result may supersede it. Current full coverage
and checks must pass, and new independent outcome evidence must establish the
resolution. The ledger checks these recorded prerequisites, not their truth.

Resolve every `fix_applied` before `advance`. Settle completed focused outcomes
before coverage-change reconciliation; do not invent focused completion to
retire an invalid open plan.
Call `advance` before starting a further fix cycle. A failed attempt remains
actionable unless separately disposed of with justification.

## Evidence shapes

Pass entries require complete coverage, not merely a worker's exit status:

```json
{"name":"correctness","worker":"reviewer-1","result":"complete","evidence":"Traced changed call paths and boundary conditions in src/parser.py"}
```

`passes` is a non-empty array of those entries. Failed/partial passes cannot
advance the workflow. Record an incomplete `stop` instead.

Check entries have this shape:

```json
{"name":"python3 -m unittest tests.test_parser","result":"passed","evidence":"All 8 cases passed against the recorded snapshot"}
```

`checks` is a non-empty array. Results are `passed`, `failed`, `unavailable`,
or `not_applicable`. The last requires an actual reason, for example a
documentation-only change with no documentation test runner. Never relabel
failed or unavailable verification as not applicable.

`results` maps every attempted finding ID to its applied/failed result:

```json
{"F001":{"result":"applied","evidence":"Preserved empty input while rejecting malformed delimiters"}}
```

Required failed checks prevent verified resolution or successful completion.
Record pre-existing failures and their relevance honestly. Add newly
introduced regressions as findings in the focused review.

## Review handback mapping

The [shared handback](../review-code/CONTRACTS.md) is not a ledger event.
Keep schema 1 and its exact event fields. The outer loop translates it:

| Handback | Event |
| --- | --- |
| Candidate, including rejected, grouped, below-threshold, or duplicate observations | `finding`; keep origin, assignment, basis, trigger, consequence, requirement, uncertainty, and recurrence references in its evidence string array. Preserve observed/inferred supporting-claim distinctions. Reuse the underlying-issue key only for the same cause. |
| Completed pass | Exactly `name`, `worker`, `result: complete`, and `evidence`. Put the assignment ID, single `review_type`, `instruction_set` identity, reviewed snapshot, effective strategy, selection record, whole-file coverage, report path, and non-blocking limitations in the evidence string. Structured data may be JSON-encoded inside that string, never added as pass fields. |
| Assessment | `decision` after `review_done` or `fixes_reviewed`; retain validator identity, reachability, confidence, priority, `report_action`, and reasoning in the reason/evidence fields. Resolve pending caller validation first. Do not add these as event fields. |
| Incomplete required work | Preserve received candidates, then `stop`; put assignment outcomes, coverage gaps, selection provenance, and diagnostics in its reason. Do not emit `review_done` or `fixes_reviewed` for partial passes. |

Keep an unobserved `report.worker` as JSON `null` in the original report.
For the ledger pass's required text `worker`, use the caller-observed native
identity when available and retain its observation source in `evidence`.
If neither side observes the identity, use `unobserved (non-identity marker)`
in that ledger field only. Preserve the original report, assignment, null caller
observation and visibility limitation in `evidence`, and identify the marker as
non-identity text. Never use the marker or assignment name as a native identity
in packets, attempt records or context-reuse checks. This mapping does not prove
independence or remove identity-visibility limitations.

Record `start_review` before the coordinator or full-review workers launch.
Prepare first and retain the complete phase plan, normalized options, frozen
source content, effective registry and replacement bounds in that event's reason.
For focused review, record `fix_done` after edits/checks to save the correction's
after snapshot and enter its review phase. Only then can `diff` return the actual
before/after delta. Prepare the complete focused plan from that delta and persist
it in `stop.reason` with outcome `interrupted`, then immediately `resume` before
launching workers. This is an internal checkpoint, not a request for human input.
It preserves the phase and allowances. Do not record another `start_review` or
defer plan persistence until `fixes_reviewed`. Checks keep their existing
`passed`, `failed`, `unavailable`, and `not_applicable` semantics.
Every required category and the separate adjudicator belong to that same
counted phase. Sweep-first changes order, not their purposes. Before recording
completion, check that each assignment used a distinct worker context and
its own purpose-specific instructions. The ledger preserves this evidence;
it does not prove isolation from different pass names alone.
Read result files and map their complete evidence, not only file paths or
grouped human-report rows. Workers never write ledger events.
Resolve any shared request references and retain the standards inventory,
source identities, and applicable selection evidence in existing evidence fields.
Retain the normalized `review_options` and explicit-choice provenance in the
first `start_review` reason and subsequent pass evidence. A resumed override
belongs in the `resume` or next phase event's reason/evidence. Requested,
selected, and observable actual models remain separate, including fallback
attempts. Configuration observations must be refreshed on resume, not treated
as lasting host authority.
Do not make replay depend on an unavailable external request file.
An orderly interruption or open-phase plan revision uses the existing
`stop.reason` for the complete latest plan, chronological attempts, active map,
available evidence and consumed allowances, then `resume`.
Restore the latest such plan, not only the initial phase record.
Unknown lost spending is not refunded. Cosmetic plugin byte changes alone do
not invalidate frozen instructions.

Before reconciliation in `validating_fixes`, settle any still-applied outcomes
with valid independent evidence and the same snapshot, authority and check
prerequisites. If those prerequisites cannot support verification, stop incomplete.
Do not invent a prior fixed decision or perform an artificial edit to escape.
Reconciliation keeps decision history, permitting the narrow full-review
reconfirmation above without another fix cycle. For a plan retired while still
`reviewing_fixes`, preserve the applied-cycle record and use the guarded first
verification route after a fresh counted full review. Old partial passes remain
partial; the new review does not retroactively certify them.
Event shapes remain schema 1;
older helpers cannot replay this newly allowed transition.
An assessment awaiting independent caller validation does not make its
completed pass partial. Record the completed passes, then resolve and record
that assessment; never use the handback's overall outcome alone to decide
whether coverage finished.

For a separately scheduled caller validator, retain its assignment, report
identity, snapshot, coverage, and assessments in decision evidence, or in the
stop reason when incomplete. Do not emit a second `review_done` or
`fixes_reviewed` for validation. Record any newly discovered candidates through
`finding`; they still require independent assessment.

Map non-reportable underlying issues to `ignored` with a reason, without falsely
marking a valid style observation invalid. Duplicate observations use the
canonical finding's key; duplication alone does not warrant an ignored decision.
Supported, in-scope `Act` findings remain `open` until corrected or explicitly
accepted. Unresolved `Decide` and
`Investigate` assessments also remain `open`, but are not eligible for a fix
until evidence and authority support a valid `Act` assessment. Preserve any
accepted uncertainty and residual risk. These are semantic coordinator
decisions; the helper does not infer them from severity or `report_action`
text in evidence.

An ignored valid style observation can produce `completed_with_exceptions`.
Preserve that bookkeeping outcome without presenting a style-only exception
as an unresolved material risk or adding it to the human findings list.

Keep a recoverable worker/capability failure resumable with `blocked`.
Use `interrupted` for interruption, `failed` for unrecoverable errors, and
`stalled` when progress is abandoned. Only blocked/interrupted runs resume.
Record available evidence without inventing successful assignments or dropping
diagnostics to shorten the human report.

The separate adjudicator validates specialist findings. The loop
checks completeness and contradictions, then records the disposition.
Adjudicator-originated findings require a fresh independent validator.
A scripted owner schedules the shared caller-validation role and records the
actual validator's identity, assessments, and evidence. Mechanical replay
validates structure and ordering, not those judgments.

## Snapshots and reports

```bash
python3 "/installed plugin/scripts/review_ledger.py" diff \
  ".review-loop/<run-id>/REVIEW_LEDGER.json" \
  --from "<cycle-before-snapshot>" --to "<cycle-after-snapshot>"
```

`diff` emits file names, modes, object references, and text deltas. Binary
content is retained in snapshot objects; lossy display is not binary review.
Inspect such files with suitable tools or report missing coverage.

The canonical schema version 1 ledger contains run metadata, limits, the
pinned comparison commit, initial snapshot, snapshot manifests, and an
ordered event history. Current state is derived by replay, not separately
hand-edited. Snapshots reference content-addressed files in the run's
`objects/` directory. They capture file modes, symlink text, HEAD, and index
metadata. No command restores them over the working tree.

`status` returns current findings with observations and decision history,
loops and cycles, outcome, history, and drift information. Use it for
intermediate/final reporting. Usage is explicitly `not_collected`.

Updates use a per-worktree lock and expected revision, followed by atomic
replacement. Only one running/resumable run is allowed in a worktree.
Another run may start after the previous one is terminal; concurrent code
changes need separate worktrees. These guards prevent common accidental
conflicts, not deliberate tampering or arbitrary external writers.
