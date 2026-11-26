# Configuration

Installation and basic usage: [../README.md](../README.md).

[../config/defaults.json](../config/defaults.json) is the complete catalog of
active guards, services, and skills. Every entry ships as `true`.

## Native Claude settings pane

In Claude Code with mods enabled, `/ioncache-ai-tools:plugin-settings` opens an
interactive pane when available, or prints the grouped listing otherwise.
It groups the complete catalog under the same headings and typed names
as the CLI. Select Project or Global, then select a setting to enable or disable
it. Each toggle saves immediately across all three hosts, using the existing
settings helper and its readback verification. Opening, switching scopes, and
refreshing do not write settings.

Tab moves between controls, Enter activates one, Page Up/Down scrolls, and Esc
closes the pane. Global mode shows the effective project value wherever an
override differs. Refresh reloads external changes. During an operation,
setting controls are unavailable. A failed save clears stale controls and shows
the error; Refresh inspects any partial update before another toggle.

`/ioncache-ai-tools:plugin-settings --list` always prints the grouped listing.
Arguments such as
`/ioncache-ai-tools:plugin-settings --global --hook:docs-cache=disabled` run the existing CLI
operation without opening the pane. Arguments are parsed as data, never
executed by a shell. Native commands and controls do not call a model.
This pane is separate from Claude's built-in `/config`; there is no second
settings store to reconcile.
The mod handles the existing namespaced skill command rather than registering
another command. Without mods, the same invocation runs the skill's text
interface. No unnamespaced alias is registered.

`hook:plugin-settings-ui` (JSON key `plugin-settings-ui`) controls the pane
independently of `skill:plugin-settings`. Disable either without disabling the
other. A disabled pane can be re-enabled with:

```text
/ioncache-ai-tools:plugin-settings --hook:plugin-settings-ui=enabled
```

When the pane is disabled or cannot be displayed, the command automatically
prints the listing. If the backend also fails, it reports the error and the
explicit `--list` recovery command without blocking the session.
The standalone helper remains usable with both UI and skill disabled.

Copilot and Codex use the settings skill below. This plugin does not yet ship
a native pane for either host. The shared helper's `--json` output
provides the complete grouped view, scope, effective states, and verified saved
paths for native callers without duplicating the catalog or persistence rules.

## Settings command

Invoke `/ioncache-ai-tools:plugin-settings` in Claude or Copilot, or
`$ioncache-ai-tools:plugin-settings` in Codex. With no arguments it opens the
Claude pane where available; otherwise it lists every shipped setting and its
effective `enabled` or `disabled` state in separate groups. `--list` requests
the listing on every host. Opening or listing does not write settings or lock
files.

```text
/ioncache-ai-tools:plugin-settings --hook:answer-questions=disabled
/ioncache-ai-tools:plugin-settings --hook:answer-questions=enabled
/ioncache-ai-tools:plugin-settings --skill:review-code=disabled --hook:docs-cache=disabled
/ioncache-ai-tools:plugin-settings --instruction:documentation-first=enabled
/ioncache-ai-tools:plugin-settings --autonomous-development:audit=disabled
/ioncache-ai-tools:plugin-settings --global --review:comments=enabled
```

| Group | CLI names | Controls |
| --- | --- | --- |
| Hooks | `hook:<name>` | Automatic checks and services, including guards and documentation caching |
| Instructions | `instruction:<name>` | Guidance only, without a tool denial |
| Autonomous development | `autonomous-development:<setting>` | Execution and related workflow features |
| Reviews | `review:<setting>` | Review categories and related workflow features |
| Skills | `skill:<name>` | Whether a skill can be invoked or applied |

Use exact names from the listing, including their prefixes.
Values are `enabled` or `disabled`, not JSON booleans. Multiple setting flags
are accepted; if repeated, the last value wins. Unknown IDs or values fail
before settings writes. `--help` lists the accepted options.

CLI names map to the existing JSON feature IDs documented below. For example,
`hook:answer-questions` updates `answer-questions`, `instruction:documentation-first`
updates `documentation-first`, and `autonomous-development:audit` updates
`autonomous-development-audit`. Skill IDs already have their `skill:` prefix.
The CLI does not accept unprefixed storage IDs or rename keys in settings files.

`autonomous-development:execution` maps to `autonomous-development`; it controls
execution rather than skill availability. The separate invocation guard belongs
in Hooks as `hook:autonomous-development:explicit-only`, because it enforces a
tool denial rather than merely instructing the assistant.

The current directory is the default project. `--project /absolute/project`
selects another existing directory. Changes update all three hosts' project
files; they stay sparse and leave global files untouched.
If any project destination resolves to a global settings file, the command
refuses the update before writing. Choose a distinct `--project` directory,
or use `--global` if you intend to change global settings. Read-only listing
remains available.
`--global` instead updates all three global files, preserving both embedded
and file-based project overrides. Its listing shows global and effective
project states separately. A project override can still win after a global
change; the command reports that difference rather than removing the override.
Global changes do not affect existing project overrides in other projects.

The helper uses the shared configuration resolver and locked, atomic file
writes. It re-reads each target under its lock, preserving unrelated settings
and intentional symlinks. It validates existing settings before updates and
checks each target's requested stored values afterward. The three files are
not one transaction. Verification and both displayed state columns use the
same readback observations. A failed write, failed readback, or mismatched stored
value makes the command exit nonzero and report that the update may be partial.
Inspect the listing and correct the reported problem before retrying. Malformed
preferences are never replaced with defaults.

`skill:plugin-settings` controls the skill itself. The standalone helper remains
available for explicitly requested settings management when the skill is off:

```sh
python3 "/absolute/plugin root/hooks/scripts/plugin_settings.py" --skill:plugin-settings=enabled
```

Resolve that path from the installed plugin, and run it from the target project
or supply `--project`. No reinstall is needed for settings changes.

## Settings files and precedence

| Host | Global settings | Project settings |
| --- | --- | --- |
| Claude Code | `~/.claude/ioncache-ai-tools.local.json` | `.claude/ioncache-ai-tools.local.json` |
| Copilot CLI | `~/.copilot/ioncache-ai-tools.local.json` | `.github/copilot/ioncache-ai-tools.local.json` |
| Codex | `~/.codex/ioncache-ai-tools.local.json` | `.codex/ioncache-ai-tools.local.json` |

`COPILOT_HOME` and `CODEX_HOME` override their respective global directories.
Global files contain the full catalog. Project files stay sparse so they
inherit global changes.

Within each host, precedence is shipped defaults, global values, embedded
project values in the global file's `projects` map, then the project file.
A feature disabled by any host's effective settings is disabled across all
three hosts.

For example, disable the broad-process-termination guard globally:

```json
{ "features": { "no_broad_process_kill": false } }
```

Re-enable that guard for one project by setting the same key to `true` in its
project settings. While enabled, use an exact positive PID for an owned or
explicitly assigned process instead of a name or process-group target.

Ignore project-local settings and their generated
`.ioncache-ai-tools.local.json.lock` files in consuming repositories. Lock files
remain after synchronization finishes.

## Feature IDs

| ID | Controls |
| --- | --- |
| `answer-questions` | Question guidance and the answer-only guard for verified root-user prompts, including Copilot's native message-evidence check |
| `autonomous-development-explicit-only` | Reject assistant skill-tool calls to autonomous development; direct human invocation and ordinary work remain available |
| `autonomous-development-follow-ups` | Automatic follow-up issue creation by authorized development PR publishers; separate from run approval, audit publication and reporting |
| `block_raw_worktree_add` | Worktree creation outside the setup helper |
| `docs-cache` | Documentation cache, distillation, and diagnostics |
| `documentation-first` | Documentation-first startup guidance |
| `engineering-judgment` | Startup engineering policy and skill guidance |
| `fix_emdash` | Em-dashes in edits and shell input |
| `no_broad_process_kill` | Name-based and process-group termination commands |
| `no-manual-lockfile-edit` | Lockfile edits through file tools |
| `no_manual_lockfile_edit_bash` | Lockfile edits through shell commands |
| `plugin-settings-ui` | Native Claude settings pane; the CLI helper and settings skill remain independent |
| `review-auto-model-selection` | Automatic model choice for unspecified review roles; explicit choices still obey host restrictions |
| `review-post-comments` | Publishing review-code findings to the PR with `--post-comments`; when disabled the review still runs and reports that posting was off |
| `review-known-issues` | Named unresolved-finding sections in review reports, development final reports and PR drafts; disabling display retains the inventory and does not disable separately authorized tickets |
| `review-<category>` | Independent coverage for a shipped review category; all enabled by default |
| `scope-exactly-what-asked` | Scope guidance, without stored permission or request-freshness checks |
| `skill:<name>` | A shipped skill, such as `skill:review-code` |
| `writer-quality-guidance` | Shared writing standards, context reconciliation and diff self-check guidance for autonomous implementers and both workflows' fixers |

Scope settings control instructions, not permission gates. Disabling
`answer-questions` removes the question contract and releases any pending
question-turn denial at the next tool call. Disabling either does not disable
independent action checks. The plugin stores no task approvals or shared
root/child authorization state.

Skill opt-outs block explicit skill-tool loads and instruct the assistant not
to apply the skill automatically or through slash commands. They do not remove
skills from the host's discovery menu. Instruction-based activation remains
subject to host behavior.
When a skill is disabled, continue with other available tools. The worktree
guard supplies its setup helper's path, so recovery does not depend on loading
the `create-worktree` skill.

Autonomous development is separately user-invoked only. Its native metadata
sets `disable-model-invocation: true` and `user-invocable: true` for Claude and
Copilot, plus `policy.allow_implicit_invocation: false` in `agents/openai.yaml`
for Codex. The tool-call guard closes Copilot's by-name loading route; disabling
that guard does not change the native discovery metadata. No prompt-classifier
state or conversation-wide fence is involved.

Disabling `skill:engineering-judgment` also suppresses the reminder to load
that skill. Apart from these dependencies, guard and skill settings are
independent.

`review-code` and review/fix options read these settings without rewriting them.
Disabling `review-auto-model-selection` selects configured defaults for
unspecified roles without disabling reviews, explicit role choices, or other
safeguards. See [../skills/review-code/OPTIONS.md](../skills/review-code/OPTIONS.md).

The review categories are `security`, `code-complexity`, `comments`, `jsdoc`,
`unit-tests` (framework-adaptive), `documentation`, `design-coherence`, `correctness`,
`integration`, `privacy`, `performance`, and `test-coverage` (framework-neutral).
For example, `review-comments: false` removes that category's review obligation.
Disabling `skill:comments` only disables its writing/explicit skill activation;
it does not silently remove comment review. Disabling `skill:review-code` still
disables that workflow.

Review enablement is separate from technical language applicability. JSDoc
requires evidenced JavaScript source and does not apply to TypeScript; no JSDoc
worker launches for a verified JavaScript-free target. General categories still
adapt to the target's languages and frameworks. This is not a config exclusion,
and missing language evidence does not silently count as absence.

Additional project categories live in a request-local `project:<slug>` registry,
not plugin settings. General purposes run by default; an explicitly declared
language prerequisite uses the same evidence rules. User exclusions retain their
provenance. The skill does not suggest exclusions or ask a category-selection question.
Same-purpose project instructions modify the owning category's scoped standard.

Startup engineering guidance excludes already assigned reviewers and validators
from generic composing skills. That reminder remains stateless and advisory;
native instruction delivery and model compliance require separate verification.

Writing guidance uses the review registry's enabled categories and applicability
rules. Fixers use the saved phase's frozen sources and scoped project standards;
implementers start with shipped sources and add inspected project requirements.
Disabling a corresponding writing skill omits that writing guidance, not its
independent review obligation. `writer-quality-guidance: false` removes the added
bundle and fixer plan-reference requirement without disabling implementation,
fixing, checks or reviews. Settings are read without writes when generating a
new writer prompt; already prepared batches retain their original instructions.
An unreadable setting reports unavailable guidance rather than a permission
decision or a completed standards check.

## Synchronization and recovery

Autonomous development has independent `autonomous-development-progress` and
`autonomous-development-model-selection` controls. Disabling progress removes
worker checkpoint writes, not the read-only `watch` command or assignment state.
Disabling automatic role selection leaves unspecified roles configured while
preserving explicit model/effort choices. `review-auto-model-selection` separately
controls unspecified review roles. None of these switches disables acceptance
checks, refunds attempts, or changes native permissions.

`autonomous-development-report-correction` enables two report corrections after
the initial validation fails, in the same assigned worker. Disabling it keeps
validation mandatory but removes automatic correction attempts. Failed candidates
and counters stay in the private run store. This is not an allowance to repeat
implementation or publication, and it never launches extra correction models.

`autonomous-development-report-contract` adds the validator-generated per-role
JSON contract to worker prompts. Disabling it does not relax validation.
`autonomous-development-report-recovery` permits one recorded recovery submission
per exhausted started job, using existing evidence after native shutdown.
It does not repeat the worker, reset counters or bypass acceptance.
The read-only `check-report` precheck remains available without spending attempts.
See [../skills/autonomous-development/RECOVERY.md](../skills/autonomous-development/RECOVERY.md).

`autonomous-development-rebase-review` enables verified clean-rebase recovery for
an accepted review. It preserves the original review and all consumed allowances;
changed patches still require a counted review. Disabling it does not change
normal acceptance, review or read-only inspection.

Do not mix old and new catalog writers while using the new review controls.
An older cached plugin removes keys it does not recognize; a newer copy then
restores their default `true`, losing an intended opt-out. Refresh all active
host copies together and recheck effective settings. Mixed-version preservation
of new settings is not supported.

Hooks reconcile settings on each invocation. To synchronize explicitly after
installing or updating, run this from the installed plugin directory:

```sh
python3 hooks/scripts/plugin_config.py copilot --project /absolute/path/to/project
```

Replace `copilot` with `claude` or `codex` as needed. Installation itself does
not run this command.

Synchronization preserves retained values, adds new global defaults, and
removes unknown or retired keys. Writes are locked and atomic, preserve
intentional symlinks, and skip unchanged files. Settings are reused within
one hook invocation and are not cached across invocations.

Runtime persistence failures warn but retain valid effective settings.
Writer-lock waits are bounded. A busy lock follows the same persistence-failure
path rather than indefinitely stalling the hook.
Explicit synchronization exits nonzero on read, validation, or persistence
failure. Malformed or unreadable preferences remain untouched and pause plugin
features until repaired; the host's own permissions still apply.

Compatibility imports accept `disabledRules` / `enabledRules` JSON lists and
Codex plugin tables in `config.toml`. TOML is read only when the companion
plugin JSON is absent and is never rewritten. Remove obsolete custom TOML
tables before using Codex `--strict-config`.

Settings edits need no reinstall. Start a new session to refresh instructions
already delivered to the conversation.
