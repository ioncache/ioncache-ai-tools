# ioncache-ai-tools

Personal AI tools, packaged as an installable plugin for both Claude Code
and Codex, so they apply everywhere without touching any individual
project's config.

## Hooks

| Hook | Lifecycle event | What it does |
| ---- | ---------------- | ------------- |
| `classify_question.py` | UserPromptSubmit | Flags any prompt containing a question |
| `block_pending_question.py` | PreToolUse | Denies mutating tools until a pending question is answered |
| `fix_emdash_tool_input.py` | PreToolUse | Silently rewrites em-dashes in tool input |
| `block_emdash_turn.py` | Stop | Blocks the turn if the reply contains an em-dash |

## Commands

| Command | Description |
| ------- | ------------ |
| `/verify-unresolved-pr-comments` | Triage table of unresolved PR review feedback. Read-only |
| `/review-code` | Full-pass review: necessity, contracts, standards, correctness |
| `/investigate` | Read-only trace of how a feature or system works |
| `/triage-errors` | Fix a batch of failures by root cause, not one by one |

## Skills

| Skill | Description |
| ----- | ------------ |
| `answer-questions` | Answer direct questions fully before doing anything else |
| `code-complexity` | Parameter counts, nesting depth, function length, single responsibility |
| `comments` | Default to no comment; when warranted, why not what |
| `prompt-output` | Wrap generated prompt files in a single code fence |
| `unit-tests` *(opinionated, Vitest)* | BDD `describe`/`it`, AAAR comments |
| `jsdoc` *(opinionated, JS/TS)* | Required tags, typedef rules, no inline `Object` |
| `security` *(opinionated, Fastify/MongoDB examples)* | Validate at the edge, sanitize input, secrets in env |

## Install

### Claude Code

```
/plugin marketplace add <your-github-username>/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Enabling it goes in your **global** `~/.claude/settings.json`
(`enabledPlugins`), so it's active in every project, not just the one you
installed it from.

### Codex

```bash
codex plugin marketplace add <your-github-username>/ioncache-ai-tools
codex
```

Then, inside the session, open `/plugins`, select the ioncache-ai-tools
marketplace, and install it. Open `/hooks` afterward to review and trust
the hooks, then start a new thread.

## Local development

Before pushing, test against the working copy directly:

```
/plugin marketplace add ~/projects/personal/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Hooks load at session start, so restart the session after any change to
`hooks/hooks.json` or the scripts under `hooks/scripts/`.
