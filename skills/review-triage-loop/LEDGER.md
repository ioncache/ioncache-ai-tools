# Durable discovery ledger

## Storage and ownership

Use a unique run directory under
`~/.local/state/ioncache-ai-tools/review-triage-loop/` by default, outside the
reviewed tree and outside temporary or session scratchpad storage. If that
location is within the target or unavailable, resolve another durable private
location before starting. Record its absolute path.

Use owner-only access for the directory and files. Only the coordinator writes
them. Keep one coordinator per run; do not let simultaneous sessions update
the same ledger. Do not follow symlinked storage paths, overwrite another run,
change project ignore files, commit artifacts, or upload them. They may contain
private project evidence. Retain them until the user explicitly removes them.

Each run contains `REVIEW_LEDGER.md` and one `round-NNN.md` per started round.
The ledger is the canonical record of assessments and progress. Round files
preserve the exact assignment and unabridged response, plus launch identity
and completion state. Never point reviewers at these files; embed only the
canonical issue inventory in their assignments.

This is a coordinator-maintained Markdown protocol. Do not use
`scripts/review_ledger.py`: that helper's remediation transitions are not this
discovery workflow. Do not fabricate fix events or mark open findings ignored
to make it accept another discovery round.

## Required ledger sections

### Run

Record protocol version `1`, unique run ID, created/updated timestamps,
absolute run path, project/worktree identity, resolved target and exclusions,
comparison base and reviewed head when applicable, and original invocation.
Record the effective total round cap, every explicit cap change, rounds
started, quiet streak, current phase, outcome, and last completed checkpoint.

Phases are preparing, reviewing, validating, and reporting. Outcomes are running,
quiet stop, round limit reached, blocked, or interrupted. A blocked or
interrupted outcome is incomplete, never a clean review.

### Inputs and evidence

Record the target file inventory and content fingerprints, including relevant
local edits and untracked files. Record missing/deleted paths explicitly.
A commit ID alone does not identify a dirty worktree. Record file types and
symlink targets; if evidence follows a symlink, fingerprint the read destination
as a supporting input too.

For each supporting local source, record its absolute path or repository and
immutable revision, content fingerprint, and cited locations. For external
sources, record URL, retrieval date, applicable version/configuration, and the
claim supported, with a saved excerpt or fingerprint when useful. Record
requirements, operational assumptions, validation commands/results, and any
missing evidence. Exclude secrets and unrelated personal data.

### Rounds

Record each round's number, launch identity, input snapshot references, round
file path, started/completed timestamps, and status: started, reviewing,
validating, complete, or incomplete. Record the current validation cursor so
an interruption does not discard already assessed candidates.

For complete rounds, record newly reportable IDs, materially updated IDs,
running unique total, and resulting quiet streak. Record candidate and duplicate
observations separately from reportable counts. Preserve failures, gaps, and
any evidence invalidation. Never count an incomplete round as quiet.

### Findings

Assign a stable `F001`-style ID to each underlying issue. Record:

- First-seen round, every observation and duplicate reference, and the first
  reportable round or resume checkpoint if any. Preserve the exact reviewer
  wording in round files.
- The underlying issue key, plain-language claim, affected locations,
  triggering conditions, expected behavior, consequence, and evidence.
- Validity, kind, reachability, risk, confidence, priority, and disposition
  from the workflow, with reasons for each assessment.
- The next worthwhile correction, investigation, or decision; what would
  settle uncertainty; dependencies and shared-correction groups.
- Each assessment change, its round/checkpoint, previous assessment, new
  assessment, and evidence. Keep rejection, suppression, acceptance, and
  reopening reasons. Do not rewrite an old decision as if it never existed.

Use observations to retain duplicate candidates without creating extra
canonical findings. Every returned candidate must map to a finding or an
explicit duplicate of one. No candidate may disappear during filtering.

### Reports and checkpoints

Record the latest completed round table, current reportable IDs, material
updates not yet communicated, coverage/verification gaps, and stop reason.
Record whether each round's report was delivered so resumption can deliver
an interrupted report without starting another review.

Keep checkpoints ordered, including evidence invalidations and quiet-streak
resets between rounds. Recompute the streak only from complete quiet rounds
after the latest reset. Record resume-only assessment changes at a dated
checkpoint, not an invented review round. Reconcile any resulting unique-count
adjustment alongside the historical round table without rewriting old rows.

Before a launch, save the consumed round and assignment. After a response,
save the full response before validation. Checkpoint each candidate's assessment.
Finalize round counts and the quiet streak only after all candidates are
processed and inputs rechecked. Checkpoint again before reporting or stopping.

Publish completed round files before ledger references to their results.
For checkpoint replacement, write a temporary file in the same private
directory, verify its completeness, then atomically replace the destination.
Re-read the saved record before treating the checkpoint as durable.
If storage fails, stop and disclose the last durable checkpoint; do not launch
more work or claim that unsaved results are resumable.

## Resume without losing or inventing work

1. Read the explicitly named ledger and its referenced round files. Verify
   protocol, run identity, target, cap, checkpoints, and candidate-to-finding
   mappings. Recompute counts and the quiet streak from round and checkpoint
   history. A missing, contradictory, or malformed record is blocked, not an
   empty run.
2. Recheck target fingerprints and pinned comparison identities before using
   old judgments. Target drift blocks continuation; never restore the target
   or silently rebase the review. Recheck supporting files and refresh mutable
   external evidence used for material conclusions or suppression decisions.
   Missing evidence is a gap, not proof that the old conclusion still holds.
3. If supporting evidence changes, preserve earlier assessments, mark affected
   conclusions stale, persist a quiet-streak reset, and revalidate before
   reusing them. If the affected set cannot be identified, treat all dependent
   conclusions as stale. Record material changes for the next report. Earlier
   quiet rounds remain historical but cannot establish a new quiet stop.
   Do not silently reuse a quiet-stop result after its evidence was invalidated.
4. Resume saved validation or reporting before launching another round. Reuse
   a complete saved reviewer response when its inputs still match. If a
   reviewer is still running and identifiable, retrieve its result; do not
   launch a duplicate. Never send another assignment to that reviewer.
5. If a launched reviewer failed or its response is unavailable, mark the
   round incomplete, retain its consumed capacity, and reset the quiet streak.
   An explicit resume may start a fresh next round if capacity remains; it
   must keep the failed coverage visible. No invisible retries or refunds.
6. Apply any explicit `--max-rounds N` as a new total cap and record old/new
   values and the invocation. Reject a cap below rounds already started.
   Without a larger cap, an exhausted run can finish saved validation/reporting
   but cannot launch another reviewer. Never reset history to gain capacity.
7. Continue under the saved scope and remaining allowance. If two valid
   consecutive quiet rounds already exist, return the saved, rechecked report
   without launching another reviewer. A larger cap alone does not require
   extra rounds. Keep unresolved material questions visible at either stop.

Round history must distinguish a previously published count from a later
evidence correction. Resumption can update current conclusions, but it cannot
erase past findings, consumed rounds, incomplete coverage, or decision reasons.
