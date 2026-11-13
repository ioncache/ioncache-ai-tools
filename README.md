# ioncache-ai-tools

A plugin for Claude Code, GitHub Copilot CLI, and Codex CLI. It provides
19 directly invocable skills for code review, PR work, investigation, writing,
and implementation, plus automatic guardrails for common tool actions.

## Install

Requires Python 3.11+, Git, and macOS or Linux. Use a current supported
CLI with a working login. PR workflows also need access to the relevant GitHub
repository. The Copilot integration targets the CLI, not the cloud agent or
VS Code.

For PR operations that require GitHub CLI (`gh`), including posting review
comments, install it from https://cli.github.com/ and run `gh auth login` in
your terminal. Read-only PR workflows can use a suitable GitHub integration
instead, or fall back to `gh`.

### Claude Code

Run inside Claude Code:

```text
/plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Choose user scope to make the plugin available across projects. Reload plugins
or start a new session when prompted. Manage updates and removal through `/plugin`.

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

Start your CLI in the project you want to work on. Enter the skill invocation
in the assistant's interactive input, **not your shell**:

| Host | Invoke a code review | Find installed skills |
| --- | --- | --- |
| Claude Code | `/ioncache-ai-tools:review-code` | Type `/` and select the plugin's skill |
| GitHub Copilot CLI | `/ioncache-ai-tools:review-code` | `/skills list` |
| Codex CLI | `$ioncache-ai-tools:review-code` | `/skills`, or type `$` to select a skill |

Use the same syntax for any skill listed below. The catalog shows the
Claude/Copilot invocation. In Codex, replace only the leading `/` with `$`,
keeping the `ioncache-ai-tools:` prefix.

If the host lists same-name skills separately, select this plugin's entry.
Copilot instead ignores a plugin skill when a project or personal skill has
the same name. Remove the conflicting skill or exclude its directory using
`ignoredSkillsLocations` in Copilot's `~/.copilot/settings.json`, then start a
new session.

Append the target or task to the invocation when needed. For example, these
review the current branch:

```text
/ioncache-ai-tools:review-code branch
```

In Codex:

```text
$ioncache-ai-tools:review-code branch
```

Most skills take task context rather than fixed command-line flags. Review
options below are explicit skill arguments. Bare `review-code` invocation uses
defaults without a setup prompt.

## Skills

### Reviews and PR work

| Invocation in Claude/Copilot | What it does | What to provide |
| --- | --- | --- |
| `/ioncache-ai-tools:review-code` | Reviews code without applying fixes or posting comments | A file, directory, repository, branch, or PR; defaults to the active PR or branch changes |
| `/ioncache-ai-tools:review-dependabot-pr` | Checks dependency updates against actual project usage; reports without changing the PR | The Dependabot, Renovate, or other dependency-update PR; a saved run directory when resuming |
| `/ioncache-ai-tools:verify-unresolved-pr-comments` | Evaluates unresolved feedback and recommends fixes or responses; does not edit, post, resolve threads, or run tests | Invoke from the branch with the active PR |
| `/ioncache-ai-tools:post-pr-review-comments` | Drafts or edits review comments; can add them to a pending review when explicitly requested; never submits the review | The PR, findings or comments, and whether to draft, edit, or post |
| `/ioncache-ai-tools:write-pr-descriptions` | Drafts or edits a PR title and description | The PR or branch and the requested drafting or editing task |
| `/ioncache-ai-tools:review-triage-loop` | Repeats read-only review and prioritizes findings without fixing them | An explicit target, optional round limit, or saved ledger |
| `/ioncache-ai-tools:review-validate-fix-loop` | Reviews, validates findings, edits code, and re-reviews within limits | A target and optional loop limits, or saved ledger; defaults to active PR or branch changes |

### Investigation and implementation

| Invocation in Claude/Copilot | What it does | What to provide |
| --- | --- | --- |
| `/ioncache-ai-tools:investigate` | Traces a feature or workflow and explains its behavior without editing files | The feature, workflow, or system to investigate |
| `/ioncache-ai-tools:triage-errors` | Groups failing checks by root cause and fixes each group | The failing command and relevant error context |
| `/ioncache-ai-tools:create-worktree` | Creates a git worktree and applies the repository's setup configuration | Worktree arguments, such as `-b feature-name ../feature-name` |

### Writing and engineering guidance

Invoke these with the task or files you want the guidance applied to. They
provide standards for the requested work, not standalone test or audit tools.

| Invocation in Claude/Copilot | Guidance |
| --- | --- |
| `/ioncache-ai-tools:engineering-judgment` | Choose coherent solutions across affected code while honoring scope limits |
| `/ioncache-ai-tools:code-complexity` | Keep functions cohesive; evaluate size, nesting, and parameter counts |
| `/ioncache-ai-tools:comments` | Decide when code comments are warranted and explain why, not what |
| `/ioncache-ai-tools:documentation-writing` | Write direct documentation with clear sentences and standard punctuation |
| `/ioncache-ai-tools:prompt-output` | Format a requested prompt as one copyable Markdown code block |
| `/ioncache-ai-tools:unit-tests` | Write or review JavaScript/TypeScript tests using Vitest conventions |
| `/ioncache-ai-tools:jsdoc` | Write or review JSDoc using the plugin's JS/TS documentation conventions |
| `/ioncache-ai-tools:security` | Apply input-validation, authentication, and secret-handling standards |
| `/ioncache-ai-tools:answer-questions` | Inspect question-answering guidance; not required before asking ordinary questions |

Full skill instructions are in [skills/](skills/).

## Review options

```text
/ioncache-ai-tools:review-code --help
/ioncache-ai-tools:review-code this PR --model-selection configured
/ioncache-ai-tools:review-code this PR --lead-model LEAD_ID --reviewer-model REVIEW_ID
```

Replace model placeholders with identifiers supported by your host. Unspecified
roles default to attempting automatic selection where host permissions and
capability evidence allow it, otherwise configured models are used.
Explicit choices are not silently replaced. The lead is the review coordinator
or adjudicator, not your conversation's model.

Reviews require a fresh subagent for each review purpose, including each
configured standard. Small changes do not permit inline or bundled checks.
Coordination, integration review, and adjudication stay separate.
The default strategy uses isolated specialists; `sweep-first` changes their
order, not the required tasks or context isolation.

Role effort, validator, fallback, and strategy options are listed in
[skills/review-code/OPTIONS.md](skills/review-code/OPTIONS.md). The review/fix loop
accepts the same review options; they do not change its fixing model.
Use `$ioncache-ai-tools:review-code --help` in Codex. Claude can show argument
hints; `--help` is the portable option list, not a promised cross-host picker.

## Review-loop arguments

Use `review-triage-loop` for repeated review without fixes:

```text
/ioncache-ai-tools:review-triage-loop branch --max-rounds 5
/ioncache-ai-tools:review-triage-loop --resume /absolute/path/to/REVIEW_LEDGER.md
```

It defaults to five rounds and stops early after two consecutive complete
rounds with no new reportable information. The target can be a file, directory,
repository, or branch/PR comparison. Resume uses the saved target; an explicit
`--max-rounds` replaces the total cap, not the remaining allowance.

Use `review-validate-fix-loop` when you want findings fixed:

```text
/ioncache-ai-tools:review-validate-fix-loop branch --max-loops 3 --max-fix-cycles 3
/ioncache-ai-tools:review-validate-fix-loop --resume .review-loop/<run-id>/REVIEW_LEDGER.json
```

Defaults are three outer review loops and three fix cycles per outer loop.
Replace the resume paths with the ledger from your run. This skill edits files,
but does not commit, push, or post PR comments. Loop counts are not spending
limits. Keep review artifacts private because they can contain source.

For Codex, the equivalent invocation starts with
`$ioncache-ai-tools:review-triage-loop` or
`$ioncache-ai-tools:review-validate-fix-loop`; the arguments stay the same.

## Worktree setup

This skill requires Node.js 22.12.0 or later. The launcher checks availability
and version before creating a worktree or setup files. If either check fails,
install or upgrade Node.js, or correct `PATH`, then retry the skill.

For Claude/Copilot:

```text
/ioncache-ai-tools:create-worktree -b feature-name ../feature-name
```

For Codex:

```text
$ioncache-ai-tools:create-worktree -b feature-name ../feature-name
```

Replace the branch name and destination with your own. The skill applies
`.worktree-setup.json` from the main worktree. If it is missing, the helper
creates generic symlink defaults; dependency installation requires a configured
setup command. See [docs/workflows.md#worktree-setup](docs/workflows.md#worktree-setup)
for configuration examples.

## Automatic guardrails

Hooks run without a skill invocation. Scope and questions supply guidance,
not task approvals or turn-wide permission gates. Questions and messages do
not create blocking state for the receiving worker or other agents. Native
host permissions still apply.

Action checks block direct lockfile edits, broad process termination, and raw
worktree creation. Recovery uses the package manager, an exact owned process
target, or the setup helper respectively, without a plugin approval exchange.
Checks also fix or reject em-dashes in file edits and shell input.

Guidance covers scope, direct answers, documentation-backed
research, and engineering judgment. Hooks do not use model reviews to judge
authorization or reply content. Checker failures report unavailability rather
than stopping the worker or granting host permission.
The documentation cache reuses facts from supported documentation fetches.
**Cache distillation makes additional model calls and consumes the host's
usage.** Disable `docs-cache` to opt out.

## Configuration

Every shipped guard and skill is enabled by default. Edit the appropriate
global or project settings file to opt out:

| Host | Global settings | Project settings |
| --- | --- | --- |
| Claude Code | `~/.claude/ioncache-ai-tools.local.json` | `.claude/ioncache-ai-tools.local.json` |
| Copilot CLI | `~/.copilot/ioncache-ai-tools.local.json` | `.github/copilot/ioncache-ai-tools.local.json` |
| Codex CLI | `~/.codex/ioncache-ai-tools.local.json` | `.codex/ioncache-ai-tools.local.json` |

For example, disable the documentation cache and the code-review skill:

```json
{
  "features": {
    "docs-cache": false,
    "skill:review-code": false
  }
}
```

Set either entry to `true` to re-enable it. Project values override global
values within each host; a feature disabled by any host's effective settings
is disabled across all three. Settings edits need no reinstall. Start a fresh
session to refresh instructions already in context. A disabled skill can still
appear in the host's menu.

Available settings: [config/defaults.json](config/defaults.json).
Precedence and synchronization: [docs/configuration.md](docs/configuration.md).

## Known issues and limits

| Situation | What to know or do |
| --- | --- |
| A skill is missing | Confirm the plugin is installed and enabled, then start a fresh session or thread. Use the host's skill picker shown above. |
| An action is denied | Use the alternative in the denial rather than repeating the command. Plugin recovery does not require per-turn approval. |
| A checker is unavailable | The plugin reports the problem without creating a persistent tool gate. Native permissions still apply. |
| Sensitive documentation questions | The shared cache can replay Claude's original `WebFetch` question across projects and hosts. Disable `docs-cache` before submitting sensitive questions. |
| Review coordination | Supervised cross-host trials remain pending; not every execution mode is acceptance-verified. |
| Response punctuation | Assistant text is not rewritten or blocked. File-edit punctuation checks remain independent. |
| Copilot child `/tmp` writes | Some general-purpose workers refuse these writes even with allow-all. This also occurs without the plugin; see https://github.com/github/copilot-cli/issues/5441. |

These are guardrails, not a security boundary. Unsupported tools and shell
indirection can evade checks; agents with settings access can disable them.
Keep the host's own permissions enabled for security-critical restrictions.

## Reference

| Topic | Documentation |
| --- | --- |
| Guard behavior, recovery, and privacy | [docs/guardrails.md](docs/guardrails.md) |
| Settings and synchronization | [docs/configuration.md](docs/configuration.md) |
| Detailed review workflows and worktree configuration | [docs/workflows.md](docs/workflows.md) |
| Cache behavior and troubleshooting | [docs/documentation-cache.md](docs/documentation-cache.md) |

Host skill-invocation references:

- https://code.claude.com/docs/en/skills
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
- https://learn.chatgpt.com/docs/build-skills
