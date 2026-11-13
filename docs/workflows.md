# Skills and workflows

Installation and basic usage: [../README.md](../README.md).
Invoke a skill directly using the host syntax in
[../README.md#invoke-a-skill](../README.md#invoke-a-skill).
Each skill's file defines its scope, inputs, and stopping conditions.

## Workflow catalog

| Skill | Purpose |
| --- | --- |
| [../skills/investigate/SKILL.md](../skills/investigate/SKILL.md) | Explain existing code without changes |
| [../skills/review-code/SKILL.md](../skills/review-code/SKILL.md) | Read-only code review |
| [../skills/review-dependabot-pr/SKILL.md](../skills/review-dependabot-pr/SKILL.md) | Review dependency updates against actual usage, including grouped and indirect dependencies |
| [../skills/verify-unresolved-pr-comments/SKILL.md](../skills/verify-unresolved-pr-comments/SKILL.md) | Triage outstanding PR feedback without changing it |
| [../skills/post-pr-review-comments/SKILL.md](../skills/post-pr-review-comments/SKILL.md) | Draft and edit PR comments in a pending review; never submit it |
| [../skills/write-pr-descriptions/SKILL.md](../skills/write-pr-descriptions/SKILL.md) | Write and edit human-focused PR titles and descriptions |
| [../skills/review-triage-loop/SKILL.md](../skills/review-triage-loop/SKILL.md) | Repeated read-only review and evidence-based triage |
| [../skills/review-validate-fix-loop/SKILL.md](../skills/review-validate-fix-loop/SKILL.md) | Review, validate, fix, and re-review within limits |
| [../skills/triage-errors/SKILL.md](../skills/triage-errors/SKILL.md) | Fix related failures by root cause |
| [../skills/create-worktree/SKILL.md](../skills/create-worktree/SKILL.md) | Create a worktree with repository setup applied |

Writing and implementation guidance lives in [../skills/](../skills/):
`answer-questions`, `engineering-judgment`, `code-complexity`, `comments`,
`documentation-writing`, `prompt-output`, `unit-tests`, `jsdoc`, and `security`.
The testing and JSDoc skills target Vitest and JavaScript/TypeScript.

## Review loops

These are direct skill invocations in Claude Code or Copilot CLI, not shell
commands. In Codex, replace only the leading `/` with `$`, keeping the
`ioncache-ai-tools:` prefix:

```text
/ioncache-ai-tools:review-triage-loop docs/architecture.md --max-rounds 8
/ioncache-ai-tools:review-triage-loop --resume /absolute/private/run/REVIEW_LEDGER.md
/ioncache-ai-tools:review-validate-fix-loop branch --max-loops 3 --max-fix-cycles 3
/ioncache-ai-tools:review-validate-fix-loop --resume .review-loop/<run-id>/REVIEW_LEDGER.json
```

The read-only triage loop defaults to five rounds and stops after two
consecutive complete rounds without new reportable information. Each round
uses a fresh reviewer. Its private ledger defaults to
`~/.local/state/ioncache-ai-tools/review-triage-loop/`, outside the reviewed
tree. Counters and checkpoints are skill instructions, not mechanically
enforced by the review/fix ledger helper.

The review/fix loop defaults to three review loops and three fix cycles per
loop. It does not authorize commits, pushes, or PR comments. Keep
`.review-loop/` artifacts private; they can contain source.

### Review coordination

These rules apply to `review-code`, including reviews invoked by
`review-validate-fix-loop`. The separate `review-triage-loop` requires a fresh
reviewer each round and forbids using `review-code` for that role.

Every review task requires a fresh subagent with one review purpose and
only that purpose's review instructions. There is no inline or small-check
exception. The caller/coordinator schedules and collects; correctness, each
configured standard, integration, and adjudication are separate assignments.
Nested mode uses a dedicated coordinator; flat mode uses caller-owned
collection. Both require a separate adjudicator. Missing required independence
leaves the review incomplete, without blocking other authorized work.

Before allocation, inventory repository standards, path applicability, and
exceptions. Separate code-checking passes from execution constraints such as
conversational guidance. Reuse a pinned inventory, not an assumed instruction
catalog; missing required sources leave coverage incomplete. Every configured
code-review standard gets a worker, which verifies applicability and reports
why no paths apply when appropriate. The orchestrator cannot skip a standard
because it predicts a small or low-value check.

The options helper resolves `auto` deterministically to `specialists`, which
dispatches independent review types concurrently where supported.
`sweep-first` runs correctness first, then every remaining preallocated type
in its own context. It changes order, not coverage or isolation.
Do not bundle tasks, invent an agent budget, or reuse a worker for another
purpose or review round. An actual host concurrency limit queues tasks;
it never justifies combining them. Explicit total-work limits remain binding
and leave coverage incomplete if the required roster cannot finish.

Both strategies require whole-file reads and propagate caller read/tool
constraints. Reviewers responsible for consumers also read shared
implementations; integration checks cross-boundary symbols against consumers.
The same map includes runtime handoffs, readiness prerequisites, and relevant
dependency limits. Changed enumeration and batching need checks for successful
but partial results, not just thrown errors.
Specialists write complete pass records to assigned files in caller-owned
private scratch outside the reviewed tree. Adjudicators read those files
directly rather than relying on retyped summaries. Only caller/coordinator-owned
private request, option, instruction records, and assigned reports may be written; they do not
authorize code edits or worker ledger writes.

If permitted file handoff is unavailable, explicitly agree an in-context
handoff of complete pass records or report the review as blocked.

Common scope, snapshot, and execution constraints can be shared through a
private immutable record. Each worker receives its own purpose-specific
instruction packet with source and content identities, not the full standards
catalog or another discovery worker's conclusions. Each dispatch states its
assignment, purpose, scope, snapshot, and hard limits. Adjudicators receive
the reports needed for evidence assessment, not extra standards-review tasks.
Pass results remain complete; shared records never substitute for fresh
reasoning contexts or establish another worker's actual model.

Give reviewers explicit assignments and permitted report paths. These are
instructions, not plugin-maintained permissions. Questions and handbacks do
not block other workers. Native host permissions and the review's snapshot
checks still apply; the plugin does not judge semantic purpose or report evidence.

The shared actionability policy reports worthwhile corrections (`Act`),
consequential choices (`Decide`), and credible evidence gaps (`Investigate`).
Incorrect documentation warrants correction when it causes a concrete mistaken
action, consequential misunderstanding, or maintenance risk; an observed runtime
failure is unnecessary. Harmless wording and accurate documentation in a
nonpreferred style do not. Missing
coverage of new or changed code is actionable by default, with a 100% coverage
goal and meaningful assertions. Coverage exceptions need concrete justification,
not an assumption that simple code needs no test.
Investigate production failures described as test gaps before classifying them.
Verify consequential premises in both accepted findings and rejections; PR
comments and unsupported "known issue" labels cannot establish another
component's behavior. Match findings by trigger, incorrect behavior, and
consequence, not shared labels or symbols.

Extreme, speculative edge cases are excluded unless evidence supports a
credible trigger and meaningful performance, security, privacy, or correctness
impact. Ordinary failure paths are not extreme edge cases. Severity describes
impact, independently of confidence and priority. No finding quotas or
automatic severity promotion apply.

Rejected, duplicate, style-only, and low-value observations stay private, with
counts rather than a second findings table. Every candidate retains its
`observed` or `inferred` basis, uncertainty, provenance, and assessment.
The caller's `main_min_severity` threshold (default `Low`) is a display filter
applied after actionability; it neither accepts risk nor changes fix eligibility.
The review/fix loop selects only valid, in-scope `Act` findings for corrections,
not every valid observation. Consequential unresolved evidence gaps remain
visible and required failed checks still prevent a clean review.

The triage loop's coordinator uses the same actionability policy without
changing its minimal fresh-reviewer assignments. Unresolved-PR-comment triage
also uses the policy but accounts for every supplied comment, including
no-change responses, without treating those responses as actionable defects.

Review options and defaults are in
[../skills/review-code/OPTIONS.md](../skills/review-code/OPTIONS.md). Bare invocation
runs immediately; help launches no review. Role model/effort overrides and
fallbacks pass through review/fix phases without changing the parent or fixing
model. `review-auto-model-selection` independently disables automatic choices.

Check host authority first. Default `auto` attempts an evidence-backed suitable
native choice where permitted, otherwise uses configured defaults. Explicit
choices do not require suitability research or a separate account-catalog
precondition. Neither a supported identifier nor a public catalog proves
entitlement; native rejection follows the declared fallback, without repeated
probes or an external CLI workaround. Record requested, selected, and actual
models separately; the last remains unknown when not observable.
Invoking the skill cannot override a host rule requiring specific user model
choices. Default-only execution is not verified automatic selection.

Checks cannot mutate the shared reviewed worktree. A mutation experiment needs
an explicitly authorized isolated copy. Before/after fingerprints cannot detect
intervening writes and do not make temporary shared-tree mutation safe.

Shared criteria and handback contracts:
[../skills/review-code/CRITERIA.md](../skills/review-code/CRITERIA.md),
[../skills/review-code/ORCHESTRATION.md](../skills/review-code/ORCHESTRATION.md),
and [../skills/review-code/CONTRACTS.md](../skills/review-code/CONTRACTS.md).
The outer review/fix loop owns ledger writes, fixes, and limits.

An explicitly approved scripted controller may consume these contracts. It
schedules fresh independent validation of adjudicator-originated findings; mechanical
record checks are not code-review judgments. Autonomous development keeps
review contexts separate from implementation even for small tasks, and retains
task reviews, full-PR reviews, and full-scope confirmation after corrections.
This contract does not implement a controller or authorize commits or publication.
On resume, recheck worker and instruction-set identities. Older bundled or
inline-review records cannot count as independent coverage; replace affected
assignments within the same run limits or report the gap. This policy is part
of the existing review skills and uses their opt-outs, not a separate mode
that permits worker bundling.

Supervised launch-to-handback trials remain pending. Nested/flat execution and
automatic model selection are not acceptance-verified on any host. See
[review-orchestration-plan.md](review-orchestration-plan.md) for the trial gate.
Synthetic finding-quality checks and their limits are described in
[review-evaluation.md](review-evaluation.md).

## Worktree setup

The skill requires Node.js 22.12.0 or later. Its Python launcher checks
availability and version before running the worktree helper. A missing or
older runtime, or a failed version check, stops without creating a worktree
or setup files. Install or upgrade Node.js, or correct `PATH`, then retry the
same skill invocation.

Configure `.worktree-setup.json` at the repository root. The `create-worktree`
skill creates generic defaults if it is missing: empty `copies`, `afterCopy`,
and `commands` lists, plus predefined symlinks. Those defaults do not copy a
cache or run `npm install`.

The following is a customized example, not the generated defaults:

```json
{
  "copies": ["generated-cache"],
  "afterCopy": [
    { "path": "generated-cache/.root", "content": "${worktreePath}\n" }
  ],
  "symlinks": [".claude/settings.local.json"],
  "commands": ["npm install"]
}
```

Setup runs in this order: copies, generated files, symlinks, commands.
`${worktreePath}` and `${mainRoot}` expand in generated content and commands;
quote them in commands if paths may contain spaces. Missing symlink sources
are skipped. Copy, generated-file, and symlink paths must stay within the
worktree roots. Review setup commands before using an unfamiliar repository.
