# ioncache-ai-tools

Personal AI tools, packaged as an installable plugin for both Claude Code
and Codex, so they apply everywhere without touching any individual
project's config.

## Hooks

| Hook | Lifecycle event | What it does |
| ---- | ---------------- | ------------- |
| `graphify_context.js` | UserPromptSubmit | When the project has a graphify knowledge graph, tells the agent to use `graphify query` instead of grep/Read/find |
| `docs_first_guard.py user-prompt-submit` | UserPromptSubmit | Flags prompts that require official/current docs |
| `docs_first_guard.py pre-tool-use` | PreToolUse | Blocks non-docs tool work until a documentation lookup happens |
| `classify_question.py` | UserPromptSubmit | Flags any prompt containing a question |
| `block_pending_question.py` | PreToolUse | Denies mutating tools until a pending question is answered |
| `block_raw_worktree_add.js` | PreToolUse | Denies creating a worktree by raw git or oh-my-zsh's `gwta` alias; points to `/create-worktree` instead |
| `rule-engine.js PreToolUse` | PreToolUse | Runs every `hooks/rules/*` rule registered for this event (deny or rewrite) |
| `rule-engine.js UserPromptSubmit` | UserPromptSubmit | Runs every `hooks/rules/*` rule registered for this event (injects reminders) |
| `block_emdash_turn.py` | Stop | Blocks the turn if the reply contains an em-dash |

## Commands

| Command | Description |
| ------- | ------------ |
| `/verify-unresolved-pr-comments` | Triage table of unresolved PR review feedback. Read-only |
| `/review-code` | Full-pass review: necessity, contracts, standards, correctness |
| `/investigate` | Read-only trace of how a feature or system works |
| `/triage-errors` | Fix a batch of failures by root cause, not one by one |
| `/create-worktree` | Wraps the git worktree command and applies the repo's `.worktree-setup.json` (untracked local config, generated caches, post-create commands); writes the file with generic defaults on first use |

### `.worktree-setup.json`

Lives at a repo's root. `/create-worktree` reads it from the main worktree and
applies it to every new worktree. A repo without one gets the file written with
generic defaults on the first run (the Claude Code local-config symlinks below,
nothing else), so it is always there to extend.

```json
{
  "copies": ["generated-cache"],
  "afterCopy": [{ "path": "generated-cache/.root", "content": "${worktreePath}\n" }],
  "symlinks": [
    ".claude/settings.local.json",
    ".claude/hooks",
    "CLAUDE.local.md",
    ".claude/hookify.*.local.md"
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
- `commands` - shell commands run in the new worktree, in order, after copies
  and symlinks, with the same `${worktreePath}` and `${mainRoot}` substitution.
  The first failure stops the run and the command exits non-zero. This is where
  repo-specific setup goes (env symlinks, installs); the plugin itself knows
  nothing about any repo's layout. Quote the placeholders, paths can contain
  spaces. The file is committed to the repo, so its commands run with the same
  trust as an install script: review it before creating a worktree in a repo
  you did not write.

### `hooks/rules/`

One file per rule, loaded by `rule-engine.js`. Adding a rule never touches
engine code. Three shapes:

- **Always-on** (`.json`, `matcher: {"type": "always"}`): injects a fixed
  reminder into `additionalContext` on every `UserPromptSubmit`.
- **Pattern** (`.json`, `matcher: {"type": "regex", "field": "...", "pattern": "..."}`):
  denies a `PreToolUse` call when a field of the tool input matches.
- **Scripted** (`.js`, exports `{event, toolNames, matches(input), async check(input)}`):
  the escape hatch for anything a regex can't express, including rewriting
  tool input in place (see `fix-emdash.js`).

Full design: `docs/superpowers/specs/2026-09-04-generic-rule-engine-design.md`.

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

## Install

### Claude Code

```text
/plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Enabling it goes in your **global** `~/.claude/settings.json`
(`enabledPlugins`), so it's active in every project, not just the one you
installed it from.

### Codex

```bash
codex plugin marketplace add https://github.com/ioncache/ioncache-ai-tools
codex
```

Then, inside the session, open `/plugins`, select the ioncache-ai-tools
marketplace, and install it. Open `/hooks` afterward to review and trust
the hooks, then start a new thread.

## Local development

Before pushing, test against the working copy directly:

```text
/plugin marketplace add <local path to repo>
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Hooks load at session start, so restart the session after any change to
`hooks/hooks.json`, the scripts under `hooks/scripts/`, or the rules under
`hooks/rules/`.
