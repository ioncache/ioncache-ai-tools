# ioncache-ai-tools

Personal AI tools, packaged as an installable plugin for Claude Code,
Codex, and GitHub Copilot CLI, so they apply everywhere without touching
any individual project's config.

## Table of Contents

- [Install](#install)
  - [Claude Code](#claude-code)
  - [Codex](#codex)
  - [GitHub Copilot CLI](#github-copilot-cli)
- [Hooks](#hooks)
  - [Claim evidence guard](#claim-evidence-guard)
  - [Codex hook compatibility](#codex-hook-compatibility)
  - [Copilot hook compatibility](#copilot-hook-compatibility)
- [Rules](#rules)
  - [Disabling a rule](#disabling-a-rule)
- [Commands](#commands)
  - [`.worktree-setup.json`](#worktree-setupjson)
- [Skills](#skills)
- [Local development](#local-development)
  - [Claude Code](#claude-code-1)
  - [Codex](#codex-1)
  - [GitHub Copilot CLI](#github-copilot-cli-1)
- [Known limitations and security considerations](#known-limitations-and-security-considerations)

## Install

### Claude Code

```text
/plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Enabling it goes in your **global** `~/.claude/settings.json`
(`enabledPlugins`), so it's active in every project, not just the one you
installed it from.

**Reinstall** (same commands as install, safe to re-run):

```text
/plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

**Remove:**

```text
/plugin uninstall ioncache-ai-tools@ioncache-ai-tools
/plugin marketplace remove ioncache-ai-tools
```

Removing the marketplace also uninstalls the plugin, so the plugin
`uninstall` step alone is enough if you just want to drop the plugin and
keep the marketplace registered.

### Codex

```bash
codex plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
codex
```

Then, inside the session, open `/plugins`, select the ioncache-ai-tools
marketplace, and install it. Open `/hooks` afterward to review and trust
the hooks, then start a new thread.

**Reinstall:**

```bash
codex plugin add ioncache-ai-tools --marketplace ioncache-ai-tools
```

**Remove:**

```bash
codex plugin remove ioncache-ai-tools --marketplace ioncache-ai-tools
codex plugin marketplace remove ioncache-ai-tools
```

### GitHub Copilot CLI

Requires Python 3.11+, Node.js, Git, and macOS or Linux. Use a current
Copilot CLI with `userPromptTransformed` hook support (verified with 1.0.89).
This is a CLI plugin, not a Copilot cloud-agent or VS Code extension.

```bash
copilot plugin install ioncache/ioncache-ai-tools
```

The plugin is installed in your user configuration and applies across
projects. Start a new session after installing or updating it.

Alternatively, use the existing marketplace, which Copilot can read from
`.claude-plugin/marketplace.json`:

```bash
copilot plugin marketplace add ioncache/ioncache-ai-tools
copilot plugin install ioncache-ai-tools@ioncache-ai-tools
```

**Update:**

```bash
copilot plugin update ioncache-ai-tools
```

**Remove:**

```bash
copilot plugin uninstall ioncache-ai-tools
```

If you registered the marketplace, remove it after uninstalling the plugin:

```bash
copilot plugin marketplace remove ioncache-ai-tools
```

## Hooks

| Hook | Lifecycle event | What it does |
| ---- | ---------------- | ------------- |
| `graphify_context.js` | UserPromptSubmit | When the project has a graphify knowledge graph, tells the agent to use `graphify query` instead of grep/Read/find |
| `docs_first_guard.py` | UserPromptSubmit | Unconditionally reminds the model to verify library/API/tool/service specifics via a real lookup instead of training data |
| `classify_question.py` | UserPromptSubmit | Flags any prompt containing a question and emits the `answer-questions` skill reminder in the same invocation |
| `block_pending_question.py` | PreToolUse | Denies recognized mutations while the latest user prompt is classified as a question; a subsequent non-question prompt clears it |
| `rule_engine.py PreToolUse` | PreToolUse | Runs every `hooks/rules/*` rule registered for this event (deny or rewrite) |
| `rule_engine.py UserPromptSubmit` | UserPromptSubmit | Runs every `hooks/rules/*` rule registered for this event (injects reminders) |
| `block_emdash_turn.py` | Stop | Blocks the turn if the reply contains an em-dash |
| `claim_evidence.py` | Prompt, tool, lifecycle, and Stop events | Enforces read boundaries, tracks complete reader output, and requires exact-artifact review checkpoints |

### Claim evidence guard

This guard separates source delivery from semantic review. It mechanically
checks complete, current source coverage and a review record for the exact
outgoing content. It does not prove that a statement follows from its evidence.
Load the [claim-evidence skill](skills/claim-evidence/SKILL.md) for the workflow
and review JSON format.

The guard is enabled by default. Supported edits require a checkpoint even
when they contain only code: every outgoing line must be classified as
behavioral or non-behavioral. This deliberately avoids guessing which lines
contain comments or documentation in an arbitrary language. A reviewer must
justify non-behavior classifications; the hook cannot establish their truth.
Use the normal [disable configuration](#disabling-a-rule) with ID
`claim-evidence` to disable the whole guard, including reminders and Stop checks.
This ID belongs to a standalone hook, not a file in `hooks/rules/`.

| Read case | Policy |
| --- | --- |
| At most 400 physical lines | Native read requests must omit ranges, including an explicit start at line 1 |
| More than 400 lines, supported Python syntax | Ranges must exactly match parser-produced units or the entire file |
| Other languages or unsupported syntax | Whole-file evidence reads; no guessed or brace-counted units |
| Search, diff, native file read, or arbitrary shell output | Discovery only; no ledger coverage |
| Bounded evidence-reader pages | Coverage only after every page from the same snapshot is delivered intact |

A physical line ends at LF; a final nonempty unterminated sequence also counts.
CRLF does not add another line. Python units include complete function,
async-function, and class nodes, including decorators, plus complete top-level
statements. Nested callables can be read independently but do not establish
coverage for their enclosing function. Lambdas are covered through their
enclosing supported unit. A conditional or loop inside a function is not an
independent unit. Bare-CR Python source requires a whole-file read.

Resolve `hooks/scripts/claim_evidence.py` from the installed plugin, not the
consuming project. Its `units` command reports exact unit IDs and a source hash.
`read` defaults to the entire file, including files larger than a host's display
limit. `--unit START:END` selects a parser-defined unit; `--page N --sha256 HASH`
continues a logical read without trusting a guessed range. Each page contains
at most 2,000 source characters. Read and inventory inputs are UTF-8 text,
limited to 4 MiB; oversized or binary sources fail explicitly. A readable
empty file has zero lines and one empty delivery page.

The first unsupported-by-a-checkpoint edit is denied and its normalized
request is captured in a private JSON file. `prepare REQUEST.json` inventories
all outgoing content and returns paged output, with a hash and page count.
Complete every inventory page before reviewing it. `approve REQUEST.json
--review REQUEST.review.json` submits the classifications and evidence.
Approval is recorded only after the matching helper response arrives intact.
Running these commands outside an active host grants neither coverage nor
approval. Review files beside captured requests are exempt from edit gates,
including native patches, so preparing a review does not recursively require
another review.

Every inventory line must be classified exactly once. Behavioral claims quote
outgoing text and identify complete source units, current hashes, decisive
lines, and a supporting rationale. Non-behavior classifications require a
rationale and no claims. Metadata records a reviewer identity, but does not
authenticate an independent reviewer or automatically run one. Use a separate
reviewer where practical. For changed behavior, make the code-only edit,
reread the resulting code, then add prose.

Supported write surfaces are `Write`, `Edit`, `MultiEdit`, and `apply_patch`,
including their translated Copilot equivalents. The shell gate recognizes
direct `git commit` and `gh pr create`/`new`/`edit`/`comment` calls. It checks
literal message text, message/body files, and the staged diff for commits.
Commit forms must use explicit messages and the existing index, not automatic
staging, path selection, message reuse, or an editor. PR creation requires an
explicit title and body. Chained commands, shell expansion, stdin bodies, and
generated or interactive text are rejected. Some uncommon options, metadata-only
PR edits, and special characters in literal arguments are conservatively
rejected; this is not an exhaustive shell interpreter.

Coverage and approvals live in a private SQLite ledger under
`~/.cache/ioncache-ai-tools/claim-evidence/`, scoped by session, working directory,
and supplied agent identity. Exact artifact fingerprints include target-file
state and file-backed publication text. Source hashes are rechecked at approval
and retry. Compaction, startup/resume, session end, and subagent-start events
clear receipts and captured request/review JSON across that session, including
other working directories and agents. Receipt invalidation commits before
request-file cleanup, with the database lock retained until the store closes.
Failed or interrupted cleanup can leave request files but cannot restore the
cleared receipts. Disabling the guard also clears them on the next event.
Empty database files and directories remain; an abrupt exit can leave private
state until a lifecycle reset.

Claude uses serialized `PostToolBatch` output, not its earlier structured
`PostToolUse` output, to account for delivered pages. Codex and Copilot adapters
use their model-facing post-tool output. Missing hooks and unrecognized or
truncated output cannot grant a receipt. Claude installations
need `PostToolBatch` support. Source reads by other tools are intentionally not
credited, even if complete; using the helper first avoids duplicate reads.

Known limits and costs:

- Stop requests one correction for an unreviewed final answer, then permits
  completion. It does not buffer chat or retract already displayed prose.
- Claim-to-source mapping, non-behavior classifications, dependency coverage,
  and semantic correctness remain reviewer responsibilities. Current local
  source is not proof of deployed behavior, a PR's remote state, or historical
  intent. External API and decision-record verification remains a skill step.
- Unknown tools, shell scripts, aliases, API publications, tool-output rewrites
  by other hooks, and later host-side truncation are outside the guarantee.
  Checks cover the pre-tool snapshot, not concurrent changes made after it.
  Hooks can fail open on host timeouts or fail to load; this is not a security
  boundary or an authenticated audit log.
- Agent isolation depends on host-supplied identity. Copilot tool payloads
  need not carry it; its adapter clears coverage at reported subagent start
  and stop. Unreported or overlapping subagents cannot be reliably isolated.
- There is no automatic language-server or code-graph integration, semantic
  review service, buffered host wrapper, or automatic pre-PR branch-wide prose
  scan. Commit inventory includes staged changes; PR inventory covers outgoing
  title/body text.
- Source tokens scale with distinct required units and rereads after
  invalidation. Each 2,000-character page takes a helper call. Every supported
  edit adds inventory delivery and review, including non-behavioral edits.
  Hashing/parsing occurs locally; no parser dependency or network service is
  installed. There is no parser cache in this implementation.

### Codex hook compatibility

Claude Code uses `hooks/hooks.json` directly. Codex's
`.codex-plugin/plugin.json` points to `hooks/codex-hooks.json`.
The Codex adapter and Copilot adapter share `hook_adapter_common.py` for
ordered execution of the shared manifest and patch parsing. Rules remain
in one place.

Claude and Codex launch matching hooks concurrently. Question classification
and its skill reminder share one handler, so neither host depends on the
ordering of separate prompt hooks. Codex's manifest registers one
adapter command for `UserPromptSubmit`, which runs the shared scripts in
order and combines their additional context.

Codex reports file changes as `apply_patch`, with the patch in
`tool_input.command`, even when a hook matcher uses `Edit` or `Write`.
The adapter passes the patch to the shared hooks once. The question guard
recognizes it as a mutation; the engine checks each target as an edit,
including additions, deletions, and both ends of renames. Rules and config
are loaded once per patch, not once per target.

Only added lines are checked for em-dashes. A required rewrite becomes a
denial asking the agent to correct the patch; context and removed lines
are never rewritten. Safe calls return no permission override. Bash
keeps the shared shell checks. `Stop` runs the shared punctuation and evidence
checks through the adapter with Codex's `last_assistant_message`.

Adapter failures log to stderr and exit with code 2, which blocks the
prompt or tool call. The shared engine still isolates individual rule
errors. Engine-wide failures and its five-second watchdog log and exit 2.
The adapters also bound shared tool-hook execution to 20 seconds, below
the native 30-second timeout; these hooks are guardrails, not a security boundary.

Claude text rewrites return `updatedInput` without granting permission.
Copilot returns only `modifiedArgs`. The Codex adapter adds the `allow`
field only when its rewrite protocol requires it; patch changes that
would need rewriting are denied instead.

After updating the installed plugin, review and trust the changed hooks
in `/hooks`, then start a new thread. See the
[Codex hooks reference](https://learn.chatgpt.com/docs/hooks).

### Copilot hook compatibility

Copilot's `.github/plugin/plugin.json` points to `hooks/copilot-hooks.json`, whose
`copilot_adapter.py` entrypoint runs the same scripts in the shared
manifest's order. Rules and skills stay shared.

| Copilot event | Shared behavior |
| --- | --- |
| `userPromptTransformed` | Runs the `UserPromptSubmit` hooks and appends their reminders to the transformed prompt, preserving its existing content |
| `preToolUse` | Translates native tool names/arguments, runs the `PreToolUse` hooks, and returns native denial or argument-rewrite output |
| `postToolUse` | Supplies model-facing tool output to the evidence ledger and returns receipt or failure guidance |
| `agentStop` | Reads the current final response from Copilot's transcript, then runs the shared `Stop` hook |
| `sessionStart`, `preCompact`, `subagentStart`, `subagentStop` | Invalidates evidence receipts and captured review requests |
| `sessionEnd` | Clears evidence state and removes that Copilot session's pending-question marker |

Copilot drops command-hook output from `userPromptSubmitted`, so simply
installing the Claude hook manifest would lose all prompt reminders.
The adapter uses `userPromptTransformed` instead.

Native `create` and `edit` calls retain the em-dash auto-fix, without
granting permissions that the user's normal policy would deny. Raw
`apply_patch` calls check every file target, including rename destinations.
They deny em-dashes in added text rather than rewriting the patch; context
and removed lines are left untouched. Bash remains deny-only.

Copilot's `agentStop` payload lacks `last_assistant_message`, and its
transcript is written asynchronously. The adapter waits up to two seconds
for the matching stop-invocation record before checking the latest root
assistant response. It ignores subagent messages and previous turns.
An unavailable or malformed transcript reports an error rather than being
treated as a clean response; Copilot's stop-hook error behavior is fail-open.
This transcript dependency is specific to Copilot. Claude and Codex still
use their supplied `last_assistant_message`.

Copilot markers have a `copilot-` session prefix. As with the other hosts,
recognized questions block mutations until a subsequent non-question
prompt; read-only lookups remain available.

See the [Copilot hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference)
and [plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
for the host contracts.

## Rules

**Scope, by design:**

- These guard against common, everyday ways of doing something (a bare
  command, a typical flag, a normal redirection), not deliberate
  obfuscation.
- Exhaustive coverage would mean running every tool call through a
  separate LLM to evaluate it against a list of rules: real cost and
  latency on every call, for a guard meant to stop casual/automatic
  action, not survive an adversary.
- A cheap, readable check that catches the common cases is the actual
  goal. A bypass that requires deliberately obfuscating the command is
  an accepted, out-of-scope gap, not a bug to chase.

These rules aren't a replacement for your tool's own permission-denial
system, prefer that for anything security-critical:

- Claude Code: [`permissions.deny`](https://code.claude.com/docs/en/permissions)
- Codex: [`execpolicy` rules](https://learn.chatgpt.com/docs/agent-configuration/rules)
- Copilot CLI: [tool permissions](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference)

One file per rule, in `hooks/rules/`, loaded by `rule_engine.py`. Adding a
rule never touches engine code. Three shapes:

- **Always-on** (`.json`, `matcher: {"type": "always"}`): injects a fixed
  reminder into `additionalContext` on every `UserPromptSubmit`.
- **Pattern** (`.json`, `matcher: {"type": "regex", "field": "...", "pattern": "..."}`):
  denies a `PreToolUse` call when a field of the tool input matches.
- **Scripted** (`.py`, module-level `EVENT`, optional `TOOL_NAMES`, a
  `matches(hook_input)` function, and either a `check(hook_input)` function
  or module-level `ACTION`/`MESSAGE`): the escape hatch for anything a
  regex can't express on its own, including rewriting tool input in place
  (see `fix_emdash.py`) or reusing a shared helper like
  `normalize_shell_command` (see `no_manual_lockfile_edit_bash.py` and
  `block_raw_worktree_add.py`).

| Rule | Shape | Event | What it does |
| ---- | ----- | ----- | ------------ |
| `never_kill_without_asking` | Scripted | PreToolUse | Denies `kill`/`pkill`/`killall` in a Bash command, using real command tokenization (not a regex) |
| `no-manual-lockfile-edit` | Pattern | PreToolUse | Denies editing `package-lock.json`/`yarn.lock`/`pnpm-lock.yaml` via Edit/Write/MultiEdit |
| `no_manual_lockfile_edit_bash` | Scripted | PreToolUse | Denies mutating a lockfile from Bash (redirection, `sed -i`, `tee`, `perl -i`) |
| `fix_emdash` | Scripted | PreToolUse | Rewrites em-dashes to `, ` in Write/Edit/MultiEdit input; denies (asks for a manual fix) in Bash, since the rewrite can split one shell argument into two |
| `block_raw_worktree_add` | Scripted | PreToolUse | Denies creating a worktree by raw git or oh-my-zsh's `gwta` alias; points to the `create-worktree` skill instead |
| `scope-exactly-what-asked` | Always-on | UserPromptSubmit | Reminds to do exactly what was asked, nothing more |
| `verify-state-before-claiming` | Always-on | UserPromptSubmit | Reminds to verify current status before stating it, never from memory |

### Authoring rules

Use a JSON rule for a fixed reminder or a field-pattern denial. Use a Python
rule when the policy needs a conditional decision or an input rewrite.
For example, a project that requires a release checklist could add
`hooks/rules/release-checklist.json`:

```json
{
  "event": "UserPromptSubmit",
  "matcher": {"type": "always"},
  "action": "inject",
  "message": "Use the project's release checklist when preparing a release."
}
```

Python rules receive the shared hook payload, not native adapter arguments.
`UserPromptSubmit` supplies `prompt`; `PreToolUse` supplies `tool_name` and
`tool_input`. Optional `TOOL_NAMES` restricts which tools reach `matches()`.
Return a boolean from `matches(hook_input)` and an action dictionary or
`None` from `check(hook_input)`. Do not return the final hook output envelope
or print protocol output from a rule.

| Result from `check()` | Event | Policy meaning |
| --- | --- | --- |
| `None` | Either | This rule has no action; it does not grant permission. |
| `{"action": "inject", "message": "..."}` | `UserPromptSubmit` | Add guidance to the prompt. |
| `{"action": "deny", "message": "..."}` | `PreToolUse` | Reject the tool call with a reason. |
| `{"action": "rewrite", "updatedInput": {...}}` | `PreToolUse` | Substitute the complete tool input; an optional `systemMessage` explains the change. |

For example, a project that disallows writing blank files could add
`hooks/rules/no-blank-write.py`:

```python
EVENT = 'PreToolUse'
TOOL_NAMES = ['Write']


def matches(hook_input):
    """Apply the content requirement to every Write request."""
    return True


def check(hook_input):
    """Reject empty or whitespace-only content; otherwise take no action."""
    if not hook_input['tool_input']['content'].strip():
        return {'action': 'deny', 'message': 'Supply nonblank file content.'}
    return None
```

This example rejects `content: "  "` but takes no action for
`content: "Release notes"`. Its scope is `Write`, not `Edit` or native patches.
Native patch targets reach rules as synthetic `Edit` inputs, containing
added text rather than the complete resulting file. See
[patch handling](#codex-hook-compatibility) before writing policies that need
whole-file content.

Rules run in filename order. Any denial wins over rewrites. Otherwise only
the first rewrite is returned, with a warning if multiple rules request one.
Rewrites are not chained: each rule receives the original request.
Prompt reminders are joined with blank lines. Use
[rule-disable configuration](#disabling-a-rule) to opt out of a policy;
disabled Python rules are not imported.

### Evaluation and failure contract

The shared entry point accepts an event argument (`PreToolUse` or
`UserPromptSubmit`) and a JSON object on stdin. Rules come from the plugin's
bundled `hooks/rules/` directory; project configuration is resolved from the
process working directory. Adapters translate native requests and responses
as described in [Codex compatibility](#codex-hook-compatibility) and
[Copilot compatibility](#copilot-hook-compatibility).

For a valid hook payload:

| Outcome | Engine response |
| --- | --- |
| Rules produce a denial, rewrite, or reminder | Exit 0 with the corresponding JSON result on stdout. A policy denial is not an engine failure. |
| Directory is readable but empty, no enabled rules apply, or no rule requests an action | Exit 0 with no stdout; normal host permissions still apply. |
| An individual rule fails to load, match, or check | Log the rule failure to stderr and continue evaluating the remaining rules. |
| Rules directory is missing, is not a directory, or cannot be listed | Log the discovery failure to stderr and exit 2, with no successful result. |
| An unhandled engine error occurs or the five-second watchdog expires | Log to stderr and exit 2. |

An unavailable rule directory is an installation or filesystem failure, not
an instruction to disable enforcement. Restore access to the bundled rules
or repair the plugin installation before retrying. To intentionally disable
a rule, use [configuration](#disabling-a-rule), not removal of the directory.
When calling `load_rules_for_event()` or `run_hook()` directly, discovery
errors propagate as exceptions; `main()` translates them into the CLI
failure response.

### Disabling a rule

Add config in the harness-specific locations below, whichever CLI you use.
Rule toggles are file-based, not environment variables.

- Global config is the baseline; project-level config only overrides it
  for one project (in either direction: a project can disable a rule
  that's enabled everywhere else, or re-enable one that's disabled
  everywhere else).
- Disabling a rule once, globally, is the common case, most people who
  don't want a rule don't want it in any project.

**Claude Code:** `ioncache-ai-tools.local.json`, in `~/.claude/` for a global
setting, or in `<project>/.claude/` to override it for one project
(gitignored, not shipped with the plugin):

```json
{ "disabledRules": ["never_kill_without_asking"] }
```

A project-level file can also carry `enabledRules`, to re-enable a rule
the global file disables, for that project only:

```json
{ "enabledRules": ["never_kill_without_asking"] }
```

**Codex:** in `~/.codex/config.toml`, hand-edited, there is no CLI command
for it. A top-level table for a global setting, a project-scoped table to
override it for one project. Not compatible with Codex's `--strict-config`
flag, which rejects both unrecognized tables:

```toml
[ioncache-ai-tools]
disabled_rules = ["never_kill_without_asking"]

[projects."/absolute/path/to/project".ioncache-ai-tools]
enabled_rules = ["never_kill_without_asking"]
```

The rule engine itself is Python and reads Codex's config.toml directly with
the stdlib `tomllib` parser (3.11+ required); on an older Python, the
disabled-rules lookup logs the failure to stderr and falls back to none
disabled, same as any other malformed Codex config.

**Copilot CLI:** `ioncache-ai-tools.local.json` in `~/.copilot/` (or
`$COPILOT_HOME/`) for global settings, and
`<project>/.github/copilot/ioncache-ai-tools.local.json` for project overrides:

```json
{ "disabledRules": ["never_kill_without_asking"] }
```

Project settings can also use `enabledRules` to override a global disable,
just like Claude Code. These are plugin-owned config files, separate from
Copilot's native `settings.json`. The project file is gitignored in this
repository; consuming repositories should ignore it too if they use it.

- A rule's id is its filename minus the extension.
- Resolution per tool: start from that tool's global config, add anything
  the project config disables, then remove anything the project config
  enables. All three tools' results are then unioned, disabling a rule in
  any one disables it for every host.
- No global-scope `enabledRules`/`enabled_rules`: with nothing disabled
  globally, every rule already runs, so a global enable list would have
  nothing to override.
- Takes effect immediately, on the next tool call, read fresh from disk
  every time. Unlike changes to the plugin's own files (see
  [Local development](#local-development)), this never needs a reinstall.

## Commands

These workflows ship as native `skills/<name>/SKILL.md` files on every
host, not legacy command files that Codex may ignore or partially migrate.
Ask the assistant to use the named skill. Claude also exposes plugin skills
as `/ioncache-ai-tools:<name>`; in Codex, use `/skills` or the `$` skill
picker. In Copilot, ask to load the named skill explicitly.

| Workflow skill | Description |
| ------- | ------------ |
| `verify-unresolved-pr-comments` | Triage table of unresolved PR review feedback. Read-only |
| `review-code` | Read-only review with independent standards passes and cross-cutting correctness |
| `review-validate-fix-loop` | Autonomous nested review/fix loops with a per-run ledger, finite limits, resumption, and reports |
| `investigate` | Read-only trace of how a feature or system works |
| `triage-errors` | Fix a batch of failures by root cause, not one by one |
| `create-worktree` | Wraps the git worktree command and applies the repo's `.worktree-setup.json` (untracked local config, generated caches, post-create commands); writes the file with generic defaults on first use |

### Review and fix loops

Explicitly request `review-validate-fix-loop` with a target (`repository`,
`branch`, PR reference, or paths), optional `--max-loops N` and
`--max-fix-cycles N`, or `--resume .review-loop/<run-id>/REVIEW_LEDGER.json`.
Both limits default to 3. With no target, the skill uses the active PR or
branch changes, including local edits. Parameters apply to one run; there
is no permanent configuration or per-phase model/effort selection.

The coordinator reviews, validates, fixes, and independently reviews fixes.
Fix/review-fixes repeats inside the current outer loop. If the inner limit
leaves actionable issues, the entire run stops. Full-scope confirmation
after corrections consumes another outer loop; exhausting the outer limit
before that confirmation is incomplete, not success.

Decisions are autonomous and include reasons and evidence. Accepted valid
or uncertain issues remain visible as exceptions. Normal permissions still
apply; the loop does not authorize commits, pushes, PR comments, or deployment.
Standalone `review-code` remains read-only.

Each run stores its own `.review-loop/<run-id>/REVIEW_LEDGER.json`, with
snapshot objects alongside it. Iterations share that history; another run
does not inherit it, and resumption across sessions preserves it. The Python
helper checks state transitions, counters, file snapshots, and expected
revisions. It does not prove that agent judgments are correct.

Only one running/resumable run is allowed per worktree. Snapshot files may
contain source; do not commit or upload run artifacts. Ignored files and
external systems are not snapshotted. Submodules/special files are unsupported,
and symlink paths cannot be declared as fix targets. Errors are explicit,
not clean reviews. Host-agent orchestration is best effort, not a hard guard.

See the [workflow](skills/review-validate-fix-loop/WORKFLOW.md),
[ledger CLI protocol](skills/review-validate-fix-loop/LEDGER.md), and
[phased design](docs/review-validate-fix-loop-design.md). Cost budgeting is
required Phase 2 work; Phase 1 measures neither spending nor tokens.

### `.worktree-setup.json`

Lives at a repo's root. The `create-worktree` skill reads it from the main worktree and
applies it to every new worktree. A repo without one gets the file written with
generic defaults on the first run (the local-config and graphify symlinks
below, nothing else), so it is always there to extend.

```json
{
  "copies": ["generated-cache"],
  "afterCopy": [{ "path": "generated-cache/.root", "content": "${worktreePath}\n" }],
  "symlinks": [
    ".claude/settings.local.json",
    ".claude/ioncache-ai-tools.local.json",
    ".claude/hooks",
    "CLAUDE.local.md",
    ".claude/hookify.*.local.md",
    ".github/copilot/settings.local.json",
    ".github/copilot/ioncache-ai-tools.local.json",
    ".graphifyignore"
  ],
  "commands": ["ln -s ~/envs/app.env \"${worktreePath}/apps/app/.env\"", "npm install"]
}
```

- `copies` - paths (relative to repo root) recursively copied into the new
  worktree.
- `afterCopy` - files written after copying; `${worktreePath}` and
  `${mainRoot}` in `content` are replaced with the absolute paths.
- `symlinks` - paths, or single-segment `*` glob patterns, symlinked from the
  main worktree into the new one. Missing sources are skipped.
- Copy, generated-file, and symlink paths must stay within their respective
  roots. Existing dangling symlinks are rejected, including intermediate
  path components, rather than followed by a later write.
- `commands` - shell commands run in the new worktree, in order, after
  copies and symlinks, with the same `${worktreePath}`/`${mainRoot}`
  substitution (quote the placeholders, paths can contain spaces). The
  first failure stops the run and the command exits non-zero. This is
  where repo-specific setup goes (env symlinks, installs); the plugin
  itself knows nothing about any repo's layout.

The file is committed to the repo, so its commands run with the same
trust as an install script: review it before creating a worktree in a
repo you did not write.

## Skills

| Skill | Description |
| ----- | ------------ |
| `answer-questions` | Answer direct questions fully before doing anything else |
| `code-complexity` | Parameter counts, nesting depth, function length, single responsibility |
| `comments` | Default to no comment; when warranted, why not what |
| `documentation-writing` | No em dashes, no AI filler phrases, short active-voice sentences |
| `prompt-output` | Wrap generated prompt files in a single code fence |
| `unit-tests` *(opinionated, Vitest)* | BDD `describe`/`it`, AAAR comments |
| `jsdoc` *(opinionated, JS/TS)* | Required tags, typedef rules, no inline `Object` |
| `security` *(opinionated, Fastify/MongoDB examples)* | Validate at the edge, sanitize input, secrets in env |
| `claim-evidence` | Complete-source reads, claim-to-evidence review records, and exact-artifact checkpoints |

## Local development

Before pushing, run the self-checks:

```bash
python3 hooks/scripts/rule_engine_self_check.py < /dev/null
python3 hooks/scripts/pending_question_self_check.py < /dev/null
python3 hooks/scripts/copilot_adapter_self_check.py < /dev/null
python3 hooks/scripts/codex_adapter_self_check.py < /dev/null
python3 hooks/scripts/claim_evidence_self_check.py < /dev/null
node scripts/create-worktree.js --self-test
python3 scripts/review_ledger_self_check.py
```

These checks run in CI (see `.github/workflows/validate.yml`). The second
covers `classify_question.py` and `block_pending_question.py`, using a fixture of
real messages pulled from actual session history rather than invented
ones, real usage turned out to have shapes (unpunctuated questions,
"do"-led imperatives) invented examples missed.

The Copilot checks exercise the real adapter subprocess with isolated
configuration, native payloads, multi-file patches, prompt state, and
transcript timing. Run one test with:

```bash
python3 hooks/scripts/copilot_adapter_self_check.py CopilotAdapterTests.test_native_shell_rules
```

The Codex checks dispatch the plugin manifest's real commands with native
payloads and isolated configuration. They cover concurrent host dispatch,
question state, patch targets and added text, shell rules, and stop checks.
Run one test with:

```bash
python3 hooks/scripts/codex_adapter_self_check.py CodexAdapterTests.test_prompt_order_survives_concurrent_host_dispatch
```

Then test against the working copy directly.

### Claude Code

```text
/plugin marketplace add <local path to repo>
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

For this relative-path plugin in a marketplace added from a local directory,
current Claude Code loads the source in place. After editing it, start a new
session or run `/reload-plugins`; no reinstall or version bump is needed.
You can also launch `claude --plugin-dir .` to load the checkout directly.

Remote marketplace installations use cached copies instead. Update those
through the plugin manager and reload or restart. See
[Claude's loading reference](https://code.claude.com/docs/en/plugins/loading#in-place-and-copied-plugins).

### Codex

```bash
codex plugin marketplace add <local path to repo>
codex plugin add ioncache-ai-tools@ioncache-ai-tools
```

Codex copies the plugin into
`~/.codex/plugins/cache/` at install time and never re-reads the live source
afterward. After any change, reinstall to force a fresh copy:

```bash
codex plugin remove ioncache-ai-tools@ioncache-ai-tools
codex plugin add ioncache-ai-tools@ioncache-ai-tools
```

### GitHub Copilot CLI

Load the checkout for one session without installing it:

```bash
copilot --plugin-dir .
```

Or install the working copy into the user plugin cache:

```bash
copilot plugin install .
copilot plugin list
copilot skill list
```

Re-run `copilot plugin install .` after changing a directly installed local
plugin, then start a new session. `--plugin-dir` reads the source directly
when a session starts. Copilot discovers all behavior and workflow skills
through the manifest's `skills/` path.

## Known limitations and security considerations

### Disable-config isn't tamper-proof

- The per-rule disable config (see [Disabling a rule](#disabling-a-rule))
  is a plain file, such as `.claude/ioncache-ai-tools.local.json`, Codex's
  `config.toml`, or `.github/copilot/ioncache-ai-tools.local.json`, that an
  agent normally has Edit/Write access to.
- An agent could add a rule's id to `disabledRules`/`disabled_rules`
  itself, defeating a rule meant to guard its own actions (e.g.
  `never_kill_without_asking`).
- There's no mandatory, non-disableable rule concept today; the original
  goal was that a user can disable any rule by hand-editing the config.
  A `mandatory: true` flag the engine refuses to honor would be a real
  design change, not a bug fix, and hasn't been made.

### Text heuristics, not a security boundary

`never_kill_without_asking` and `no_manual_lockfile_edit_bash` tokenize
the command (Python's `shlex`) and check the executable position of each
simple command, instead of matching text anywhere in the string. That
closes two gaps a flat-text match had:

- A plain argument containing the guarded word no longer false-matches
  (`echo kill`, `ls /tmp/kill`, both correctly ignored now, since `kill`
  isn't in command position).
- A quoted argument containing an operator character like `|` no longer
  exposes it (`grep "kill|pkill|killall" file` is one quoted token, not
  three separately-matched pieces).

It also recognizes a narrower version of a different gap the old text
match didn't have: a wrapper command around the guarded word
(`timeout 5 kill -9 1234`, `nohup kill -9 1234`, a bare `nice kill -9
1234`).

- `skip_wrappers` strips a small, fixed set of wrappers (matching what
  Claude Code's own `permissions.deny` documents stripping) before
  checking the executable position.
- Still not recognized: one of those wrappers invoked *with* its own
  value-taking flag (`nice -n 10 kill -9 1234`, `stdbuf -o0 kill -9
  1234`). Telling a flag from its value needs per-wrapper grammar
  knowledge this doesn't have, real scope beyond the false-positive fix
  this was solving, and stays a known, accepted gap.

Other gaps:

- `block_raw_worktree_add` still uses the older text-normalization
  approach (`normalize_shell_command`), not tokenization, and keeps both
  gaps above for the patterns it matches.
- Shell expansion or indirection that produces a guarded command without
  the guarded word ever appearing literally in the text (a variable or
  command substitution) is a gap for every rule here, regardless of
  approach, since none of them actually execute or expand the shell.
- These rules catch the common case and prompt a pause; they don't
  withstand deliberate evasion.
