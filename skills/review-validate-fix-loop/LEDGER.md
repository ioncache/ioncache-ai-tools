# Ledger protocol

Resolve `../../scripts/review_ledger.py` relative to the skill directory.
Run from the consuming worktree. All helper results are JSON on stdout;
errors use stderr and exit 2. Use actual absolute paths, quoted in the shell.

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
| `stop` | `outcome` | Stop as `blocked`, `interrupted`, `failed`, or `stalled`. |
| `resume` | None | Reopen a blocked/interrupted run without changing allowances. |
| `reconcile` | `evidence` | Invalidate evidence after external edits outside a fixing phase. |

`locations`, `evidence`, `findings`, and `files` are non-empty string arrays.
File declarations are exact paths, not globs. `severity` is `High`, `Medium`,
or `Low`. A finding key describes the underlying cause and affected behavior,
not a changing line number. Reuse it only for the same issue.

Validation values are `valid`, `invalid`, and `uncertain`; newly discovered
findings start `pending`. Disposition decisions accept `open`, `ignored`,
`out_of_scope`, `fixed`, and `fix_failed`. `fix_done` sets `fix_applied`
automatically. Preserve truth separately from disposition; explain accepted
uncertainty and residual risk in the reason/evidence.

`fixed` requires an applied correction in the current cycle, passing checks,
and completed review-fixes. Resolve every `fix_applied` before `advance`.
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
