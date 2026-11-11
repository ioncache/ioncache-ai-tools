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

Small reviews stay inline when the evidence fits one direct read and no
substantial independent pass is needed. Explicit independence requests take
precedence. Substantial reviews use nested coordination where supported or
flat worker collection with a separate adjudicator. Missing required
independence blocks the review.

An explicit strategy takes precedence. Otherwise `sweep-first` is preferred
when the whole correctness scope fits one worker and risk does not require
specialist-first allocation. Follow-ups address concrete risks, evidence gaps,
and remaining standards/docs coverage. Small standards checks can share a
worker. Both strategies retain integration and independent adjudication;
finding counts are not an allocation target.

Both strategies require whole-file reads and propagate caller read/tool
constraints. Reviewers responsible for consumers also read shared
implementations; integration checks cross-boundary symbols against consumers.
Specialists write complete pass records to assigned files in caller-owned
private scratch outside the reviewed tree. Adjudicators read those files
directly rather than relying on retyped summaries. These reports are the only
review write exception; they do not authorize code edits or worker ledger writes.

If permitted file handoff is unavailable, explicitly agree an in-context
handoff of complete pass records or report the review as blocked.

Scope hooks check authorization, not report evidence. Ordinary background
tool output does not invalidate scope verdicts; review snapshot checks still
reject target drift. Background handback limitations and the foreground
fallback are covered in [guardrails.md#host-coverage-and-limits](guardrails.md#host-coverage-and-limits).

The shared actionability policy reports worthwhile corrections (`Act`),
consequential choices (`Decide`), and credible evidence gaps (`Investigate`).
Incorrect documentation warrants correction without an observed runtime
failure; accurate documentation in a nonpreferred style does not. Missing
coverage of new or changed code is actionable by default, with a 100% coverage
goal and meaningful assertions. Coverage exceptions need concrete justification,
not an assumption that simple code needs no test.

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

Review-role model choices depend on current availability, suitability evidence,
and host permissions. When those are missing, preserve configured defaults and
disclose the limitation. This is not automatic runtime model selection.

Shared criteria and handback contracts:
[../skills/review-code/CRITERIA.md](../skills/review-code/CRITERIA.md),
[../skills/review-code/ORCHESTRATION.md](../skills/review-code/ORCHESTRATION.md),
and [../skills/review-code/CONTRACTS.md](../skills/review-code/CONTRACTS.md).
The outer review/fix loop owns ledger writes, fixes, and limits.

Supervised launch-to-handback trials remain pending. Nested/flat execution and
automatic model selection are not acceptance-verified on any host. See
[review-orchestration-plan.md](review-orchestration-plan.md) for the trial gate.

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
