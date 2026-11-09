# ioncache-ai-tools

Guardrails and reusable workflows for Claude Code, Codex, and GitHub Copilot CLI.
Hooks check questions, scope, and common tool actions. Skills guide reviews,
investigations, writing, and implementation.

Requires Python 3.11+, Node.js, Git, and macOS or Linux. Use a current supported
CLI with a working login. This plugin targets local coding CLIs; its Copilot
integration is not for the cloud agent or VS Code.

## Install

### Claude Code

Run inside Claude Code:

```text
/plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Choose user scope to enable it across projects. Manage updates and removal
through `/plugin`. Reload plugins or start a new session when prompted.

### Codex

```sh
codex plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
codex plugin add ioncache-ai-tools --marketplace ioncache-ai-tools
codex
```

Review and trust the plugin's hooks through `/hooks`, then start a new thread.
Use `/plugins` to browse installed plugins.

### GitHub Copilot CLI

```sh
copilot plugin install ioncache/ioncache-ai-tools
```

Start a new session after installing or updating.
Update with `copilot plugin update ioncache-ai-tools`.
Remove with `copilot plugin uninstall ioncache-ai-tools`.

## Use

Guardrails activate automatically. They keep question turns answer-only, check
work against the user's authorization, block direct lockfile edits and
recognized process-kill commands, route worktree creation through the setup
helper, and enforce punctuation rules. Documentation-first and engineering
guidance apply at startup. Projects with `graphify-out/graph.json` require a
graph query before source discovery.

Ask for a skill by name when you want a workflow:

```text
Use investigate to explain how authentication works without changing files.
Use review-code to review this branch.
Use review-dependabot-pr to review this dependency update.
Use create-worktree to create a worktree for the logging changes.
Use write-pr-descriptions to draft a description for this branch.
```

Read-only review and bounded review-and-fix workflows are separate skills.
See [docs/workflows.md](docs/workflows.md) for the catalog and invocation
options.

**Scope checks and documentation-cache distillation make additional model calls
and consume your host's usage.** Scope checks can add latency and make mistakes;
they do not verify factual claims. Request and approval context is stored
locally and passed to the host's reviewer.
See [docs/guardrails.md](docs/guardrails.md) for recovery, privacy, and coverage.

## Configuration

Every feature and skill is enabled by default. Set an entry in `features` to
`false` in the appropriate global or project file:

| Host | Global settings | Project settings |
| --- | --- | --- |
| Claude Code | `~/.claude/ioncache-ai-tools.local.json` | `.claude/ioncache-ai-tools.local.json` |
| Copilot CLI | `~/.copilot/ioncache-ai-tools.local.json` | `.github/copilot/ioncache-ai-tools.local.json` |
| Codex | `~/.codex/ioncache-ai-tools.local.json` | `.codex/ioncache-ai-tools.local.json` |

For example, to disable the documentation cache:

```json
{ "features": { "docs-cache": false } }
```

Project values override global values within each host. A feature disabled by
any host's effective settings is disabled across all three hosts.
Hooks synchronize settings automatically; edits need no reinstall.
Start a new session to refresh instructions already in context.

See [config/defaults.json](config/defaults.json) for available settings and
[docs/configuration.md](docs/configuration.md) for precedence, synchronization,
and skill opt-outs.

## Known issues and limits

- A prompt mixing a question with an instruction still blocks edits. Send a
  separate, direct instruction to authorize the work.
- If approval context is missing, restate the complete task, scope, and
  authorization in chat. Repeating a denied tool call does not grant permission.
- Checker failures can block edits. Confirm that the host CLI on `PATH` is
  current and its noninteractive login works; read-only investigation remains
  available.
- Host coverage differs. Codex checks final responses only; checks on any host
  cannot retract streamed prose or undo completed actions.
- Background subagent handbacks can be mistaken for user prompts where the
  host does not identify their origin. Use supported foreground collection
  when that distinction is unverified.
- Shared review coordination is implemented, but supervised cross-host
  launch-to-handback trials are still pending.

These are guardrails, not a security boundary. Unsupported tools and shell
indirection can evade checks, and agents with settings access can disable them.
Keep the host's own permissions enabled for security-critical restrictions.

## Reference and development

| Topic | Documentation |
| --- | --- |
| Guard behavior, recovery, model usage, and privacy | [docs/guardrails.md](docs/guardrails.md) |
| Settings and synchronization | [docs/configuration.md](docs/configuration.md) |
| Skills, review loops, and worktree setup | [docs/workflows.md](docs/workflows.md) |
| Documentation-cache behavior and troubleshooting | [docs/documentation-cache.md](docs/documentation-cache.md) |
| Local development, plugin updates, and releases | [docs/development.md](docs/development.md) |

Contributors should start with [AGENTS.md](AGENTS.md) and
[.github/copilot-instructions.md](.github/copilot-instructions.md).
