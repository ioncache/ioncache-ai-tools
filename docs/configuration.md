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

For example, disable the process-termination guard globally:

```json
{ "features": { "never_kill_without_asking": false } }
```

Re-enable that guard for one project by setting the same key to `true` in its
project settings. Chat approval does not override this guard while it is enabled.

Ignore project-local settings and their generated
`.ioncache-ai-tools.local.json.lock` files in consuming repositories. Lock files
remain after synchronization finishes.

## Feature IDs

| ID | Controls |
| --- | --- |
| `answer-questions` | Question classification, mutation gate, and answer-only guidance |
| `block_raw_worktree_add` | Worktree creation outside the setup skill |
| `docs-cache` | Documentation cache, distillation, and diagnostics |
| `documentation-first` | Documentation-first startup guidance |
| `engineering-judgment` | Startup engineering policy and skill guidance |
| `fix_emdash` | Em-dashes in edits, shell input, and final responses |
| `graphify` | Graph-discovery guidance and gate |
| `never_kill_without_asking` | Recognized process-kill commands |
| `no-manual-lockfile-edit` | Lockfile edits through file tools |
| `no_manual_lockfile_edit_bash` | Lockfile edits through shell commands |
| `scope-exactly-what-asked` | Startup scope guidance and request-freshness checks |
| `skill:<name>` | A shipped skill, such as `skill:review-code` |

Skill opt-outs block explicit skill-tool loads and instruct the assistant not
to apply the skill automatically or through slash commands. They do not remove
skills from the host's discovery menu. Instruction-based activation remains
subject to host behavior.

Disabling `skill:engineering-judgment` also suppresses the reminder to load
that skill. Other guard and skill settings are independent.

## Synchronization and recovery

Hooks reconcile settings on each invocation. To synchronize explicitly after
installing or updating, run this from the installed plugin directory:

```sh
python3 hooks/scripts/plugin_config.py copilot --project /absolute/path/to/project
```

Replace `copilot` with `claude` or `codex` as needed. Installation itself does
not run this command.

Synchronization preserves retained values, adds new global defaults, and
removes unknown or retired keys. Writes are locked and atomic, preserve
intentional symlinks, and skip unchanged files. Tool guards refresh settings
after semantic review before accepting a verdict.

Runtime persistence failures warn but retain valid effective settings.
Explicit synchronization exits nonzero on read, validation, or persistence
failure. Malformed or unreadable preferences remain untouched and pause plugin
features until repaired; the host's own permissions still apply.

Compatibility imports accept `disabledRules` / `enabledRules` JSON lists and
Codex plugin tables in `config.toml`. TOML is read only when the companion
plugin JSON is absent and is never rewritten. Remove obsolete custom TOML
tables before using Codex `--strict-config`.

Settings edits need no reinstall. Start a new session to refresh instructions
already delivered to the conversation.
