# ioncache-ai-tools

Personal AI tools, packaged as an installable plugin for both Claude Code
and Codex, so they apply everywhere without touching any individual
project's config.

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
  Bash/Write/Edit/MultiEdit tool input before the tool runs.
- **block_emdash_turn.py** (Stop) - blocks ending a turn if the assistant's
  own reply contained an em-dash. Reads `last_assistant_message` from the
  hook input rather than parsing the transcript file by hand, the
  officially documented way to get the current turn's text on both tools.

## Commands

Explicit-invoke workflows (`/name`):

- **verify-unresolved-pr-comments** - fetches unresolved review threads and
  PR-level feedback on the active PR, returns a triage table. Read-only.
- **review-code** - full-pass code review (necessity, contract cross-checks,
  a pass per project coding standard if the repo has any, then correctness).
- **investigate** - read-only trace of how a feature or system works, entry
  point through data flow through side effects.
- **triage-errors** - groups a batch of failures by root cause and fixes
  upstream causes first, instead of patching symptoms one at a time.

## Skills

Auto-triggered by description match:

- **answer-questions** - answer direct questions fully, with the reasoning,
  before doing anything else. No deflection, no premature action.
- **code-complexity** - parameter counts, nesting depth, function length,
  single responsibility.
- **comments** - default to no comment; when one is warranted, why not what.
- **prompt-output** - when generating a prompt file, wrap the whole output in
  one code fence, nothing outside it.
- **unit-tests** (opinionated) - Vitest, BDD `describe`/`it`, AAAR comments.
  Assumes Vitest.
- **jsdoc** (opinionated) - required tags, typedef rules, no inline `Object`
  types. Assumes JS/TS.
- **security** (opinionated) - validate at the edge, sanitize input, secrets
  in env, fail without leaking internals. Examples assume Fastify/MongoDB but
  the principles are general.

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
