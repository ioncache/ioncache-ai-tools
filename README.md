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
| Answer-only questions | Blocks recognized mutations for the whole question turn; checks replies for unsolicited work |
| Documentation first | Checks third-party specifics against observed documentation, including applicable cached facts |
| Scope and current state | Checks mutation scope and claims against the request and current-turn observations |
| Process termination | Blocks recognized process-kill commands until the rule is disabled |
| Lockfiles | Blocks direct edits; use the package manager |
| Worktrees | Directs creation through the setup-aware `create-worktree` skill |
| Punctuation | Fixes or rejects em-dashes |
| Graphify | Gates code discovery on a graph query when the project has a graph; permits bounded failure fallback |

While a question is pending, GraphQL calls with `operationName`, body files,
duplicate queries, or unrecognized options are blocked. Use one inline query.
Patches with ambiguous file-header whitespace are rejected.

### Context and turn enforcement

Ordinary prompts add no built-in reminder text after initialization.
Question turns add a 204-character answer-only contract, not a request to
reload a skill. The default bootstrap is 635 characters and runs at session
initialization, context recovery, and supported subagent startup. If a host
misses startup, the first prompt supplies it. Copilot adds a 43-character
wrapper only when a transformed prompt actually has context to append.
These counts exclude host formatting and tokens.

| Prompt | Previous shared payload | New routine payload |
| --- | ---: | ---: |
| Ordinary, no graph | 1,141 characters | 0 characters |
| Ordinary, graph present | 1,334 characters | 0 characters |
| Question, no graph | 1,641 characters | 204 characters |
| Question, graph present | 1,834 characters | 204 characters |

`turn_guard.py` records requests, assistant proposals, bounded tool observations,
documentation and decisions outside the conversation. Assistant proposals
provide context for later approval; they do not authorize work themselves.
It reuses `EvidenceStore` under
`~/.cache/ioncache-ai-tools/claim-evidence/`, with a separate `turn-policy`
namespace. It does not activate the experimental claim-evidence checkpoint
workflow. These private records can contain source and tool output.
Session end discards live observations and review decisions but retains request
context and applicable documentation for resume. A clear resets the active
request. Older request history and large observations are bounded; omitted
content is not treated as verified evidence.

Questions retain the conservative classifier: a question mixed with an
instruction still blocks recognized mutations. The work-product exception
permits requested drafts or code in the answer, not subsequent file edits.
Native Stop corrections from this plugin preserve the original question,
request, and retry budget. Other plugins' synthetic prompts cannot always be
distinguished from new user messages.
Copilot records a separate pending-prompt fence before its fallible prompt
handlers run. A failed update blocks mutations and delegation until a genuine
request is recorded successfully; old correction feedback cannot clear it.
This fence survives session end and resume. It cannot cover a hook that never
starts or cannot establish the fence.

Claude's `MessageDisplay` hook silently records streamed text without changing
the display or running a model. Copilot retains root assistant prose across
tool calls through the exact current Stop event. Missing batches, truncated
text and final-message-only inputs are reported as incomplete coverage, not a
successful whole-turn check. Codex supplies the final message only: its hook
documentation explicitly describes the transcript format as unstable, so the
plugin does not parse it. Earlier prose is checked for question and scope
violations; later evidence cannot retroactively verify earlier live-state claims.

Compaction preserves the active request and hard question gate. Claude and
Codex recover context through `SessionStart`. Copilot recovers on the next
post-tool event, once, without waiting for another prompt. If no tool completes,
context recovery waits for the next prompt; the stored gates still apply.

Graph gating recognizes discovery tools and source reads. A successful query
unlocks source inspection for that turn and graph snapshot. A failed query
permits source fallback. An unavailable graph or executable produces one explanatory denial,
then permits ordinary discovery on retry. Echoing a command, reading help, or
querying a different graph does not satisfy the gate. This is a common-action
guard, not an exhaustive shell interpreter or proof of query relevance.

**Semantic checks make additional model calls and consume the host's usage.**
`turn_review.py` invokes the same host's CLI for recognized mutations,
delegations, follow-up agent messages and responses. It does not select a model: the isolated CLI's default
applies. Claude and Copilot have no tools; Codex disables shell, web and native
subagents in read-only mode but may expose utility tools. Runs suppress this
plugin's hooks and execute outside the consuming repository. Claude disables
customizations; Copilot disables custom instructions; Codex ignores user config.
The host login must work independently in noninteractive mode.

The checker receives the actual request, candidate and observed evidence,
including resource identifiers, fetch ages, versions when present, failures and
truncation. It may reuse applicable documentation, but must not use an older
observation to certify live state. Mutations invalidate live observations across
all actors in the session, including parent observations after child writes.
Tool starts and completions are correlated by native IDs or an unambiguous
tool/input key. File snapshots taken before and after a read detect changes
during the read as well as later changes. Unmatched or ambiguous reads cannot
certify current state. Explicit child startup or resume binds the child to the
current parent request; an old worker cannot silently inherit new authority.
Identical semantic decisions are cached until the candidate, request or
evidence changes. Operational failures are not cached as semantic denials.

Each model call has a 60-second deadline and a 90,000-byte input budget.
Tool inputs and results are bounded together with their evidence records.
Older context can be omitted to fit the combined budget, with explicit omission
metadata. The latest request and proposed candidate are never silently cut.
Private review payloads travel over stdin, not process arguments.
Timeouts and catchable cancellation terminate and reap the reviewer process
group. Cleanup cannot run after an uncatchable kill of its supervising hook.
Final-response review makes at most two model calls per user turn, even if
another hook triggers further continuations. Exhausted budgets and unavailable
turn state produce warnings, not unreviewable correction loops.
An unavailable or malformed reviewer denies a recognized mutation without
granting permission. Documentation research stays available. A failed final
check requests at most one correction per user turn. Further failure produces
a user-facing warning and records an unverified result, not a successful check.
There is no portable root-response replacement or hard final-stop mechanism
across all three hosts. Checks cannot retract streamed prose or undo actions
that already ran. Semantic judgments can be wrong.

The main conversation gets only bootstrap/turn context and specific denial or
correction feedback. This reduces accumulating context, not necessarily total
model usage or latency. The isolated CLI can retain its own session history;
Copilot does not provide the ephemeral mode used for Claude and Codex here.
Host tool coverage also limits observation: Codex hosted search bypasses local
tool hooks, and Copilot's built-in general-purpose agent has no subagent
start/stop events. Identified child tool events initialize child state when
startup omitted the identity. Anonymous child stops warn without consuming the
parent's review budget. Unobserved activity is not a verified receipt.

Hook contracts and CLI isolation options were checked against:

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/hooks#messagedisplay
- https://code.claude.com/docs/en/sub-agents#resume-subagents
- https://code.claude.com/docs/en/cli-reference
- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://docs.github.com/en/copilot/reference/hooks-reference
- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
- https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically
- https://github.com/github/copilot-sdk/blob/main/docs/features/streaming-events.md
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents/send_input.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents/resume_agent.rs

### Documentation lookup cache

Claude Code, Codex, and Copilot CLI share short facts distilled from successful
documentation fetches. Claude uses `WebFetch`, Codex uses single-URL
`web.run` opens, and Copilot uses `web_fetch`.
A cache hit supplies the source URL and fetch date instead of downloading the
page again. Repeating the identical call bypasses that hit once and fetches live.
The documentation policy permits reusing verified facts in the conversation
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

Post-tool and Stop hooks emit a diagnostic once per distinct problem and
harness/session, until notification-state expiry. Claude and Codex use
`systemMessage`; Copilot uses display-only progress output. Diagnostics do not
become model context, force answer rewrites, or require unrelated prose in a
question's answer. Silent or noninteractive host interfaces can suppress UI
warnings; inspect the persistent status and event files in that case.
Fetch permissions stay unchanged.
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
| `scope-exactly-what-asked` | Startup scope policy and semantic scope check |
| `verify-state-before-claiming` | Startup state policy and live-state claim check |

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
