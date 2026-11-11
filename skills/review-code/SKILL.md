---
name: review-code
description: Reviews code for correctness, security, performance, and project standards using independent review passes. Use when asked to review files, a branch, a pull request, or a repository; reports findings without applying fixes.
---

# Read-only code review

Do not edit code, apply fixes, commit, push, or post review comments. Return
findings to the caller. A coordinating review-and-fix workflow may act on
them separately; this skill remains read-only toward the reviewed tree.
The only permitted writes are assigned result files in the caller's private
scratch directory outside that tree. They never authorize code or ledger edits.

## Scope

Honor an explicit scope, local snapshot, and comparison base supplied by
the caller. Otherwise inspect the active PR and review its change; without
a PR, review branch changes plus local staged/unstaged changes against the
default branch's merge-base. State the baseline and relevant untracked files.
Do not treat a failed lookup as an empty review.

For a local review loop, inspect the current working tree and pinned base,
not a remote PR diff that omits fixes. For focused review-fixes, inspect the
supplied correction delta and affected callers, then reconcile all outstanding
findings. Reading callers does not grant permission to expand the fix scope.

Repository/file reviews can include pre-existing issues within the requested
scope. In change reviews, prioritize introduced or worsened issues. Flag
discovered pre-existing security risks separately without attributing them
to the change. Out-of-scope does not mean invalid.

## Review method

Read [CRITERIA.md](CRITERIA.md) and [CONTRACTS.md](CONTRACTS.md). They define
the shared review standards, actionability policy, human report, and evidence
handback. Apply that policy to recommendations as well as presentation.

If assigned a bounded specialist pass, perform only that pass and return its
evidence. Do not start another review or spawn agents. An assigned coordinator
or flat adjudicator follows its role in [ORCHESTRATION.md](ORCHESTRATION.md),
not this entry point again.

Otherwise the invoking agent owns scope, permissions, and the execution-mode
decision. Handle a review inline only when all required evidence fits a single
direct read and no substantial independent pass is needed. Explicit requests
for independent agents override this shortcut.

For substantial reviews, use [ORCHESTRATION.md](ORCHESTRATION.md) to launch a
dedicated coordinator in fresh context when the host can deliver all child
results to it. Otherwise the invoking agent launches and collects specialists,
then sends their result-file paths to a separate flat adjudicator. Keep continuous
call-chain investigations together. Do not create an external runner to
work around missing native capabilities.

Honor an explicit strategy. Otherwise prefer `sweep-first` when one worker can
read the whole correctness scope and risk does not require specialist-first
allocation. Use `specialists` when capacity or independent risk areas require
it. A sweep precedes targeted follow-ups; small standards checks can share a
worker. Both strategies retain integration and independent adjudication.
Use ORCHESTRATION.md's capacity and independence rules; strategy is separate
from inline, nested, or flat topology.

The invoking agent selects the coordinator/adjudicator model before launch.
The coordinator selects worker models under the shared runtime-selection
policy. Preserve configured defaults when discovery, suitability evidence,
or permission to override is unavailable. Never ship or invent a model ranking.

Reuse the caller's snapshot. For a standalone Git review, resolve
`../../scripts/review_ledger.py` relative to this installed skill and run:

```sh
python3 -B "/absolute/plugin/scripts/review_ledger.py" fingerprint
```

Run from the consuming worktree, including a subdirectory. Pass the returned
root and snapshot identity to every reviewer. Repeat after adjudication;
different identities mean incomplete review, not permission to adopt a new
target. Assign each specialist an absolute result path in private storage
outside the reviewed tree. Specialists write the complete pass record there
and return the path; the adjudicator reads the files rather than a retyped
summary. This command creates neither a ledger nor a snapshot store.

Fingerprints cover the whole worktree, so unrelated drift also invalidates
them. They exclude ignored inputs and `.review-loop/`, store symlink target
text rather than target content, and reject submodules and special files.
Non-Git or required excluded inputs need an explicit alternative identity
and coverage limitation; never present them as protected by this fingerprint.

Check the returned handback against the request, all required assignments,
and the final snapshot. Independently validate coordinator-originated
findings, investigate gaps or contradictions, and preserve rejected candidates
for a calling loop. Do not repeat completed specialist investigations merely
because their adjudicated results returned to the invoking agent.
