---
name: review-code
description: Runs a read-only review of files, branches, pull requests or repositories with independent category workers. Use for an unassigned review request, not an already assigned category, adjudication or validation pass. Reports findings without applying fixes.
argument-hint: "[target] [--help] [--lead-model MODEL] [--reviewer-model MODEL] [--validator-model MODEL]"
---

# Read-only code review

Do not edit code, apply fixes, commit, push, or post review comments. Return
findings to the caller. A coordinating review-and-fix workflow may act on
them separately; this skill remains read-only toward the reviewed tree.
The caller/coordinator may write private request, option, and instruction
records; leaf workers may write only assigned result files.
All belong in private scratch outside the reviewed tree.
They never authorize code or ledger edits.

## Assigned roles

If already assigned a bounded review or validation pass, perform only that
assignment using its supplied instruction set and return its evidence.
Do not normalize another invocation, discover a new target, load the complete
review catalog, start another review, or spawn agents. An assigned coordinator
follows its role in [ORCHESTRATION.md](ORCHESTRATION.md), not this entry point.
The remaining sections are for an unassigned invocation.

## Invocation

Follow [OPTIONS.md](OPTIONS.md) before target discovery. Bare invocation runs
with defaults; `--help` displays options without a review. Explicit role model
and effort flags override defaults within host restrictions. Automatic model
selection is the default for unspecified roles, with configured-model recovery
and an independent `review-auto-model-selection` opt-out.
No mandatory form or `--non-interactive` flag is needed.

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

Every review task requires a fresh subagent with one review purpose and only
that purpose's review instructions. There is no inline or small-check exception.
Do not combine standards, reuse a worker for another purpose, or treat separate
pass records as separate contexts. This applies to full and focused reviews.

Read [CRITERIA.md](CRITERIA.md), [CONTRACTS.md](CONTRACTS.md), and
[PACKETS.md](PACKETS.md). They define the category inventory, bounded packet
preparation and evidence handback. Use [ASSESSMENT.md](ASSESSMENT.md) for
assessment and the human report. Establish the standards inventory
before allocating passes. Apply the actionability policy to recommendations
as well as presentation.

Every enabled general category and additional project purpose runs by default.
Resolve explicit language prerequisites from source evidence before dispatch;
JSDoc runs only for JavaScript scope, not TypeScript or other languages.
Missing dedicated language/framework guidance does not remove general coverage.
No automatic exclusions, suggested exclusions or category-selection question.
Same-purpose project requirements enter the owning category's packet rather
than a second competing pass. The caller records technical language facts;
workers establish remaining file-level and semantic applicability.
Writing-skill activation settings do not switch off review categories.

The caller owns scope, permissions, and the nested-versus-flat mode decision.
The caller may be an invoking agent or an explicitly approved scripted
controller, following [ORCHESTRATION.md](ORCHESTRATION.md). The caller and
coordinator schedule and collect work; neither performs review passes.
Reviewers must also be separate from implementation.

Use nested mode when a dedicated coordinator can launch and collect every
required worker, including a separate adjudicator. Otherwise the caller
launches and collects the same assignments in flat mode. Integration review
has its own specialist; it is not extra work for the coordinator or adjudicator.
Keep continuous call-chain investigations together within a single purpose.
Missing delegation leaves the review incomplete, not permission to review
inline or create an external runner.

Use the normalized `effective_strategy`: `auto` resolves to `specialists`,
without a size or risk heuristic. `sweep-first` changes order only: correctness
runs first, then the remaining preallocated review types still run separately.
Neither strategy can omit, merge, or absorb a required task. Follow
ORCHESTRATION.md's allocation rules independently of nested or flat topology.

The caller selects the lead and any caller validator before launch.
The coordinator selects workers using the same normalized options and
runtime-selection policy. Invocation permits bounded automatic selection where
the host allows it, not a bypass of host restrictions. Honor explicit choices
without second-guessing their suitability. For unspecified roles, attempt
evidence-backed selection, otherwise preserve configured defaults and explain
the limitation. Never ship or invent a model ranking.

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

Run the packet helper's structural check, then check the returned handback
against the request, required assignments, worker
identities, instruction-set identities, and final snapshot. Schedule fresh
validation for adjudicator-originated findings, gaps, or contradictions.
Preserve rejected candidates for a calling loop. Mechanical checks are not
semantic validation. Do not repeat completed specialist investigations merely
because their adjudicated results returned to the caller.
