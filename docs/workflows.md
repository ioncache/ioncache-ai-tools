# Skills and workflows

Installation and basic usage: [../README.md](../README.md).
Invoke a skill directly using the host syntax in
[../README.md#invoke-a-skill](../README.md#invoke-a-skill).
Each skill's file defines its scope, inputs, and stopping conditions.

## Skill discovery

If the host lists same-name skills separately, select this plugin's entry.
Copilot instead ignores a plugin skill when a project or personal skill has
the same name. Remove the conflicting skill or exclude its directory using
`ignoredSkillsLocations` in Copilot's `~/.copilot/settings.json`, then start a
new session. A skill disabled in plugin settings can still appear in the
host's menu.

Host skill-invocation references:

- https://code.claude.com/docs/en/skills
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
- https://learn.chatgpt.com/docs/build-skills

## Workflow catalog

Most skills take task context rather than fixed command-line flags. Review and
plugin-settings options are explicit skill arguments.

| Skill | What to provide |
| --- | --- |
| [../skills/investigate/SKILL.md](../skills/investigate/SKILL.md) | The feature, workflow, or system to explain without changes |
| [../skills/review-code/SKILL.md](../skills/review-code/SKILL.md) | A file, directory, repository, branch, or PR; defaults to the active PR or branch changes |
| [../skills/review-dependabot-pr/SKILL.md](../skills/review-dependabot-pr/SKILL.md) | The dependency-update PR, including grouped updates; a saved run directory when resuming |
| [../skills/verify-unresolved-pr-comments/SKILL.md](../skills/verify-unresolved-pr-comments/SKILL.md) | Invoke from the branch with the active PR |
| [../skills/post-pr-review-comments/SKILL.md](../skills/post-pr-review-comments/SKILL.md) | The PR, findings or comments, and whether to draft, edit, reply, or post; new inline comments prefer pending reviews, requested replies post directly, and the skill never submits a review |
| [../skills/write-pr-descriptions/SKILL.md](../skills/write-pr-descriptions/SKILL.md) | The PR or branch and the requested drafting or editing task |
| [../skills/review-triage-loop/SKILL.md](../skills/review-triage-loop/SKILL.md) | An explicit target, optional round limit, or saved ledger |
| [../skills/review-validate-fix-loop/SKILL.md](../skills/review-validate-fix-loop/SKILL.md) | A target and optional loop limits, or saved ledger; defaults to active PR or branch changes |
| [../skills/triage-errors/SKILL.md](../skills/triage-errors/SKILL.md) | The failing command and relevant error context |
| [../skills/create-worktree/SKILL.md](../skills/create-worktree/SKILL.md) | Worktree arguments, such as `-b feature-name ../feature-name` |
| [../skills/plugin-settings/SKILL.md](../skills/plugin-settings/SKILL.md) | No arguments to open the pane or list settings; `--<setting-id>=enabled` or `=disabled`; optional `--global` |
| [../skills/autonomous-development/SKILL.md](../skills/autonomous-development/SKILL.md) | An idea, artifact references, an approved manifest, or a private run directory |

Writing and implementation guidance lives in [../skills/](../skills/):
`answer-questions`, `engineering-judgment`, `code-complexity`, `comments`,
`documentation-writing`, `prompt-output`, `unit-tests`, `jsdoc`, and `security`.
Unit-test guidance adapts to the actual language and runner; Vitest conventions
apply only to Vitest suites. JSDoc guidance is JavaScript-only, not TypeScript.
General documentation and contract review remain relevant to other languages,
including native doc comments and docstrings.

## Autonomous development

This skill is user-invoked only, never automatically selected for matching tasks.
Invoke `/ioncache-ai-tools:autonomous-development` in Claude/Copilot, or
`$ioncache-ai-tools:autonomous-development` in Codex. Review and approve the plan,
content snapshots, permissions, and finite limits before execution.
The execution adapter uses Claude Workflows; Copilot and Codex currently support
preparation and state inspection only. The skill prepares and claims each
generated script. Do not invoke the
`/ioncache-ai-tools:autonomous-development-run` template directly.

Planning, design documentation, and execution are independent settings. Existing
issues, designs, and plans are supported preparation inputs, not automatic
approval. The manifest pins reviewed content and separates task boundaries from
PR boundaries. GitHub issues and Notion pages can be selected without coupling
either to the execution provider.

Preparation weighs PR slicing, feature flags and optional child issues with
[../skills/autonomous-development/PLANNING.md](../skills/autonomous-development/PLANNING.md).
Set `autonomous-development-incremental-planning` to `false` to keep the
baseline planning step instead.

The Python controller persists assignments before dispatch, rejects stale
results, retains allowances on interruption, and validates local Git and existing
review-ledger evidence. Claude's packaged Workflow dispatches fresh workers and
flat review roles using frozen, single-purpose category packets. Final acceptance
checks the full phase's category handoff against the completed review snapshot;
old bundled coverage requires counted reconciliation, not relabeling.
The script itself performs no filesystem or shell operations.
Publication remains an assigned worker operation under native permissions.
The helper does not independently verify the truth of remote receipts.
With approved audit publication, separate initial and final assignments export
selected process evidence and a publication-reviewed narrative. The audit helper
updates one readable page and matching data file per PR in the modified
repository's wiki, retaining older versions in wiki history, and links them
from the PR body's `Audit` section, without changing the implementation snapshot.
It automatically puts that PR's current record at the top of the
`Automated-Pull-Request-Audits` table while preserving other rows. Preflight
requires an initialized, writable wiki. The publisher verifies the observed
GitHub PR head, wiki commit and PR-body links; the controller binds the retained
receipt to the current export. See
[../skills/autonomous-development/AUDIT.md](../skills/autonomous-development/AUDIT.md)
for privacy, retention, opt-out and recovery boundaries.

Review-category controls and saved review options use the same helpers as
standalone review. Native `model` and `effort` choices are resolved before launch,
with explicit overrides and separately recorded observations under
[../skills/autonomous-development/MODELS.md](../skills/autonomous-development/MODELS.md).
Reported null identities remain visibility limitations, not fabricated worker IDs.
Independent read-only leaves in an owner round run concurrently, while each
fixer runs alone between reader batches.

Implementers and fixers receive the same applicable standards as reviewers,
plus surrounding-context and diff self-check guidance. Reports include explicit
role contracts and a read-only precheck. Exhausted report corrections have one
evidence-based recovery without repeating work. An unchanged reviewed patch can
recover after a target-branch rebase without spending another review.
Recovery preserves work and consumed allowances; stopping a run does not roll
back its implementation. See
[../skills/autonomous-development/RECOVERY.md](../skills/autonomous-development/RECOVERY.md).

Use `configuration.execution.provider: "claude-workflows"` for the packaged
adapter. Validate with `--provider claude-workflows` before approval; initialization
and reservation support the same compatibility check without consuming work.
Relative sibling and absolute worktree paths are supported, with resolved
destinations pinned and the private store separated from every checkout.

The launcher provides the store path and runs
`python3 "/absolute/plugin/scripts/development_run.py" watch "/private/run"`.
The same command works from any session or terminal with access to the store.
It reports assignment and review progress, all stopped outcomes and inactivity,
without taking controller locks or changing state. It is not native run control.
The launcher checks preflight early and does not wait solely for the host's
completion notification.

Independent increments can be handed over early. Dependent PRs wait for observed
human merges; this adapter does not implement stacked-branch maintenance.
Completed reviews precede commits, and a full-PR review precedes readiness.
Accepted exceptions remain visible. Neither the controller nor its workers may
approve or merge PRs, force-push, deploy, or silently expand approved scope.

Offline lifecycle checks do not establish native permissions, worker launch,
result delivery or cancellation on a given host. Execution establishes those
from the selected host's evidence, and the launching session reports any the
preflight record deferred that no later step established; see
[the worker contract](../skills/autonomous-development/WORKERS.md).
Authorization already given needs no separate trial approval or trial budget;
see Prepare step 6 of [the skill](../skills/autonomous-development/SKILL.md).
Hosting, shared storage, team controls, notification services, and browser/upload
capabilities are consuming-environment requirements, not provisioned services.

Contracts and recovery:
[../skills/autonomous-development/CONTRACT.md](../skills/autonomous-development/CONTRACT.md).
Set `autonomous-development` to `false` in the feature configuration to disable
execution while retaining status and interruption commands.
Worker boundaries:
[../skills/autonomous-development/WORKERS.md](../skills/autonomous-development/WORKERS.md).
Claude API and packaging reference:
https://code.claude.com/docs/en/workflows.

## Review options

```text
/ioncache-ai-tools:review-code --help
/ioncache-ai-tools:review-code this PR --model-selection configured
/ioncache-ai-tools:review-code this PR --lead-model LEAD_ID --reviewer-model REVIEW_ID
```

Replace model placeholders with identifiers supported by your host. Unspecified
roles attempt automatic selection where host permissions and capability evidence
allow it, otherwise configured models are used. Explicit choices are not silently
replaced. The lead is the review coordinator or adjudicator, not your
conversation's model.

Reviews provide 12 independently enabled categories across the requested scope:
security, complexity, comments, JSDoc, unit-test quality, documentation, design
coherence, correctness, integration, privacy, performance and test coverage.
General categories adapt to the actual stack. JSDoc requires JavaScript source;
TypeScript-only and other JavaScript-free targets retain general documentation
and contract review without a JSDoc worker.

Independent `review-<category>` settings control shipped coverage, separately
from writing-skill settings. With no extra project categories, a default flat
phase starts with 12 workers without JavaScript or 13 with it, including
adjudication, before retries, validators or capacity shards.
See [configuration.md](configuration.md) for opt-outs and the coordination
section below for project requirements and worker isolation.

Role effort, validator, fallback, strategy, and posting options:
[../skills/review-code/OPTIONS.md](../skills/review-code/OPTIONS.md).
The review/fix loop accepts the same review options, except posting options;
they do not change its fixing model.
Use `$ioncache-ai-tools:review-code --help` in Codex. Claude can show argument
hints; `--help` is the portable option list, not a cross-host picker.

### Unresolved findings

Reviews name unresolved material findings under **Known issues not fixed here**,
including pre-existing and out-of-scope defects. Autonomous development carries
that list into its final report and PR, and can create or reuse follow-up issues
when separately approved. Ticket failures do not stop development.
See [../skills/autonomous-development/FOLLOW_UPS.md](../skills/autonomous-development/FOLLOW_UPS.md)
for publication and disclosure rules.

## Review loops

These are direct skill invocations in Claude Code or Copilot CLI, not shell
commands. In Codex, replace only the leading `/` with `$`, keeping the
`ioncache-ai-tools:` prefix:

```text
/ioncache-ai-tools:review-triage-loop docs/architecture.md --max-rounds 8
/ioncache-ai-tools:review-triage-loop --resume /absolute/private/run/REVIEW_LEDGER.md
/ioncache-ai-tools:review-validate-fix-loop branch --max-loops 3 --max-fix-cycles 3
/ioncache-ai-tools:review-validate-fix-loop --resume /absolute/private/reviews/<worktree-identity>/<run-id>/REVIEW_LEDGER.json
```

The read-only triage loop defaults to five rounds and stops after two
consecutive complete rounds without new reportable information. Each round
uses a fresh reviewer. The target can be a file, directory, repository, or
branch/PR comparison. Resume uses the saved target; an explicit `--max-rounds`
replaces the total cap, not the remaining allowance. Its private ledger defaults
to
`~/.local/state/ioncache-ai-tools/review-triage-loop/`, outside the reviewed
tree. Counters and checkpoints are skill instructions, not mechanically
enforced by the review/fix ledger helper.

The review/fix loop defaults to three review loops and three fix cycles per
loop. Loop counts are not spending limits. Replace the example resume paths
with the ledger from your run. It does not authorize commits, pushes, or PR
comments. Standalone ledgers and objects default to
`~/.local/state/ioncache-ai-tools/reviews/`, honoring
`XDG_STATE_HOME`. Development runs use their assigned external storage, normally
inside their private store. Retain any recovery locations recorded in assignments.
Keep these artifacts private; they can contain source and survive worktree cleanup.
Use the ledger helper's `migrate` command for legacy in-worktree records before
deleting the checkout, and `inspect` for saved history without live acceptance.

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
catalog; missing required sources leave coverage incomplete. Enabled general
standards and evidenced language-specific standards get separate workers.
Resolve explicit language prerequisites before dispatch; unknown language facts
leave coverage unresolved while other work continues. Dispatched workers verify
remaining file-level applicability. The orchestrator cannot skip a standard
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
instructions, not plugin-maintained permissions. A user question restricts
only the agent that received it; handbacks and questions do not block other
workers. Native host permissions and the review's snapshot
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

For Claude/Copilot:

```text
/ioncache-ai-tools:create-worktree -b feature-name ../feature-name
```

For Codex:

```text
$ioncache-ai-tools:create-worktree -b feature-name ../feature-name
```

Replace the branch name and destination with your own.

The skill requires Node.js 22.12.0 or later. Its Python launcher checks
availability and version before running the worktree helper. A missing or
older runtime, or a failed version check, stops without creating a worktree
or setup files. Install or upgrade Node.js, or correct `PATH`, then retry the
same skill invocation.

Configure `.worktree-setup.json` at the main worktree's root. The `create-worktree`
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
