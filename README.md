# ioncache-ai-tools

A plugin for Claude Code, GitHub Copilot CLI, and Codex CLI. It provides
21 directly invocable skills for code review, PR work, investigation, writing,
and implementation, plus automatic guardrails for common tool actions.

## Install

Requires Python 3.11+, Git, and macOS or Linux. Use a current supported CLI
with a working login. The Copilot integration targets the CLI, not the cloud
agent or VS Code.

PR workflows need repository access. Operations such as posting review comments
also require GitHub CLI (`gh`): install it from https://cli.github.com/ and run
`gh auth login`. Read-only PR workflows can use a suitable GitHub integration
instead.

### Claude Code

Run inside Claude Code:

```text
/plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Choose user scope for use across projects. Reload plugins or start a new session
when prompted. Manage updates and removal through `/plugin`.

### GitHub Copilot CLI

Run in your terminal:

```sh
copilot plugin install ioncache/ioncache-ai-tools
```

Start a new session. Update with `copilot plugin update ioncache-ai-tools`;
remove with `copilot plugin uninstall ioncache-ai-tools`.

### Codex CLI

Run in your terminal:

```sh
codex plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
codex plugin add ioncache-ai-tools --marketplace ioncache-ai-tools
codex
```

Inside Codex, review and trust the plugin hooks through `/hooks`, then start a
new thread. Use `/plugins` to manage installed plugins.
To update, run `codex plugin marketplace upgrade ioncache-ai-tools`, repeat
the plugin-add command, and start a fresh thread. To uninstall, run
`codex plugin remove ioncache-ai-tools --marketplace ioncache-ai-tools`.

## Invoke a skill

Start your CLI in the project you want to work on. Enter the invocation in the
assistant's interactive input, **not your shell**:

| Host | Invoke a code review | Find installed skills |
| --- | --- | --- |
| Claude Code | `/ioncache-ai-tools:review-code` | Type `/` and select the plugin's skill |
| GitHub Copilot CLI | `/ioncache-ai-tools:review-code` | `/skills list` |
| Codex CLI | `$ioncache-ai-tools:review-code` | `/skills`, or type `$` to select a skill |

Append a target or task when needed, for example
`/ioncache-ai-tools:review-code branch`. The catalog below uses Claude/Copilot
syntax. In Codex, replace only the leading `/` with `$`, keeping the
`ioncache-ai-tools:` prefix.

## Skills

### Reviews and PR work

| Invocation in Claude/Copilot | What it does |
| --- | --- |
| `/ioncache-ai-tools:review-code` | Reviews files, branches, repositories, or PRs without fixes; `--post-comments` publishes one comment review |
| `/ioncache-ai-tools:review-dependabot-pr` | Checks dependency-update PRs against actual usage without changing them |
| `/ioncache-ai-tools:verify-unresolved-pr-comments` | Evaluates active-PR feedback without editing, posting, resolving threads, or running tests |
| `/ioncache-ai-tools:post-pr-review-comments` | Drafts or edits comments and posts requested replies; never submits a review |
| `/ioncache-ai-tools:write-pr-descriptions` | Drafts or edits a PR title and description |
| `/ioncache-ai-tools:review-triage-loop` | Repeats read-only review and prioritizes findings |
| `/ioncache-ai-tools:review-validate-fix-loop` | Reviews, validates, fixes, and re-reviews within limits; does not commit or push |

Bare `review-code` uses the active PR or branch changes without a setup prompt.
Use `/ioncache-ai-tools:review-code --help` for options. Reviews launch multiple
specialist agents; loop counts are not spending limits. Model selection,
coverage, loop limits, and resume examples: [docs/workflows.md](docs/workflows.md).

### Investigation and implementation

| Invocation in Claude/Copilot | What it does |
| --- | --- |
| `/ioncache-ai-tools:investigate` | Explains an existing feature or workflow without editing files |
| `/ioncache-ai-tools:triage-errors` | Groups failing checks by root cause and fixes them |
| `/ioncache-ai-tools:create-worktree` | Creates a git worktree with repository setup applied; requires Node.js 22.12.0+ |
| `/ioncache-ai-tools:plugin-settings` | Lists or changes plugin settings across all three hosts |
| `/ioncache-ai-tools:autonomous-development` | Prepares approved plans and coordinates bounded implementation toward review-ready PRs |

### Writing and engineering guidance

Invoke these with the task or files to apply them to. They supply standards,
not standalone test or audit tools.

| Invocation in Claude/Copilot | Guidance |
| --- | --- |
| `/ioncache-ai-tools:engineering-judgment` | Choose coherent solutions while honoring scope |
| `/ioncache-ai-tools:code-complexity` | Keep functions cohesive and control nesting and parameter counts |
| `/ioncache-ai-tools:comments` | Keep implementation comments purposeful and preserve API documentation |
| `/ioncache-ai-tools:documentation-writing` | Write direct documentation with clear sentences and standard punctuation |
| `/ioncache-ai-tools:prompt-output` | Format a requested prompt as one copyable Markdown code block |
| `/ioncache-ai-tools:unit-tests` | Write or review tests using the target language and framework |
| `/ioncache-ai-tools:jsdoc` | Write or review JavaScript JSDoc, not TypeScript or other languages |
| `/ioncache-ai-tools:security` | Apply input-validation, authentication, and secret-handling standards |
| `/ioncache-ai-tools:answer-questions` | Inspect the answer-only question policy; not needed for ordinary questions |

Inputs, examples, and workflow details: [docs/workflows.md](docs/workflows.md).
Full instructions: [skills/](skills/).

## Autonomous development

This skill is **user-invoked only**. Review and approve the plan, content,
permissions, and finite limits before execution. Claude Workflows is the
execution provider; Copilot and Codex support preparation and state inspection
only. PR merging stays under human control.

Runs retain private recovery state and can publish approved process audits to
the modified repository's initialized, writable GitHub wiki. Preparation,
monitoring, audits, and recovery: [docs/workflows.md#autonomous-development](docs/workflows.md#autonomous-development).

## Automatic guardrails

Hooks run without a skill invocation. They guide scope, question-only answers,
documentation-backed research, and engineering judgment. Verified user-question
turns restrict that root agent's state changes, not running children.

Action checks block direct lockfile edits, broad process termination, and raw
worktree creation. Use the package manager, an exact owned process target, or
the setup helper instead. File-edit and shell checks also fix or reject
em-dashes. Details: [docs/guardrails.md](docs/guardrails.md).

The documentation cache reuses fetched facts. **Cache distillation makes
additional model calls and consumes host usage.** It can replay Claude's
original fetch question across projects and hosts; disable `hook:docs-cache`
before submitting sensitive questions.

Optional response validation checks factual support and rewrites overclaims
before delivery in Claude Code 2.1.332+. It is off by default and adds model
usage and latency. It does not run in Copilot or Codex.
Opt-in and limits: [docs/response-validation.md](docs/response-validation.md).

## Configuration

Guards and skills ship enabled; response validation is the exception.
Use the settings skill in your assistant:

```text
/ioncache-ai-tools:plugin-settings
/ioncache-ai-tools:plugin-settings --list
/ioncache-ai-tools:plugin-settings --hook:docs-cache=disabled
```

In Codex, use `$ioncache-ai-tools:plugin-settings` with the same arguments.
Claude opens a native pane when available; otherwise the command lists settings.
`--list` always uses text, and `--help` lists flags.

Changes default to the current project and apply across all three hosts.
Add `--global` for global settings, preserving project overrides. Set a flag
to `enabled` to re-enable it. Settings edits need no reinstall; start a fresh
session to refresh instructions already in context.
Manual JSON, all settings, and precedence: [docs/configuration.md](docs/configuration.md).

## Known issues and limits

| Situation | What to know or do |
| --- | --- |
| A skill is missing | Check installation and enablement, then start a fresh session or thread. Same-name skills can conflict; see [docs/workflows.md#skill-discovery](docs/workflows.md#skill-discovery). |
| An action is denied | Use the alternative in the denial rather than repeating it. Plugin recovery does not require per-turn approval. |
| A checker is unavailable | The plugin reports the problem without creating a persistent tool gate. Native permissions still apply. |
| Review coordination | Supervised cross-host trials remain pending; not every execution mode is acceptance-verified. |
| Response punctuation | There is no response punctuation filter; file-edit checks are separate. |
| Copilot child `/tmp` writes | Some general-purpose workers refuse these writes even with allow-all, including without the plugin; see https://github.com/github/copilot-cli/issues/5441. |

These guardrails are **not a security boundary**. Unsupported tools and shell
indirection can evade checks; agents with settings access can disable them.
Keep the host's own permissions enabled for security-critical restrictions.

## Reference

| Topic | Documentation |
| --- | --- |
| Review options, loops, autonomous development, and worktree setup | [docs/workflows.md](docs/workflows.md) |
| Settings and synchronization | [docs/configuration.md](docs/configuration.md) |
| Guard behavior, recovery, and privacy | [docs/guardrails.md](docs/guardrails.md) |
| Cache behavior and troubleshooting | [docs/documentation-cache.md](docs/documentation-cache.md) |
| Claude response validation, opt-in, and costs | [docs/response-validation.md](docs/response-validation.md) |
