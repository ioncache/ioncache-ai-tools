# Configuration

Installation and basic usage: [../README.md](../README.md).

[../config/defaults.json](../config/defaults.json) is the complete catalog of
active guards, services, and skills. Every entry ships as `true`.

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
| `answer-questions` | Direct-answer guidance without cancelling existing assignments |
| `block_raw_worktree_add` | Worktree creation outside the setup helper |
| `docs-cache` | Documentation cache, distillation, and diagnostics |
| `documentation-first` | Documentation-first startup guidance |
| `engineering-judgment` | Startup engineering policy and skill guidance |
| `fix_emdash` | Em-dashes in edits and shell input |
| `no_broad_process_kill` | Name-based and process-group termination commands |
| `no-manual-lockfile-edit` | Lockfile edits through file tools |
| `no_manual_lockfile_edit_bash` | Lockfile edits through shell commands |
| `review-auto-model-selection` | Automatic model choice for unspecified review roles; explicit choices still obey host restrictions |
| `review-<category>` | Independent coverage for a shipped review category; all enabled by default |
| `scope-exactly-what-asked` | Scope guidance, without stored permission or request-freshness checks |
| `skill:<name>` | A shipped skill, such as `skill:review-code` |

Scope and question settings control instructions, not permission gates.
Disabling them does not disable independent action checks. The plugin stores
no task approvals or shared root/child authorization state.

Skill opt-outs block explicit skill-tool loads and instruct the assistant not
to apply the skill automatically or through slash commands. They do not remove
skills from the host's discovery menu. Instruction-based activation remains
subject to host behavior.
When a skill is disabled, continue with other available tools. The worktree
guard supplies its setup helper's path, so recovery does not depend on loading
the `create-worktree` skill.

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

## Synchronization and recovery

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
