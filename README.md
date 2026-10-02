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
| Questions first | Blocks project edits until a non-question prompt; permits private evidence-review records |
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

### Claim evidence guard

Enabled by default. Requires complete source reads and a review before supported
edits, commits, and PR text, including code-only edits. Files up to 400 lines
require whole-file reads; larger Python files allow complete functions or
classes. Other languages require whole-file evidence.

The agent must use the [claim-evidence workflow](skills/claim-evidence/SKILL.md);
ordinary reads and search snippets do not count. This adds reads and review
steps. It checks evidence coverage, not whether a claim is true.

The evidence reader rejects binary files and files over 4 MiB. Unknown tools
and indirect publication commands can bypass checks. Chat is not held back:
the guard requests one correction but cannot retract displayed text.
Disable it with `claim-evidence` in the [rule settings](#disabling-a-rule).

## Workflows

Ask the assistant to use a skill by name.

| Skill | Purpose |
| --- | --- |
| [review-code](skills/review-code/SKILL.md) | Read-only code review |
| [verify-unresolved-pr-comments](skills/verify-unresolved-pr-comments/SKILL.md) | Triage outstanding PR feedback without changing it |
| [review-validate-fix-loop](skills/review-validate-fix-loop/SKILL.md) | Review, validate, fix, and re-review within set limits |
| [investigate](skills/investigate/SKILL.md) | Read-only investigation |
| [triage-errors](skills/triage-errors/SKILL.md) | Fix related failures by root cause |
| [create-worktree](skills/create-worktree/SKILL.md) | Create a worktree with repository setup applied |

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
{ "disabledRules": ["claim-evidence"] }
```

To re-enable it for one project, put this in that project's settings:

```json
{ "enabledRules": ["claim-evidence"] }
```

For Codex:

```toml
[ioncache-ai-tools]
disabled_rules = ["claim-evidence"]

[projects."/absolute/path/to/project".ioncache-ai-tools]
enabled_rules = ["claim-evidence"]
```

`COPILOT_HOME` and `CODEX_HOME` override their respective global directories.
Codex's `--strict-config` rejects these custom tables. Ignore project-local
JSON settings in consuming repositories.

Within each host, project enables override disables. A rule disabled by any
host's settings is disabled across all three hosts.

Available IDs:

| ID | Guard |
| --- | --- |
| `claim-evidence` | Complete-source evidence and review |
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
