# ioncache-ai-tools

Reusable guardrails and workflows for Claude Code, Codex, and GitHub Copilot CLI.

Requires Python 3.11+, Node.js, Git, and macOS or Linux.

## Install

### Claude Code

```text
/plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Choose user scope to enable it across projects. Manage updates and removal
through `/plugin`.

### Codex

```bash
codex plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
codex
```

Open `/plugins` to install it, then `/hooks` to review and trust its hooks.
Start a new thread.

Reinstall:

```bash
codex plugin add ioncache-ai-tools --marketplace ioncache-ai-tools
```

Remove:

```bash
codex plugin remove ioncache-ai-tools --marketplace ioncache-ai-tools
codex plugin marketplace remove ioncache-ai-tools
```

### GitHub Copilot CLI

```bash
copilot plugin install ioncache/ioncache-ai-tools
```

Start a new session after installing or updating.

Update: `copilot plugin update ioncache-ai-tools`.

Remove: `copilot plugin uninstall ioncache-ai-tools`.

This plugin targets Copilot CLI, not the cloud agent or VS Code.

## Guardrails

| Guard | Effect |
| --- | --- |
| Questions first | Blocks edits after a question until a subsequent non-question prompt |
| Documentation first | Reminds the agent to verify external API and tool details |
| Scope and current state | Reminds the agent to do only the requested work and check status before claiming it |
| Process termination | Blocks recognized process-kill commands until the rule is disabled |
| Lockfiles | Blocks direct edits; use the package manager |
| Worktrees | Directs creation through the setup-aware `create-worktree` skill |
| Punctuation | Fixes or rejects em-dashes |
| Graphify | Prefers an existing project knowledge graph for discovery |

While a question is pending, GraphQL calls with `operationName`, body files,
duplicate queries, or unrecognized options are blocked. Use one inline query.
Patches with ambiguous file-header whitespace are rejected.

### Documentation lookup cache

Claude Code, Codex, and Copilot CLI share short facts distilled from successful
documentation fetches. Claude uses `WebFetch`, Codex uses single-URL
`web.run` opens, and Copilot uses `web_fetch`.
A cache hit supplies the source URL and fetch date instead of downloading the
page again. Repeating the identical call bypasses that hit once and fetches live.
The documentation reminder permits reusing verified facts in the conversation
or a fresh cache hit when they cover the needed detail and version.

The cache lives at
`${XDG_CACHE_HOME:-~/.cache}/ioncache-ai-tools/docs-cache/`, shared across projects
and sessions across all three harnesses. A fact produced by any harness can be
reused by the others. Bypass and notification state remain separate per harness
and session.
The cache stores facts, not fetched pages. Facts expire after seven days, with
up to three facts per URL/chunk and a 20 MB entry budget.
Each summary is limited to 150 whitespace-separated words. Overlong output is
rejected and reported as a distiller failure, not truncated into partial facts.
URL metadata in new entries and log records omits userinfo, query strings, and
fragments. Cache keys still hash the full normalized URL. Existing files are
not scrubbed; clear the cache to remove previously stored URL metadata.

Copilot requests need an explicit positive `max_length`. Cached Copilot chunks
must start at the same offset and cover at least the requested length.
Claude answers and Codex excerpts are stored as reference-only summaries, not
as complete pages. URL-level requests can reuse those facts, with the original
Claude extraction question shown when present. The assistant must fetch live
if the facts do not answer the required detail.

Codex caches a single literal HTTP(S) URL opened from the beginning through its
local `web.run` tool (`webrun` in hook payloads). Searches, batched or mixed
operations, session-local reference IDs, and line continuations stay live.
Its hosted search path does not emit local tool hooks and is not intercepted.
Claude redirects and Codex results without an identifiable matching source
also stay uncached.
Raw HTML requests, failed or empty results, and volatile pages such as release
notes, changelogs, and `/latest` always fetch live. Cache faults leave normal
fetch permissions unchanged.

Distillation runs outside the main context through the originating harness's
CLI and login: Haiku for Claude, and `gpt-6-luna` with low reasoning effort for
Codex and Copilot. These jobs consume that harness's usage separately.
Their model choices are currently fixed in code.
Claude and Copilot distillers disable tools. Codex disables shell, web, and
native subagent tools and runs read-only, but can still expose utility tools.
The plugin suppresses its own adapters in distiller runs; update installed
copies too when testing with a live checkout.

Post-tool hooks supply distiller problems as context for the assistant's final
response, including in `--silent` mode. The stop hook requests a corrected answer
if it omits the notice, with at most two retries per distinct problem per session.
After that, the notice remains pending for post-tool delivery without further
stop blocks. A problem is marked as reported only after the current root response
contains it. Fetch permissions stay unchanged.
Inspect `events.jsonl` for misses, hits, bypasses, stores, and distiller outcomes;
`distill-status.json` holds the latest problem. Removing the cache's contents
resets it. The cache's storage limits do not govern the CLI's own session history.

## Workflows

Ask the assistant to use a skill by name.

| Skill | Purpose |
| --- | --- |
| [review-code](skills/review-code/SKILL.md) | Read-only code review |
| [review-dependabot-pr](skills/review-dependabot-pr/SKILL.md) | Read-only dependency-update review against actual project usage |
| [verify-unresolved-pr-comments](skills/verify-unresolved-pr-comments/SKILL.md) | Triage outstanding PR feedback without changing it |
| [post-pr-review-comments](skills/post-pr-review-comments/SKILL.md) | Draft and edit PR review comments in a pending review; never submit it |
| [write-pr-descriptions](skills/write-pr-descriptions/SKILL.md) | Write and edit human-focused PR titles and descriptions |
| [review-triage-loop](skills/review-triage-loop/SKILL.md) | Repeated read-only review with evidence-based triage and prioritized actions |
| [review-validate-fix-loop](skills/review-validate-fix-loop/SKILL.md) | Review, validate, fix, and re-review within set limits |
| [investigate](skills/investigate/SKILL.md) | Read-only investigation |
| [triage-errors](skills/triage-errors/SKILL.md) | Fix related failures by root cause |
| [create-worktree](skills/create-worktree/SKILL.md) | Create a worktree with repository setup applied |

The dependency review covers Dependabot, Renovate, and similar updates,
including grouped bumps and indirect dependencies. It compares package code
against project usage and checks environment drift without changing the PR.
Reviews can resume from a saved private run directory.

The review/triage loop keeps code and documents unchanged. It defaults to five
rounds. Configure the cap at invocation:
`review-triage-loop docs/architecture.md --max-rounds 8`.
Each round uses a fresh reviewer with a minimal assignment and prior findings.
The coordinator validates every candidate but reports only
worthwhile actions and consequential uncertainties. Two consecutive complete
rounds without new reportable information stop the run early.
Its private ledger retains suppressed findings and supports
`review-triage-loop --resume /absolute/private/run/REVIEW_LEDGER.md`.
Storage defaults to `~/.local/state/ioncache-ai-tools/review-triage-loop/`,
outside the reviewed tree. Counters and checkpoints are skill instructions,
not enforcement by the review/fix ledger helper.

The review/fix loop defaults to three review loops and three fix cycles per
loop. It supports resuming a run, but does not authorize commits, pushes, or PR
comments. Keep `.review-loop/` artifacts private: they can contain source.

### Review coordination

`review-code` uses shared criteria, role instructions, and evidence contracts:
[skills/review-code/CRITERIA.md](skills/review-code/CRITERIA.md),
[skills/review-code/ORCHESTRATION.md](skills/review-code/ORCHESTRATION.md), and
[skills/review-code/CONTRACTS.md](skills/review-code/CONTRACTS.md).

Small reviews stay inline when all evidence fits one direct read and no
substantial independent pass is needed. Explicit independence requests take
precedence. For substantial reviews, the invoking agent can delegate to a
fresh-context coordinator that collects specialists, validates their findings,
and returns one handback. If nested result collection is unsupported or
unverified, the invoking agent collects workers and uses a separate flat
adjudicator. Missing required independence blocks the review.

The invoking agent selects the coordinator model before launch. Worker
selections follow the same evidence-based policy, without shipped model names
or rankings. Explicit conversational role/model requests and harness settings
remain subject to host policy; the loop adds no model/effort flags. When
account discovery, suitability evidence, or permission to override is missing,
the instructions preserve configured defaults and disclose the limitation.
This fallback is not automatic runtime model selection.

The outer review/fix loop remains the only ledger writer and owns fixes and
limits. It adopts coordinator validation of specialist findings after checking
evidence completeness, independently validates coordinator-originated findings,
and maps the handback into the existing schema-1 protocol. Recoverable worker
failures stop as blocked, not automatically as terminal failures.

Standalone Git reviews run this from the consuming worktree:

```sh
python3 -B "/absolute/plugin/scripts/review_ledger.py" fingerprint
```

It returns the canonical root, snapshot ID, and file-hash manifest without
creating a ledger or storing source blobs.
Compare IDs before and after adjudication. Coverage is whole-worktree and
includes tracked and non-ignored untracked files, HEAD, index, and file modes.
Ignored files and `.review-loop/` are excluded; symlinks record target text,
not dereferenced content. Submodules and special files fail explicitly.

These shared instructions and mechanical checks are implemented, but supervised
launch-to-handback trials are still pending. No host-specific agent descriptors
or manifest migrations have been added. Nested/flat execution and automatic
model selection are not yet acceptance-verified on any host. Their rollout
remains gated by the trials in
[docs/review-orchestration-plan.md](docs/review-orchestration-plan.md).
The dependency-review and review/triage workflows keep their existing policies.

### `.worktree-setup.json`

Configure setup at the repository root. The worktree skill creates generic
defaults if the file is missing.

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

## Disabling a rule

Settings take effect on the next tool call, without reinstalling.

| Host | Global settings | Project settings |
| --- | --- | --- |
| Claude Code | `~/.claude/ioncache-ai-tools.local.json` | `.claude/ioncache-ai-tools.local.json` |
| Copilot CLI | `~/.copilot/ioncache-ai-tools.local.json` | `.github/copilot/ioncache-ai-tools.local.json` |
| Codex | `~/.codex/config.toml` | Project table in the same file |

For Claude Code or Copilot CLI:

```json
{ "disabledRules": ["never_kill_without_asking"] }
```

To re-enable it for one project, put this in that project's settings:

```json
{ "enabledRules": ["never_kill_without_asking"] }
```

For Codex:

```toml
[ioncache-ai-tools]
disabled_rules = ["never_kill_without_asking"]

[projects."/absolute/path/to/project".ioncache-ai-tools]
enabled_rules = ["never_kill_without_asking"]
```

`COPILOT_HOME` and `CODEX_HOME` override their respective global directories.
Codex's `--strict-config` rejects these custom tables. Ignore project-local
JSON settings in consuming repositories.

Within each host, project enables override disables. A rule disabled by any
host's settings is disabled across all three hosts.

Available IDs:

| ID | Guard |
| --- | --- |
| `never_kill_without_asking` | Process termination |
| `no-manual-lockfile-edit` | Lockfile edits through file tools |
| `no_manual_lockfile_edit_bash` | Lockfile edits through shell commands |
| `fix_emdash` | Em-dashes in edits and shell input |
| `block_raw_worktree_add` | Worktree creation outside the setup skill |
| `scope-exactly-what-asked` | Scope reminder |
| `verify-state-before-claiming` | Current-state reminder |

## Writing and coding skills

| Skill | Guidance |
| --- | --- |
| `answer-questions` | Answer questions before acting |
| `code-complexity` | Keep functions small and focused |
| `comments` | Explain why, not what; omit unnecessary comments |
| `documentation-writing` | Short, direct prose without filler or em-dashes |
| `prompt-output` | Format generated prompt files |
| `unit-tests` | Vitest test structure and conventions |
| `jsdoc` | JS/TS documentation conventions |
| `security` | Input validation, authentication, and secret handling |

Browse the [skills](skills/) for their instructions.

## Local development

Use Node.js 22.12.0+ and npm for contributor tooling:

```sh
npm ci
```

This installs commitlint and activates Husky's `commit-msg` hook. Repeat it in
each development checkout or worktree. This repository's `.worktree-setup.json`
runs it automatically for worktrees created through the setup helper.
Plugin users do not need these npm dependencies.

Commit messages and PR titles must follow Conventional Commits, for example
`fix: preserve hook permissions` or `feat(review): add draft comments`.
Generated merge, revert, and version messages are not exempt. Write reverts as
`revert: describe the reverted change`.

The `Commit conventions` workflow checks PR titles (including title edits),
PR commits, and commits pushed to `main`. It checks the entire reachable
history if a push has no available previous tip.

Local hooks can be bypassed. To block merges on CI failures, require the
`Commit conventions` status check on `main` in GitHub. Configure squash-only
merging, use PR titles for squash commit messages, and require linear history.
These are separate repository settings; this setup does not change them.
Editing a squash message can still introduce a bad message, which the push
check reports after it reaches `main`.

See [repository instructions](.github/copilot-instructions.md) for validation
commands. Refresh installed copies after source changes and start a new session
or thread. Rule-setting changes need neither.

Host-specific setup:
[Claude Code](https://code.claude.com/docs/en/plugins/loading),
[Codex](https://learn.chatgpt.com/docs/plugins),
[Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference).

## Limitations

These are guardrails, not a security boundary. Shell indirection and unsupported
tools can evade checks; host failures can prevent hooks from running. Agents
with write access to rule settings can disable them. Use your host's own
permissions for security-critical restrictions.
