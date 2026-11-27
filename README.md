# ioncache-ai-tools

A plugin for Claude Code, GitHub Copilot CLI, and Codex CLI. It provides skills
for reviews, PR work, investigation, and implementation, plus automatic hooks
and reusable engineering instructions.

## How to install

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

## How to use

### Configuration

Use `plugin-settings` to inspect or change the plugin's settings. Enter these
commands in your assistant using the invocation syntax described below:

| Invocation | Guidance |
| --- | --- |
| `/ioncache-ai-tools:plugin-settings` | Open the settings pane when available, or print the grouped listing |
| `/ioncache-ai-tools:plugin-settings --list` | List every setting and its effective enabled/disabled state |
| `/ioncache-ai-tools:plugin-settings --help` | Show all setting flags |
| `/ioncache-ai-tools:plugin-settings --hook:response-validation=enabled` | Enable response validation |
| `/ioncache-ai-tools:plugin-settings --hook:docs-cache=disabled` | Disable documentation caching |

Changes default to the current project and apply across all three hosts.
Add `--global` for global settings, preserving project overrides. Hook and
instruction names in the tables below are setting IDs: pass
`--<setting-id>=enabled` or `--<setting-id>=disabled` to `plugin-settings`.

The **Default** column shows shipped defaults, not your current settings.
Enabled means available on supported hosts, not that every skill runs
automatically. Settings edits need no reinstall; start a fresh session to
refresh instructions already in context. Manual JSON, precedence, and detailed
workflow settings: [docs/configuration.md](docs/configuration.md).

### Invoke a skill

Start your CLI in the project you want to work on. Enter the invocation in the
assistant's interactive input, **not your shell**:

| Host | Invoke a code review | Find installed skills |
| --- | --- | --- |
| Claude Code | `/ioncache-ai-tools:review-code` | Type `/` and select the plugin's skill |
| GitHub Copilot CLI | `/ioncache-ai-tools:review-code` | `/skills list` |
| Codex CLI | `$ioncache-ai-tools:review-code` | `/skills`, or type `$` to select a skill |

All skill and settings invocations elsewhere in this README use the `/`
form. In Codex, replace only that leading `/` with `$`, keeping the
`ioncache-ai-tools:` prefix and arguments unchanged.

Append a target or task when needed, for example
`/ioncache-ai-tools:review-code branch`. Same-name skill conflicts and discovery:
[docs/workflows.md#skill-discovery](docs/workflows.md#skill-discovery).

### Skills

Invoke a skill with the task or files you want it to work on. Related skills
are grouped below; their detailed options stay in the linked documentation.

#### Reviews and PR work

Review workflows can launch multiple specialist agents. Loop counts are not
spending limits.

| Invocation | Default | Guidance |
| --- | --- | --- |
| `/ioncache-ai-tools:review-code` | Enabled | Review files, branches, repositories, or PRs without fixes; defaults to the active PR or branch changes. Options and optional posting: [docs/workflows.md#review-options](docs/workflows.md#review-options) |
| `/ioncache-ai-tools:review-dependabot-pr` | Enabled | Check dependency-update PRs against actual usage without changing them |
| `/ioncache-ai-tools:verify-unresolved-pr-comments` | Enabled | Evaluate active-PR feedback without editing, posting, resolving threads, or running tests |
| `/ioncache-ai-tools:post-pr-review-comments` | Enabled | Draft or edit comments and post requested replies; never submit a review |
| `/ioncache-ai-tools:write-pr-descriptions` | Enabled | Draft or edit a PR title and description |
| `/ioncache-ai-tools:review-triage-loop` | Enabled | Repeat read-only review and prioritize findings. Limits and resume: [docs/workflows.md#review-loops](docs/workflows.md#review-loops) |
| `/ioncache-ai-tools:review-validate-fix-loop` | Enabled | Review, validate, fix, and re-review within limits; never commit or push. [docs/workflows.md#review-loops](docs/workflows.md#review-loops) |

#### Investigation and implementation

| Invocation | Default | Guidance |
| --- | --- | --- |
| `/ioncache-ai-tools:investigate` | Enabled | Explain an existing feature or workflow without editing files |
| `/ioncache-ai-tools:triage-errors` | Enabled | Group failing checks by root cause and fix them |
| `/ioncache-ai-tools:create-worktree` | Enabled | Create a git worktree with repository setup applied; requires Node.js 22.12.0+. [docs/workflows.md#worktree-setup](docs/workflows.md#worktree-setup) |
| `/ioncache-ai-tools:plugin-settings` | Enabled | Inspect or change plugin settings across all three hosts. [docs/configuration.md](docs/configuration.md) |
| `/ioncache-ai-tools:autonomous-development` | Enabled | User-invoked only: plan approved work and coordinate bounded implementation toward review-ready PRs. Execution requires Claude Workflows; other hosts support preparation and inspection. [docs/workflows.md#autonomous-development](docs/workflows.md#autonomous-development) |

Review and approve the autonomous-development plan, content, permissions, and
limits before execution. PR merging stays under human control.

#### Writing and engineering guidance

These skills apply standards to the requested work. They are not standalone
test or audit tools.

| Invocation | Default | Guidance |
| --- | --- | --- |
| `/ioncache-ai-tools:engineering-judgment` | Enabled | Choose coherent solutions while honoring scope |
| `/ioncache-ai-tools:code-complexity` | Enabled | Keep functions cohesive and control nesting and parameter counts |
| `/ioncache-ai-tools:comments` | Enabled | Keep implementation comments purposeful and preserve API documentation |
| `/ioncache-ai-tools:documentation-writing` | Enabled | Write direct documentation with clear sentences and standard punctuation |
| `/ioncache-ai-tools:prompt-output` | Enabled | Format a requested prompt as one copyable Markdown code block |
| `/ioncache-ai-tools:unit-tests` | Enabled | Write or review tests using the target language and framework |
| `/ioncache-ai-tools:jsdoc` | Enabled | Write or review JavaScript JSDoc, not TypeScript or other languages |
| `/ioncache-ai-tools:security` | Enabled | Apply input-validation, authentication, and secret-handling standards |

### Hooks

Hooks run automatically, without a skill invocation. They guard common tool
actions and provide background services. A denied action includes an allowed
alternative so the agent can continue; native host permissions still apply.
The names below are settings, not commands to invoke.

#### Automatic guardrails

| Setting | Default | Guidance |
| --- | --- | --- |
| `hook:answer-questions` | Enabled | Keep verified user-question turns answer-only for that root agent; running children remain unrestricted. [docs/guardrails.md#question-turns](docs/guardrails.md#question-turns) |
| `hook:autonomous-development:explicit-only` | Enabled | Prevent automatic skill-tool activation of autonomous development; require direct user invocation. [docs/configuration.md#settings-command](docs/configuration.md#settings-command) |
| `hook:block_raw_worktree_add` | Enabled | Block raw worktree creation and direct the agent to the configured setup helper. [docs/guardrails.md#action-checks-and-autonomous-recovery](docs/guardrails.md#action-checks-and-autonomous-recovery) |
| `hook:no-manual-lockfile-edit` | Enabled | Block direct lockfile edits through file tools; use the package manager instead. [docs/guardrails.md#action-checks-and-autonomous-recovery](docs/guardrails.md#action-checks-and-autonomous-recovery) |
| `hook:no_manual_lockfile_edit_bash` | Enabled | Block recognized shell commands that directly edit lockfiles. [docs/guardrails.md#action-checks-and-autonomous-recovery](docs/guardrails.md#action-checks-and-autonomous-recovery) |
| `hook:no_broad_process_kill` | Enabled | Block broad process termination; use an exact owned process target or native stop control. [docs/guardrails.md#action-checks-and-autonomous-recovery](docs/guardrails.md#action-checks-and-autonomous-recovery) |
| `hook:fix_emdash` | Enabled | Rewrite em-dashes in structured file edits and reject them in shell input or patch additions. [docs/guardrails.md#action-checks-and-autonomous-recovery](docs/guardrails.md#action-checks-and-autonomous-recovery) |

#### Automatic services

| Setting | Default | Guidance |
| --- | --- | --- |
| `hook:docs-cache` | Enabled | Reuse fetched documentation facts; distillation makes extra model calls and consumes host usage. [docs/documentation-cache.md](docs/documentation-cache.md) |
| `hook:plugin-settings-ui` | Enabled | Open the native Claude settings pane when available; keep the text interface available otherwise. [docs/configuration.md#native-claude-settings-pane](docs/configuration.md#native-claude-settings-pane) |
| `hook:response-validation` | Disabled | Check factual support and rewrite overclaims before delivery in Claude Code 2.1.332+ only; adds model usage and latency. [docs/response-validation.md](docs/response-validation.md) |

If response validation cannot finish, the reply is preserved with a preface
explaining why.

The documentation cache can replay Claude's original fetch question across
projects and hosts. Disable `hook:docs-cache` before submitting sensitive questions.

### Instructions

Instructions supply automatic guidance, not tool denials. Their settings are
independent of similarly named skills.

| Setting | Default | Guidance |
| --- | --- | --- |
| `instruction:scope-exactly-what-asked` | Enabled | Keep work within the requested scope without introducing approval gates. [docs/guardrails.md#guidance-and-permission](docs/guardrails.md#guidance-and-permission) |
| `instruction:documentation-first` | Enabled | Use documentation-backed third-party APIs and behavior. [docs/configuration.md#feature-ids](docs/configuration.md#feature-ids) |
| `instruction:engineering-judgment` | Enabled | Apply coherent engineering decisions and the relevant specialist guidance. [docs/configuration.md#feature-ids](docs/configuration.md#feature-ids) |
| `instruction:writer-quality-guidance` | Enabled | Give autonomous implementers and fixers applicable standards, context reconciliation, and diff self-check guidance. [docs/configuration.md#feature-ids](docs/configuration.md#feature-ids) |

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
