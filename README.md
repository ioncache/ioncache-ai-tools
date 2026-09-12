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
| `require_answer_questions_skill.py` | UserPromptSubmit | Reuses `classify_question.py`'s marker; tells the assistant to apply the `answer-questions` skill when the prompt was a question |
| `block_pending_question.py` | PreToolUse | Denies mutating tools until a pending question is answered |
| `rule_engine.py PreToolUse` | PreToolUse | Runs every `hooks/rules/*` rule registered for this event (deny or rewrite) |
| `rule_engine.py UserPromptSubmit` | UserPromptSubmit | Runs every `hooks/rules/*` rule registered for this event (injects reminders) |
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

One file per rule, loaded by `rule_engine.py`. Adding a rule never touches
engine code. Three shapes:

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
| `block_raw_worktree_add` | Scripted | PreToolUse | Denies creating a worktree by raw git or oh-my-zsh's `gwta` alias; points to `/create-worktree` instead |
| `scope-exactly-what-asked` | Always-on | UserPromptSubmit | Reminds to do exactly what was asked, nothing more |
| `verify-state-before-claiming` | Always-on | UserPromptSubmit | Reminds to verify current status before stating it, never from memory |

### Disabling a rule

Add config to either tool's own files, whichever CLI you use. No repo file,
no environment variable. Disabling a rule once, globally, is the common
case, most people who don't want a rule don't want it in any project, so
global config is the baseline and project-level config is the exception,
used only to override that baseline for one specific project (in either
direction: a project can disable a rule that's enabled everywhere else, or
re-enable one that's disabled everywhere else).

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

A rule's id is its filename minus the extension. Resolution per tool: start
from that tool's global config, add anything the project config disables,
then remove anything the project config enables. Both tools' results are
then unioned, disabling a rule in either one disables it. There's no
global-scope `enabledRules`/`enabled_rules`: with nothing disabled globally,
every rule already runs, so a global enable list would have nothing to
override. Takes effect immediately, on the next tool call. This config is
read fresh from disk every time, unlike changes to the plugin's own files
(see Local development below), which do require a reinstall.

Full design: `docs/superpowers/specs/2026-09-11-rule-config-design.md`.

Full design: `docs/superpowers/specs/2026-09-04-generic-rule-engine-design.md`.

The engine was later rewritten from Node to Python; see
`docs/superpowers/specs/2026-09-11-python-rule-engine-rewrite.md` for why
and what changed. The two docs above still describe the current matching/
loading/config design accurately, only the implementation language and the
scripted-rule file extension (`.py`, not `.js`) changed.

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

Before pushing, run the rule engine's self-check:

```bash
python3 hooks/scripts/rule_engine_self_check.py < /dev/null
```

Then test against the working copy directly.

### Claude Code

```text
/plugin marketplace add <local path to repo>
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

Claude Code copies the plugin's files into its own cache at install time and
never re-reads the live source directory afterward, even across session
restarts. After any change (`hooks/hooks.json`, the scripts under
`hooks/scripts/`, the rules under `hooks/rules/`, or either manifest),
reinstall to force a fresh copy, then start a new session:

```text
/plugin uninstall ioncache-ai-tools@ioncache-ai-tools
/plugin install ioncache-ai-tools@ioncache-ai-tools
```

### Codex

```bash
codex plugin marketplace add <local path to repo>
codex plugin add ioncache-ai-tools@ioncache-ai-tools
```

Codex has the identical caching behavior: it copies the plugin into
`~/.codex/plugins/cache/` at install time and never re-reads the live source
afterward. After any change, reinstall to force a fresh copy:

```bash
codex plugin remove ioncache-ai-tools@ioncache-ai-tools
codex plugin add ioncache-ai-tools@ioncache-ai-tools
```

## Known limitations and security considerations

**A rule's disable-config isn't itself protected from the agent it's meant
to guard.** The per-rule disable config (see "Disabling a rule" above) is a
plain file in the project (`.claude/ioncache-ai-tools.local.json`) or in
Codex's own `config.toml`, both of which an AI agent using the tool normally
has Edit/Write access to. An agent could in principle add a rule's id to
`disabledRules`/`disabled_rules` itself, which would defeat the point of a
rule meant to guard the agent's own actions (`never_kill_without_asking`,
for example). The current design has no concept of a mandatory,
non-disableable rule, since the original goal was that a user can disable
any individual rule by hand-editing the config. Hardening this (e.g. a
`mandatory: true` flag on a rule file that the engine refuses to honor a
disable request for) is a real design change to what the feature
guarantees, not a bug fix, and hasn't been made.

**Two rules use real command tokenization; the rest are still text
heuristics, not a security boundary.** `never_kill_without_asking` and
`no_manual_lockfile_edit_bash` tokenize the command (Python's `shlex`)
and check the executable position of each simple command, rather than
matching text anywhere in the string. That closes two gaps a flat-text
match had: a plain argument that happens to contain the guarded word no
longer false-matches (`echo kill` and `ls /tmp/kill` are both correctly
ignored now, since `kill` isn't in command position in either), and a
quoted argument containing an operator character like `|` no longer
exposes it (`grep "kill|pkill|killall" file` is a single quoted token,
not three separately-matched pieces).

It also introduces a different gap that the old position-blind text
match didn't have: a wrapper command around the guarded word (`timeout
5 kill -9 1234`, `nice kill -9 1234`) is not currently recognized,
since only the first token of each simple command is checked. The old
regex would sometimes catch these by luck, since it matched the
guarded word anywhere in the text regardless of position. This is a
known, accepted trade-off for now, not a fix; closing it means teaching
the matcher each wrapper's own flag/argument shape (e.g. `timeout`
takes a required duration before the wrapped command), which is real
scope beyond the false-positive fix this was solving.

`block_raw_worktree_add` still uses the older text-normalization
approach (`normalize_shell_command`) rather than tokenization, and
keeps both of the gaps above for the patterns it matches. Shell
expansion or indirection that produces a guarded command without the
guarded word ever appearing literally in the text (a variable or
command substitution) is a gap for every rule here regardless of
approach, since none of them actually execute or expand the shell.
These rules are meant to
catch the common case and prompt a pause, not to withstand deliberate
evasion.

**A native permission deny list is a stronger, complementary backstop, and
you have to add it yourself.** Claude Code's `permissions.deny` does real
shell-aware matching: it splits compound commands on shell operators,
strips known wrappers (`timeout`, `nice`, `nohup`, bare `xargs`, etc.)
before matching, and its own docs give `/bin/rm -rf` and `bash -c 'rm -rf'`
as things a `Bash(rm *)` deny rule catches, exactly the path-qualification
gap a hand-rolled regex has to special-case. It's also enforced
independently of hooks: a matching deny rule blocks the call regardless of
what a `PreToolUse` hook returns. Codex has a closer analog in its
`execpolicy` `.rules` files, which match on parsed argv rather than raw
text. Neither is something this plugin can ship for you: permissions and
execpolicy rules aren't a supported plugin contribution in either tool, so
they only exist if you add them to your own personal config. For the
commands this repo already treats as dangerous, add to your own
`~/.claude/settings.json`:

```json
{
  "permissions": {
    "deny": ["Bash(kill:*)", "Bash(pkill:*)", "Bash(killall:*)"]
  }
}
```

This plugin's `never_kill_without_asking` rule stays in place regardless,
since it's the only piece of this that installs automatically and can
carry a custom message coaching the assistant on what to do next, a bare
deny rule can't do either of those.
