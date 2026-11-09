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

### Synchronize settings

The shipped `config/defaults.json` is the complete enabled-by-default catalog.
After installing or updating, run this from the installed plugin directory,
using your host name (`claude`, `copilot`, or `codex`):

```sh
python3 hooks/scripts/plugin_config.py copilot --project /absolute/path/to/project
```

This preserves existing values, adds new settings, and removes retired settings.
Hooks run the same reconciliation before use, so the first session after an
install/update also synchronizes. There is no shared native installer callback:
installation alone does not run the command. No plugin reinstall is needed
when editing settings. See [README.md#configuration](README.md#configuration).

## Guardrails

| Guard | Effect |
| --- | --- |
| Answer-only questions | Blocks recognized mutations for the whole question turn; checks replies for unsolicited work |
| Documentation first | Supplies documentation-first guidance; does not verify claims |
| Engineering judgment | Prefers coherent system behavior over the shortest patch |
| Scope | Checks recognized mutations, delegation and response work products against the user's authorization |
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
reload a skill. The bootstrap includes enabled policies and disabled-skill
instructions, and runs at
session initialization, context recovery, and supported subagent startup.
If a host misses startup, the first prompt supplies it. Copilot adds a 43-character
wrapper only when a transformed prompt actually has context to append.
These counts exclude host formatting and tokens.

| Prompt | Previous shared payload | New routine payload |
| --- | ---: | ---: |
| Ordinary, no graph | 1,141 characters | 0 characters |
| Ordinary, graph present | 1,334 characters | 0 characters |
| Question, no graph | 1,641 characters | 204 characters |
| Question, graph present | 1,834 characters | 204 characters |

`scope_guard.py` records requests, assistant proposals, question-tool exchanges,
and scope decisions outside the conversation. Assistant proposals
provide context for later approval; they do not authorize work themselves.
It reuses `EvidenceStore` under
`~/.cache/ioncache-ai-tools/claim-evidence/`, with a separate `scope-policy`
namespace. The directory name is historical: active hooks do not load the
claim checker or collect file snapshots, shell receipts, or documentation evidence.
These private records can contain user requests and assistant text.
Session end discards review decisions but retains request context for resume.
A clear resets the active request. Older request history is bounded; omitted
content cannot establish authorization.
Assistant history reserves space for the final response, then retains recent
messages within the remaining budget. A separate bounded recent-message buffer
preserves proposals after long research without replacing the earlier-prose audit
buffer. Each retained message records its own completeness; omitting older prose
does not make a complete recent proposal unusable for later approval.

Question-tool proposals and returned answers have their own bounded context.
Complete exchanges up to 16,000 serialized characters survive mutations,
compaction and resume.
Larger exchanges retain explicitly truncated excerpts; retained exchanges share
a 32,000-character budget, with omissions marked. Successful tool execution is
not consent: refusals and unavailable-user replies remain visible. Matching
tool starts and completions establish provenance, not permission. New user
restrictions still control, and clearing the session clears this context.
These exchanges do not bypass the semantic check or host permissions.

Copilot also recovers lost scope and question-tool exchanges from the native
transcript path supplied at root Stop. Recovery checks the session header,
matches the exact Stop invocation, and pairs native `ask_user` starts and
completions. Answers use native detailed output when available; text omitted
by the host cannot establish permission. Prompt-hook inputs provide request
context. Other message text cannot grant permission, and conflicting restrictions
cannot be silently discarded. Reading alleged approval through Bash or a file
tool is not recovery.

The recovered dialogue stays separate from ordinary request history and survives
mutations, compaction and resume. Newly observed requests and answers extend it,
so later restrictions remain visible even after ordinary request-history eviction.
Recovery retains the whole chronological dialogue or none of it: its limit is
48,000 serialized characters, with a 64 MiB transcript, 8 MiB event and
two-second scan limit. Combined reviewer-budget pressure can also omit it as a
whole. Missing, unsafe, mismatched or incomplete history never supplies partial
permission. A clear discards recovery and prevents restoring the old transcript.

Recovery becomes available after Stop, not before the first blocked edit after
an upgrade. It does not automatically retry edits or authorize a new task.
An unavailable final assistant message does not prevent history recovery;
the response remains unverified. Arbitrary tool output is not substituted
for missing final assistant text.
Claude and Codex do not import historical transcripts for approval recovery.
On every host, a self-contained request stating the scope and authorization
directly in chat remains the fallback when old context is unavailable.
An unavailable confirmation tool is not consent, but does not revoke established
approval or require another confirmation tool to authorize a complete new request.
Real restrictions and semantic checks still apply; repeating a denied call
never grants permission.

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
tool calls through the exact current Stop event. A root `session.task_complete`
summary is also assistant response text and receives the same semantic and
punctuation checks. Missing summaries remain unavailable; child events and
summaries from before a new request or assistant turn cannot supply the final
response. Missing batches, truncated
text and final-message-only inputs are reported as incomplete coverage, not a
successful whole-turn check. Codex supplies the final message only: its hook
documentation explicitly describes the transcript format as unstable, so the
plugin does not parse it. Earlier prose is checked for question and scope
violations, not factual accuracy.

Compaction preserves the active request and hard question gate. Claude and
Codex recover context through `SessionStart`. Copilot recovers on the next
post-tool event, once, without waiting for another prompt. If no tool completes,
context recovery waits for the next prompt; the stored gates still apply.

Graph gating recognizes discovery tools and source reads. A successful query
unlocks source inspection for that turn and graph snapshot. A failed or unverified query
permits source fallback. An unavailable graph or executable produces one explanatory denial,
then permits ordinary discovery on retry. Echoing a command, reading help, or
querying a different graph does not satisfy the gate. This is a common-action
guard, not an exhaustive shell interpreter or proof of query relevance.

**Semantic checks make additional model calls and consume the host's usage.**
`scope_review.py` invokes the same host's CLI for recognized mutations,
delegations, follow-up agent messages and responses. It does not select a model: the isolated CLI's default
applies. Claude and Copilot have no tools; Codex disables shell, web and native
subagents in read-only mode but may expose utility tools. Runs suppress this
plugin's hooks and execute outside the consuming repository. Claude disables
customizations; Copilot disables custom instructions; Codex ignores user config.
The host login must work independently in noninteractive mode.

The reviewer executable on `PATH` must support all isolation options used by
the plugin. Claude's `--safe-mode` requires Claude Code 2.1.169 or later:
https://github.com/anthropics/claude-code/releases/tag/v2.1.169.
Codex's `--ignore-user-config` requires Codex 0.122.0 or later:
https://github.com/openai/codex/releases/tag/rust-v0.122.0.
These are the minimum versions for those flags, not a compatibility guarantee
for every hook event. Use a current supported CLI. Recognized unsupported-option
errors include an upgrade instruction instead of a generic checker failure.
The hook does not retry with weaker isolation.

The checker receives the request, candidate, proposal and approval context,
with explicit completeness metadata. Its policy explicitly excludes factual
claims, execution outcomes, live state, and documentation verification.
Missing factual evidence is not a violation. Explicit child startup or resume
binds the child to the current parent request; an old worker cannot silently
inherit new authority. Decisions are cached until the candidate, authorization
context, or relevant configuration changes. Source reads and background command
results do not invalidate scope decisions. Operational failures are not cached
as semantic denials.

Each model call has a 60-second deadline and a 90,000-byte input budget.
Older request and approval context can be omitted to fit the budget, with
explicit omission metadata. The latest request and proposed candidate are never silently cut.
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
parent's review budget.

The previous `turn_guard.py` / `turn_review.py` claim-checking implementation,
experimental claim-evidence helpers, and state-claim reminder remain in source
for reference and direct self-checks. Active hooks do not register or import
them. The retired `claim-evidence` and `verify-state-before-claiming` settings
are absent from defaults and removed from synchronized plugin JSON; stale
settings cannot reactivate them.

Hook contracts and CLI isolation options were checked against:

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/hooks#messagedisplay
- https://code.claude.com/docs/en/sub-agents#resume-subagents
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/tools-reference
- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://docs.github.com/en/copilot/reference/hooks-reference
- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
- https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically
- https://github.com/github/copilot-sdk/blob/main/docs/features/streaming-events.md
- https://github.com/github/copilot-sdk/blob/main/docs/features/agent-loop.md
- https://github.com/github/copilot-sdk/blob/main/nodejs/src/generated/session-events.ts
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents/send_input.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents/resume_agent.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/request_user_input_spec.rs

### Engineering judgment

A startup reminder directs non-trivial engineering decisions to the
[engineering-judgment skill](skills/engineering-judgment/SKILL.md). It puts
correctness, contracts, and responsibility boundaries before line or file
counts. Investigation stays proportional to the affected behavior, not a
whole-system audit for every edit.

Necessary supporting changes belong to the requested outcome. Unrelated
cleanup and speculative redesign do not. Explicit scope limits still apply;
the assistant must ask before exceeding them rather than choose an incomplete
local patch. Concise replies do not require smaller implementations.

The shared lifecycle hooks deliver the reminder at initialization and context
recovery, with a first-prompt fallback when startup is missed. Ordinary prompts
do not repeat it. The skill tells coordinators to pass relevant constraints to
delegated agents rather than assume automatic inheritance. These are
instructions, not a mechanical guarantee of architectural quality.

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

## Configuration

`config/defaults.json` lists every active guard/service and all 19 skills.
Every setting ships as `true`. Set a feature to `false` to opt out.
Global files contain the full current catalog; project files are sparse
overrides so they continue inheriting future global changes.

| Host | Global settings | Project settings |
| --- | --- | --- |
| Claude Code | `~/.claude/ioncache-ai-tools.local.json` | `.claude/ioncache-ai-tools.local.json` |
| Copilot CLI | `~/.copilot/ioncache-ai-tools.local.json` | `.github/copilot/ioncache-ai-tools.local.json` |
| Codex | `~/.codex/ioncache-ai-tools.local.json` | `.codex/ioncache-ai-tools.local.json` |

For any host, edit the corresponding global or project file:

```json
{ "features": { "never_kill_without_asking": false } }
```

To re-enable it for one project, put this in that project's settings:

```json
{ "features": { "never_kill_without_asking": true } }
```

`COPILOT_HOME` and `CODEX_HOME` override their respective global directories.
Ignore project-local JSON settings and their generated
`.ioncache-ai-tools.local.json.lock` files in consuming repositories.
These runtime lock files remain after synchronization finishes.
Within each host, project values override global values. A feature disabled
by any host's effective settings is disabled across all three hosts.

Synchronization preserves explicit values for retained keys, adds new global
defaults, and removes unknown or retired keys from global and project JSON.
Writes are locked and atomic; intentional worktree symlinks are preserved.
Unchanged files do not acquire a writer lock. Runtime hooks keep valid
preferences in effect if persistence fails, with a diagnostic instead of
disabling features. The explicit synchronization command exits nonzero if
settings cannot be read, validated, or persisted.
Malformed or unreadable preferences are not replaced with defaults. A diagnostic
pauses plugin features until the file is repaired, so configuration recovery
remains possible. This does not bypass the host's own permissions.

Legacy `disabledRules` / `enabledRules` JSON lists migrate in place.
Old Codex plugin tables in `config.toml` migrate once, when the companion
plugin JSON is absent. Embedded project values are retained in a `projects`
map in the new JSON; project-local files override them. The plugin does not
rewrite host-owned TOML or reread it after migration. Remove obsolete custom
tables yourself before using Codex `--strict-config`; retired values left in
that old file cannot enable a feature absent from the shipped catalog.

Available IDs:

| ID | Guard |
| --- | --- |
| `never_kill_without_asking` | Process termination |
| `no-manual-lockfile-edit` | Lockfile edits through file tools |
| `no_manual_lockfile_edit_bash` | Lockfile edits through shell commands |
| `fix_emdash` | Em-dashes in edits, shell input, and final responses |
| `block_raw_worktree_add` | Worktree creation outside the setup skill |
| `engineering-judgment` | Startup engineering policy and skill activation guidance |
| `scope-exactly-what-asked` | Startup scope policy and semantic scope check |
| `answer-questions` | Question classification enforcement and answer-only review |
| `approval-recovery` | Copilot native transcript approval recovery |
| `documentation-first` | Documentation-first startup guidance |
| `docs-cache` | Cache hits, background distillation, and cache diagnostics |
| `graphify` | Graph-discovery guidance and gate |
| `skill:<name>` | Each shipped skill, for example `skill:review-code` |

Tool guards use current settings on each invocation and refresh them after
semantic review before accepting a verdict. Start a new session to refresh
instructions already delivered to context. Skill opt-outs deny explicit
`Skill` / `skill` tool loads and instruct the assistant not to apply disabled
skills through automatic or slash-command activation. They do not unregister
skills from the host's discovery menu; instruction-based activation remains
subject to host behavior. Disabling `skill:engineering-judgment` also suppresses
the reminder to load that skill. Other guard and skill settings are independent.

## Writing and coding skills

| Skill | Guidance |
| --- | --- |
| `answer-questions` | Answer questions before acting |
| [engineering-judgment](skills/engineering-judgment/SKILL.md) | Choose coherent solutions across affected code and services |
| `code-complexity` | Keep functions cohesive; use metrics as guidance |
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

### Version changes and changelog

Every version change must update [CHANGELOG.md](CHANGELOG.md) with New,
Updated and Fixed sections. In a feature worktree, commit the intended changes
first, then run this command with the desired version:

```sh
npm run release -- 1.8.0
```

Run `npm ci` first if contributor dependencies are not installed. The helper
uses [conventional-changelog](https://conventional-changelog.js.org/) with its
Conventional Commits preset to parse commits and render Markdown. It updates
all three plugin manifests and prepends release notes from the Git log since
the commit that introduced the current manifest version. Later metadata-only
manifest edits do not reset that boundary. No release tags are required.
The helper requires a clean worktree, full Git history and an increasing
`MAJOR.MINOR.PATCH` version.

`feat` and `feature` commits become New items, `fix` commits become Fixed
items, and other commits become Updated items, including legacy subjects
without a Conventional Commits prefix. Breaking-change markers and footers
produce a separate BREAKING CHANGES section. Merge commits are excluded to
avoid duplicating their constituent commits. Reverted commits and their reverts
remain visible. Each item links to its commit; empty sections say `None.`.
Review the generated notes for wording and classification, then commit the
manifests and changelog together. The helper does not commit, tag or push,
and does not include uncommitted changes.

CI checks that the manifests agree and that the latest changelog entry matches
their version with all three populated sections. Run the same check locally:

```sh
npm run release:check
```

## Limitations

These are guardrails, not a security boundary. Shell indirection and unsupported
tools can evade checks; host failures can prevent hooks from running. Agents
with write access to rule settings can disable them. Use your host's own
permissions for security-critical restrictions.
