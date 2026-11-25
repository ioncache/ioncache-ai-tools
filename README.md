# ioncache-ai-tools

A plugin for Claude Code, GitHub Copilot CLI, and Codex CLI. It provides
21 directly invocable skills for code review, PR work, investigation, writing,
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

**Response validation is currently Claude Code only** (2.1.332 or later).
It is off by default because it adds model usage and latency. When enabled,
it holds supported responses while a small model checks factual support and
rewrites overclaims before the text is displayed and recorded. If checking fails,
an unavailability notice replaces the draft without blocking further work.
See [docs/response-validation.md](docs/response-validation.md) for opt-in steps,
coverage, costs, and limitations.

This requires Claude's native plugin interface to hold and rewrite response
streams before display and conversation recording. Codex and Copilot currently
lack equivalent plugin interception covering every response, so this feature
does not run on those hosts.

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

Most skills take task context rather than fixed command-line flags. Review and
plugin-settings options are explicit skill arguments. Bare `review-code` invocation uses
defaults without a setup prompt.

## Skills

### Reviews and PR work

| Invocation in Claude/Copilot | What it does | What to provide |
| --- | --- | --- |
| `/ioncache-ai-tools:review-code` | Reviews code without applying fixes; with `--post-comments`, publishes the findings as one comment review on the PR | A file, directory, repository, branch, or PR; defaults to the active PR or branch changes |
| `/ioncache-ai-tools:review-dependabot-pr` | Checks dependency updates against actual project usage; reports without changing the PR | The Dependabot, Renovate, or other dependency-update PR; a saved run directory when resuming |
| `/ioncache-ai-tools:verify-unresolved-pr-comments` | Evaluates unresolved feedback and recommends fixes or responses; does not edit, post, resolve threads, or run tests | Invoke from the branch with the active PR |
| `/ioncache-ai-tools:post-pr-review-comments` | Drafts and edits review comments; prefers pending reviews for new inline threads and posts requested replies directly; never submits a review | The PR, findings or comments, and whether to draft, edit, reply, or post |
| `/ioncache-ai-tools:write-pr-descriptions` | Drafts or edits a PR title and description | The PR or branch and the requested drafting or editing task |
| `/ioncache-ai-tools:review-triage-loop` | Repeats read-only review and prioritizes findings without fixing them | An explicit target, optional round limit, or saved ledger |
| `/ioncache-ai-tools:review-validate-fix-loop` | Reviews, validates findings, edits code, and re-reviews within limits | A target and optional loop limits, or saved ledger; defaults to active PR or branch changes |

### Investigation and implementation

| Invocation in Claude/Copilot | What it does | What to provide |
| --- | --- | --- |
| `/ioncache-ai-tools:investigate` | Traces a feature or workflow and explains its behavior without editing files | The feature, workflow, or system to investigate |
| `/ioncache-ai-tools:triage-errors` | Groups failing checks by root cause and fixes each group | The failing command and relevant error context |
| `/ioncache-ai-tools:create-worktree` | Creates a git worktree and applies the repository's setup configuration | Worktree arguments, such as `-b feature-name ../feature-name` |
| `/ioncache-ai-tools:plugin-settings` | Lists or changes plugin settings across all three hosts | No arguments to list; `--<setting-id>=enabled` or `=disabled`; optional `--global` |
| `/ioncache-ai-tools:autonomous-development` | Prepares approved plans and coordinates bounded implementation toward review-ready PRs | An idea, artifact references, an approved manifest, or a private run directory |

### Writing and engineering guidance

Invoke these with the task or files you want the guidance applied to. They
provide standards for the requested work, not standalone test or audit tools.

| Invocation in Claude/Copilot | Guidance |
| --- | --- |
| `/ioncache-ai-tools:engineering-judgment` | Choose coherent solutions across affected code while honoring scope limits |
| `/ioncache-ai-tools:code-complexity` | Keep functions cohesive; evaluate size, nesting, and parameter counts |
| `/ioncache-ai-tools:comments` | Keep implementation comments purposeful and preserve native API documentation |
| `/ioncache-ai-tools:documentation-writing` | Write direct documentation with clear sentences and standard punctuation |
| `/ioncache-ai-tools:prompt-output` | Format a requested prompt as one copyable Markdown code block |
| `/ioncache-ai-tools:unit-tests` | Write or review unit tests using the target language and framework |
| `/ioncache-ai-tools:jsdoc` | Write or review JavaScript JSDoc, not TypeScript or other languages |
| `/ioncache-ai-tools:security` | Apply input-validation, authentication, and secret-handling standards |
| `/ioncache-ai-tools:answer-questions` | Inspect the answer-only question policy; not required before asking ordinary questions |

Full skill instructions are in [skills/](skills/).

Reviews name unresolved material findings under **Known issues not fixed here**,
including pre-existing and out-of-scope defects. Autonomous development carries
that list into its final report and PR, and can create or reuse follow-up issues
when separately approved. Ticket failures do not stop development.
See [skills/autonomous-development/FOLLOW_UPS.md](skills/autonomous-development/FOLLOW_UPS.md)
for publication and disclosure rules.

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

Reviews provide 12 independently enabled categories across the requested
scope: security, complexity, comments, JSDoc, unit-test quality, documentation,
design coherence, correctness, integration, privacy, performance and test coverage.
Project-specific purposes add workers; same-purpose project requirements override
defaults within their scope. Small changes do not permit inline or bundled checks.
Coordination, integration review, and adjudication stay separate.
The default strategy uses isolated specialists; `sweep-first` changes their
order, not the required tasks or context isolation.

General categories adapt to the actual stack even without a dedicated guide.
Language-specific workers require source evidence: JSDoc runs only when
JavaScript is in scope. TypeScript-only and other JavaScript-free targets retain
general documentation and contract review without a JSDoc worker.
Unknown language facts leave coverage unresolved while other work continues.
Workers verify remaining file-level applicability; predicted usefulness cannot
remove a category.
Independent `review-<category>` settings control shipped coverage, separately
from writing-skill settings. With no extra project categories, a default flat
phase starts with 12 workers without JavaScript or 13 with it, including
adjudication, before retries, validators or capacity shards.
See [docs/configuration.md](docs/configuration.md).

Role effort, validator, fallback, and strategy options are listed in
[skills/review-code/OPTIONS.md](skills/review-code/OPTIONS.md). The review/fix loop
accepts the same review options; they do not change its fixing model.
Use `$ioncache-ai-tools:review-code --help` in Codex. Claude can show argument
hints; `--help` is the portable option list, not a promised cross-host picker.

## Autonomous development

This skill is user-invoked only, never automatically selected for matching tasks.
Invoke `/ioncache-ai-tools:autonomous-development` in Claude/Copilot, or
`$ioncache-ai-tools:autonomous-development` in Codex. Choose planning, design,
and execution destinations independently. Review and approve the plan, content
snapshots, permissions, and finite limits before execution.

The initial execution adapter uses Python-generated Claude Workflow batches,
fresh workers, private durable state, per-task and full-PR reviews, and
human-controlled PR merging. The skill prepares and claims each generated script;
do not invoke the `/ioncache-ai-tools:autonomous-development-run` template directly.
Python reads and validates report files instead of accepting model-relayed state.
Copilot and Codex currently support preparation and state inspection only.
Use the exact execution provider `claude-workflows`. The adapter applies
resolved native role models/efforts, with explicit overrides and separate
requested/observed model records. Independent review leaves run concurrently;
fixers remain sequential. Recovery preserves work and consumed allowances;
stopping a run does not roll back its implementation.

Implementers and fixers receive the same applicable standards as reviewers,
plus surrounding-context and diff self-check guidance. Reports include explicit
role contracts and a read-only precheck; exhausted report corrections have one
evidence-based recovery without repeating work. An unchanged reviewed patch can
recover after a target-branch rebase without spending another review.
See [skills/autonomous-development/RECOVERY.md](skills/autonomous-development/RECOVERY.md).

Offline checks establish only the controller and adapter contracts they
exercise. They do not establish native permissions, worker launch, result
delivery or cancellation on a given host. Execution establishes those from the
selected host's evidence and reports any not yet established as deferred; see
[skills/autonomous-development/WORKERS.md](skills/autonomous-development/WORKERS.md).
Neither establishes cloud operation or shared team controls, which the consuming
environment must provide.
Authorization you already gave needs no separate trial approval or trial budget;
see Prepare step 6 in
[skills/autonomous-development/SKILL.md](skills/autonomous-development/SKILL.md).

The launcher supplies the private store path and a cross-session monitor:

```sh
python3 "/absolute/plugin/scripts/development_run.py" watch "/private/development-run"
```

It reports assignment and review progress, stopped outcomes and inactivity
without changing the run. Worktrees may follow the project's sibling-directory
convention; the private store must remain separate from every worktree.

When approved, runs automatically publish a readable process audit in the modified
repository's wiki. The final audit updates the initial page in place, retaining
older versions in wiki history. Runs update the newest-first
`Automated-Pull-Request-Audits` table, and add report/data/index links to the PR
body. The wiki must already be initialized and writable. No audit branch or
manual upload is used. Private inputs and raw reports stay local. The public narrative
requires publication review. Set `autonomous-development-audit` to `false` to
disable this independently. See [skills/autonomous-development/AUDIT.md](skills/autonomous-development/AUDIT.md).

Preparation weighs PR slicing, feature flags and optional child issues with
[skills/autonomous-development/PLANNING.md](skills/autonomous-development/PLANNING.md).
Set `autonomous-development-incremental-planning` to `false` to keep the
baseline planning step instead.

Usage and recovery: [skills/autonomous-development/SKILL.md](skills/autonomous-development/SKILL.md).
Manifest fields: [skills/autonomous-development/CONTRACT.md](skills/autonomous-development/CONTRACT.md).
Set `autonomous-development` to `false` in the feature configuration to disable
execution while retaining status and interruption commands.

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
/ioncache-ai-tools:review-validate-fix-loop --resume /absolute/private/reviews/<worktree-identity>/<run-id>/REVIEW_LEDGER.json
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

Hooks run without a skill invocation. Scope supplies guidance, not task
approvals. Native host permissions still apply.

Question guidance asks for direct answers without unrequested work. Claude,
Copilot, and Codex use local native message evidence to restrict recognized
state changes during a verified user-question turn. Running children remain unrestricted, and their
question-shaped assignments and replies do not restrict the main session.
The next instruction releases the restriction. Unknown-origin prompts,
older host formats, and unavailable history receive guidance without a tool fence. See
[docs/guardrails.md#question-turns](docs/guardrails.md#question-turns).

Action checks block direct lockfile edits, broad process termination, and raw
worktree creation. Recovery uses the package manager, an exact owned process
target, or the setup helper respectively, without a plugin approval exchange.
Checks also fix or reject em-dashes in file edits and shell input.

Guidance covers scope, answer content, documentation-backed
research, and engineering judgment. Hooks do not use model reviews to judge
authorization or reply content. Checker failures report unavailability rather
than stopping the worker or granting host permission.
The documentation cache reuses facts from supported documentation fetches.
**Cache distillation makes additional model calls and consumes the host's
usage.** Disable `docs-cache` to opt out.

## Configuration

Shipped guards and skills are enabled by default. Response validation is the
exception: it is off by default to avoid extra model usage and latency.

### Using plugin settings

Run `/ioncache-ai-tools:plugin-settings` to manage settings without editing JSON.
In Claude Code with mods enabled, it opens a native settings pane. Otherwise,
the same command prints the grouped settings listing. Copilot and Codex use
the text interface.

In the pane, choose Project or Global, then select a setting to toggle it.
Changes save immediately across Claude, Copilot, and Codex; global changes
preserve project overrides. Use Tab and Enter to navigate, Page Up/Down to
scroll, and Esc to close.

Use `--list` to request text even when the pane is available. Setting flags also
use the text interface:

```text
/ioncache-ai-tools:plugin-settings
/ioncache-ai-tools:plugin-settings --list
/ioncache-ai-tools:plugin-settings --hook:answer-questions=disabled
/ioncache-ai-tools:plugin-settings --hook:answer-questions=enabled
/ioncache-ai-tools:plugin-settings --skill:review-code=disabled --hook:docs-cache=disabled
/ioncache-ai-tools:plugin-settings --instruction:documentation-first=enabled
/ioncache-ai-tools:plugin-settings --autonomous-development:audit=disabled
/ioncache-ai-tools:plugin-settings --global --review:comments=enabled
```

In Codex, use `$ioncache-ai-tools:plugin-settings` with the same arguments.
The listing separates Hooks, Instructions, Autonomous development, Reviews,
and Skills. `hook:` controls automatic checks or services; `instruction:`
controls guidance only; `skill:` controls skill availability. Related workflow
settings use `autonomous-development:<setting>` and `review:<setting>`.
Use the displayed names as flags; existing JSON keys stay unchanged.

Changes default to the current project and apply across all three hosts.
`--global` changes global values, preserving project overrides and showing
their effective result. Opening the pane or listing settings does not change
preferences; `--help` lists flags. `hook:plugin-settings-ui` independently
disables the pane, making the same command fall back to text.

### Editing settings manually

The pane and skill manage these files, which can also be edited directly:

| Host | Global settings | Project settings |
| --- | --- | --- |
| Claude Code | `~/.claude/ioncache-ai-tools.local.json` | `.claude/ioncache-ai-tools.local.json` |
| Copilot CLI | `~/.copilot/ioncache-ai-tools.local.json` | `.github/copilot/ioncache-ai-tools.local.json` |
| Codex CLI | `~/.codex/ioncache-ai-tools.local.json` | `.codex/ioncache-ai-tools.local.json` |

Use the JSON keys from [config/defaults.json](config/defaults.json), not the
CLI names. For example, `hook:docs-cache` maps to `docs-cache` in JSON, while
`skill:review-code` keeps its prefix. To disable both:

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
