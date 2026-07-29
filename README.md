# ioncache-ai-tools

Personal Claude Code hooks, packaged as an installable plugin so they apply
everywhere without touching any individual project's `.claude/` directory.

## Hooks

- **classify_question.py** (UserPromptSubmit) - flags a session when the
  latest prompt contains a question. Blocks on any question, even one with
  an instruction attached, since a reliable classifier for "question with a
  real instruction attached" turned out to be more trouble than it's worth.
- **block_pending_question.py** (PreToolUse) - while a question is pending,
  denies state-changing tool calls (Edit/Write/git push/etc). Read-only
  lookups stay allowed, since answering a question well often means looking
  something up. Clears on the next prompt.
- **fix_emdash_tool_input.py** (PreToolUse) - silently rewrites em-dashes in
  Bash/Write/Edit/MultiEdit tool input before the tool runs. Skips anything
  under an `i18n` path segment, since translated copy can legitimately use
  an em-dash and shouldn't be rewritten without a human reviewing it.
- **block_emdash_turn.py** (Stop) - blocks ending a turn if the assistant's
  own reply contained an em-dash. Scans only the text generated since the
  last real user prompt (not tool results, which the transcript format also
  marks as "user" entries), and only the portion not already reported by an
  earlier Stop attempt in the same turn, so a fixed retry doesn't loop
  forever on old, already-sent text that can't be unwritten.

## Install

From within Claude Code:

```
/plugin marketplace add <your-github-username>/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Enabling it goes in your **global** `~/.claude/settings.json`
(`enabledPlugins`), so it's active in every project, not just the one you
installed it from.

## Local development

Before pushing, test against the working copy directly:

```
/plugin marketplace add ~/projects/personal/ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Hooks load at session start, so restart `claude` after any change to
`hooks/hooks.json` or the scripts under `hooks/scripts/`.
