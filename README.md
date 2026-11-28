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

In Claude Code, `plugin-settings` opens an interactive settings UI for viewing
and changing settings. Copilot and Codex show a grouped text list instead.
Claude also uses the text list if the UI is disabled or unavailable.

Enter these commands in your assistant using the invocation syntax described below:

| Invocation | Guidance |
| --- | --- |
| `/ioncache-ai-tools:plugin-settings` | Inspect or change plugin settings |
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

Code reviews assess reports as they arrive, then merge the findings. They do
not install dependencies or routinely rerun suites; targeted checks use isolated
copies and existing dependencies. Use `/ioncache-ai-tools:review-code --checks source`
for source-only review. Configure `review:incremental-adjudication` and
`review:targeted-checks` independently through the plugin's settings skill.
Every review shows a compact runtime summary. Add `--run-details` for per-agent
durations, a timeline, and recorded waits; missing measurements stay explicit.

### Skills

Invoke a skill with the task or files you want it to work on. Related skills
are grouped below. Each row links to arguments, defaults, and their meanings.
Task arguments are plain-language context; only some skills accept fixed flags.

Model-driven skills consume normal conversation tokens. The token-usage notes
identify additional model calls, repeated review passes, and context overhead.

#### Reviews and PR work

| Invocation | Default | Guidance |
| --- | --- | --- |
| `/ioncache-ai-tools:review-code` | Enabled | Review files, branches, repositories, or PRs without fixes; defaults to the active PR or branch changes.<br><br>Arguments (target, review and posting flags): [Argument details](docs/skill-arguments.md#review-code).<br><br><strong>Token usage:</strong> Separate specialist reviewers and adjudication add model calls. Large reviews and additional validation passes can be token-heavy. |
| `/ioncache-ai-tools:review-dependabot-pr` | Enabled | Check dependency-update PRs against actual usage without changing them.<br><br>Task arguments (PR or saved run): [Argument details](docs/skill-arguments.md#review-dependabot-pr).<br><br><strong>Token usage:</strong> May launch separate package-review workers. Usage grows with the number of dependencies and the analysis each requires. |
| `/ioncache-ai-tools:verify-unresolved-pr-comments` | Enabled | Evaluate active-PR feedback without editing, posting, resolving threads, or running tests.<br><br>No arguments; uses the current branch's PR: [Argument details](docs/skill-arguments.md#verify-unresolved-pr-comments).<br><br><strong>Token usage:</strong> Using an agent-backed PR integration adds model calls; direct API retrieval does not require a separate reviewer. |
| `/ioncache-ai-tools:post-pr-review-comments` | Enabled | Draft or edit comments and post requested replies; never submit a review.<br><br>Task arguments (PR, findings, requested action): [Argument details](docs/skill-arguments.md#post-pr-review-comments).<br><br><strong>Token usage:</strong> Separate correctness and clarity reviewers add model calls before presentation or posting. Revised comments can require repeated checks. |
| `/ioncache-ai-tools:write-pr-descriptions` | Enabled | Draft or edit a PR title and description.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#write-pr-descriptions). |
| `/ioncache-ai-tools:review-triage-loop` | Enabled | Repeat read-only review and prioritize findings.<br><br>Arguments (target, round limit, resume): [Argument details](docs/skill-arguments.md#review-triage-loop).<br><br><strong>Token usage:</strong> Each round starts a fresh reviewer and repeats analysis. Round limits are not token or spending caps. |
| `/ioncache-ai-tools:review-validate-fix-loop` | Enabled | Review, validate, fix, and re-review within limits; never commit or push.<br><br>Arguments (target, loop limits, resume, review flags): [Argument details](docs/skill-arguments.md#review-validate-fix-loop).<br><br><strong>Token usage:</strong> Repeated specialist reviews, validation, and fix cycles can be token-heavy. Loop limits are not token or spending caps. |

#### Investigation and implementation

| Invocation | Default | Guidance |
| --- | --- | --- |
| `/ioncache-ai-tools:investigate` | Enabled | Explain an existing feature or workflow without editing files.<br><br>Task argument (topic to trace): [Argument details](docs/skill-arguments.md#investigate). |
| `/ioncache-ai-tools:triage-errors` | Enabled | Group failing checks by root cause and fix them.<br><br>Task arguments (failing command and errors): [Argument details](docs/skill-arguments.md#triage-errors). |
| `/ioncache-ai-tools:create-worktree` | Enabled | Create a git worktree with repository setup applied; requires Node.js 22.12.0+.<br><br>Arguments (destination and Git worktree options): [Argument details](docs/skill-arguments.md#create-worktree). |
| `/ioncache-ai-tools:plugin-settings` | Enabled | Inspect or change plugin settings across all three hosts.<br><br>Arguments (listing, scope, and setting flags): [Argument details](docs/skill-arguments.md#plugin-settings). |
| `/ioncache-ai-tools:context-handoff` | Enabled | Write a portable handoff with the current task, decisions, and user instructions without stopping workers.<br><br>Task argument (optional destination): [Argument details](docs/context-handoff.md#use). |
| `/ioncache-ai-tools:autonomous-development` | Enabled | User-invoked only: plan approved work and coordinate bounded implementation toward review-ready PRs. Execution requires Claude Workflows; other hosts support preparation and inspection.<br><br>Task arguments (idea, artifacts, or saved run): [Argument details](docs/skill-arguments.md#autonomous-development).<br><br><strong>Token usage:</strong> Execution launches multiple workers and review rounds and can be token-heavy. Approved task and review limits are not spending caps. |

Review and approve the autonomous-development plan, content, permissions, and
limits before execution. PR merging stays under human control.

#### Writing and engineering guidance

These skills apply standards to the requested work. They are not standalone
test or audit tools.

| Invocation | Default | Guidance |
| --- | --- | --- |
| `/ioncache-ai-tools:engineering-judgment` | Enabled | Choose coherent solutions while honoring scope.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#engineering-judgment). |
| `/ioncache-ai-tools:code-complexity` | Enabled | Keep functions cohesive and control nesting and parameter counts.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#code-complexity). |
| `/ioncache-ai-tools:comments` | Enabled | Keep implementation comments purposeful and preserve API documentation.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#comments). |
| `/ioncache-ai-tools:documentation-writing` | Enabled | Write direct documentation with clear sentences and standard punctuation.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#documentation-writing). |
| `/ioncache-ai-tools:prompt-output` | Enabled | Format a requested prompt as one copyable Markdown code block.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#prompt-output). |
| `/ioncache-ai-tools:unit-tests` | Enabled | Write or review tests using the target language and framework.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#unit-tests). |
| `/ioncache-ai-tools:jsdoc` | Enabled | Write or review JavaScript JSDoc, not TypeScript or other languages.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#jsdoc). |
| `/ioncache-ai-tools:security` | Enabled | Apply input-validation, authentication, and secret-handling standards.<br><br>Task arguments: [Argument details](docs/skill-arguments.md#security). |

### Hooks

Hooks run automatically, without a skill invocation. They guard common tool
actions and provide background services. A denied action includes an allowed
alternative so the agent can continue; native host permissions still apply.
The names below are settings, not commands to invoke.

#### Automatic guardrails

| Setting | Default | Guidance |
| --- | --- | --- |
| `hook:answer-questions` | Enabled | Keep verified user-question turns answer-only for that root agent; running children remain unrestricted.<br><br>[Documentation details](docs/guardrails.md#question-turns) |
| `hook:autonomous-development:explicit-only` | Enabled | Prevent automatic skill-tool activation of autonomous development; require direct user invocation.<br><br>[Documentation details](docs/configuration.md#settings-command) |
| `hook:block_raw_worktree_add` | Enabled | Block raw worktree creation and direct the agent to the configured setup helper.<br><br>[Documentation details](docs/guardrails.md#action-checks-and-autonomous-recovery) |
| `hook:no-manual-lockfile-edit` | Enabled | Block direct lockfile edits through file tools; use the package manager instead.<br><br>[Documentation details](docs/guardrails.md#action-checks-and-autonomous-recovery) |
| `hook:no_manual_lockfile_edit_bash` | Enabled | Block recognized shell commands that directly edit lockfiles.<br><br>[Documentation details](docs/guardrails.md#action-checks-and-autonomous-recovery) |
| `hook:no_broad_process_kill` | Enabled | Block broad process termination; use an exact owned process target or native stop control.<br><br>[Documentation details](docs/guardrails.md#action-checks-and-autonomous-recovery) |
| `hook:fix_emdash` | Enabled | Rewrite em-dashes in structured file edits and reject them in shell input or patch additions.<br><br>[Documentation details](docs/guardrails.md#action-checks-and-autonomous-recovery) |

#### Automatic services

| Setting | Default | Guidance |
| --- | --- | --- |
| `hook:context-handoff` | Enabled | Preserve task-focused context during Claude Code 2.1.332+ native compaction without stopping workers for `/clear`.<br><br>[Documentation details](docs/context-handoff.md).<br><br><strong>Token usage:</strong> Native compaction consumes model tokens. The plugin adds instructions to that operation without launching a separate model. |
| `hook:docs-cache` | Enabled | Reuse fetched documentation facts.<br><br>[Documentation details](docs/documentation-cache.md).<br><br><strong>Token usage:</strong> Fact distillation runs outside the conversation and makes additional model calls, consuming host tokens. |
| `hook:plugin-settings-ui` | Enabled | Open the native Claude settings pane when available; keep the text interface available otherwise.<br><br>[Documentation details](docs/configuration.md#native-claude-settings-pane) |
| `hook:response-validation` | Disabled | Check factual support and rewrite overclaims before delivery in Claude Code 2.1.332+ only.<br><br>[Documentation details](docs/response-validation.md).<br><br><strong>Token usage:</strong> Token-heavy because each textual response adds a model review, so it is disabled by default. |

If response validation cannot finish, the reply is preserved with a preface
explaining why.

The documentation cache can replay Claude's original fetch question across
projects and hosts. Disable `hook:docs-cache` before submitting sensitive questions.

### Instructions

Instructions supply automatic guidance, not tool denials. Their settings are
independent of similarly named skills.

| Setting | Default | Guidance |
| --- | --- | --- |
| `instruction:scope-exactly-what-asked` | Enabled | Keep work within the requested scope without introducing approval gates.<br><br>[Documentation details](docs/guardrails.md#guidance-and-permission) |
| `instruction:documentation-first` | Enabled | Use documentation-backed third-party APIs and behavior.<br><br>[Documentation details](docs/configuration.md#feature-ids) |
| `instruction:engineering-judgment` | Enabled | Apply coherent engineering decisions and the relevant specialist guidance.<br><br>[Documentation details](docs/configuration.md#feature-ids) |
| `instruction:writer-quality-guidance` | Enabled | Give autonomous implementers and fixers applicable standards, context reconciliation, and diff self-check guidance.<br><br>[Documentation details](docs/configuration.md#feature-ids).<br><br><strong>Token usage:</strong> Adds standards and context guidance to each applicable worker's prompt, increasing input tokens without launching a separate reviewer. |

## Known issues and limits

| Situation | What to know or do |
| --- | --- |
| A skill is missing | Check that the plugin is installed and enabled in your CLI, then restart the CLI to reload its skills. A personal or project skill with the same name can hide this plugin's version.<br><br>See [skill discovery details](docs/workflows.md#skill-discovery) for how to resolve that conflict. |
| An action is denied | An attempted command or edit matched a plugin rule. The assistant should use the alternative shown in the rejection message, such as updating a dependency lockfile through the package manager instead of editing it by hand. Repeating the same blocked operation will not help. Your CLI may still ask for permission to run the replacement command. |
| A checker is unavailable | The plugin could not run a check, for example because its settings could not be read. This is an error, not a verdict that your request is forbidden or safe to perform. The assistant can repair the reported problem or continue other work; remaining checks and normal CLI permissions still apply.<br><br>See [checker failure details](docs/guardrails.md#checker-failures). |
| Review coordination | Reviews split work among several AI reviewers. Starting those reviewers, selecting their models, and collecting their results have not yet been fully tested together in real sessions on the supported CLIs. A run missing required review results is incomplete, even if none of the finished checks found problems.<br><br>See [review coordination details](docs/workflows.md#review-coordination). |
| Response punctuation | The em-dash rule checks commands and file edits, not chat replies. Enabling `hook:fix_emdash` therefore does not guarantee that the assistant's answers will be free of em-dashes. |
| Copilot child `/tmp` writes | A separate AI worker launched by Copilot can refuse to create temporary files under `/tmp`, even when the main assistant can write there. This has also happened with the plugin disabled and all tool permissions allowed, so changing those settings is not a confirmed fix.<br><br>Follow [github/copilot-cli#5441](https://github.com/github/copilot-cli/issues/5441) for updates. |

These guardrails are **not a security boundary**. Unsupported tools and shell
indirection can evade checks; agents with settings access can disable them.
Keep the host's own permissions enabled for security-critical restrictions.
