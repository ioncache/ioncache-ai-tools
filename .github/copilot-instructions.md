# Repository instructions

Keep this file focused on developing the repository. Assistant behavioral
rules belong in the plugin's hooks, rules, and skills, not duplicated here.

## Architecture

This repository ships reusable AI-assistant behavior as a plugin for Claude
Code, Codex, and GitHub Copilot CLI. Python hooks enforce behavior, Markdown
commands and skills instruct the assistant, and a Node.js helper creates
configured git worktrees.
Python uses the standard library; JavaScript uses CommonJS and Node built-ins.
Use Python 3.11+ for `tomllib`, Node.js, and Git in a POSIX environment
(`rule_engine.py` uses `SIGALRM`).

- Claude Code uses `hooks/hooks.json`, which wires `UserPromptSubmit`,
  `PreToolUse`, and `Stop`. Codex uses `.codex-plugin/plugin.json` and
  `hooks/codex-hooks.json`; Copilot uses `.github/plugin/plugin.json` and
  `hooks/copilot-hooks.json`. Their adapters share `hook_adapter_common.py`
  for ordered execution of the shared manifest and patch parsing.
  Keep shared metadata in all three plugin manifests consistent. Marketplace
  registration lives in `.claude-plugin/marketplace.json` and
  `.agents/plugins/marketplace.json`, with different schemas.
- Copilot's adapter runs the shared manifest's scripts, translating
  native inputs and outputs. Use `userPromptTransformed`, not
  `userPromptSubmitted`, for reminders: Copilot drops the latter's command
  output. The adapter preserves transformed prompt content and adds context.
- Codex launches matching hooks concurrently. Register one adapter command
  per prompt/tool event so question classification precedes its consumer.
  Normalize `apply_patch` from `tool_input.command`, checking every target
  and added line. Deny required rewrites instead of altering patch context.
  Adapter errors exit 2 to block; safe calls leave permissions unchanged.
- `hooks/scripts/rule_engine.py` owns rule discovery, matching, config
  resolution, and output merging. Rules live in `hooks/rules/`; standalone
  hooks handle question state, documentation reminders, optional graphify
  context, and final-response punctuation.
- `commands/*.md` are slash-command prompts. `skills/*/SKILL.md` are reusable
  instructions with activation descriptions. Their examples describe behavior
  for consuming projects, not necessarily this plugin's implementation stack.
- `/create-worktree` invokes `scripts/create-worktree.js`, which wraps
  `git worktree add` and applies the main worktree's `.worktree-setup.json`.
  Setup order is copies, `afterCopy` writes, symlinks, then shell commands.
  Missing config is created with generic defaults. Keep repository-specific
  setup in that JSON, not in the helper. Preserve lexical and symlink-resolved
  path containment checks.

## Validation commands

Run from the repository root:

```sh
python3 hooks/scripts/rule_engine_self_check.py < /dev/null
python3 hooks/scripts/pending_question_self_check.py < /dev/null
python3 hooks/scripts/copilot_adapter_self_check.py < /dev/null
python3 hooks/scripts/codex_adapter_self_check.py < /dev/null
node scripts/create-worktree.js --self-test
```

These checks run in CI; the Node self-test exercises worktree setup and path
containment. Extend the existing assertion-based self-checks for changes to
their respective behavior.

Run one Copilot adapter test with:

```sh
python3 hooks/scripts/copilot_adapter_self_check.py CopilotAdapterTests.test_native_shell_rules
```

For a single existing question-classifier test, select one zero-based fixture
index instead of running the complete self-check:

```sh
PYTHONPATH=hooks/scripts python3 - <<'PY'
from pending_question_self_check import QUESTION_FIXTURES, has_question
message, expected, note = QUESTION_FIXTURES[1]
assert has_question(message) is expected, note
PY
```

Syntax and manifest checks used by CI:

```sh
python3 -m py_compile hooks/scripts/*.py hooks/rules/*.py
for f in hooks/scripts/*.js scripts/*.js; do node --check "$f" || exit 1; done
for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json \
         .codex-plugin/plugin.json .agents/plugins/marketplace.json \
         .github/plugin/plugin.json hooks/hooks.json hooks/codex-hooks.json \
         hooks/copilot-hooks.json; do
  python3 -m json.tool "$f" > /dev/null || exit 1
done
```

[`.github/workflows/validate.yml`](workflows/validate.yml) also checks command
and skill frontmatter and rejects literal U+2014 characters in Python,
Markdown, JSON, and JavaScript files. Em-dash detection code and fixtures
construct the character with `chr(0x2014)` to pass this source check.

## Hook and rule conventions

- Hook payloads arrive as JSON on stdin. Reserve stdout for the hook protocol;
  diagnostics belong on stderr. Prompt reminders require
  `hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: ...}`.
  A bare top-level `additionalContext` is ignored. Tool decisions similarly
  belong inside `hookSpecificOutput` with `hookEventName: "PreToolUse"`.
  Stop hooks use top-level `decision`/`reason`.
- Copilot adapter output uses native `modifiedTransformedPrompt`,
  `permissionDecision`/`permissionDecisionReason`, or `modifiedArgs`.
  A rewrite must not include `permissionDecision: "allow"`: preserve normal
  permission checks. Raw `apply_patch` checks all targets and added lines;
  deny required rewrites rather than altering patch context.
- Resolve shipped files relative to the script or the host's plugin-root
  variable (`${CLAUDE_PLUGIN_ROOT}`, `${PLUGIN_ROOT}`, or `${COPILOT_PLUGIN_ROOT}`).
  The process working directory is the consuming project, used for project
  config and graphify detection, not the installed plugin directory.
- Add one `.json` or `.py` file per rule without modifying the engine.
  JSON rules declare `event`, optional `toolNames`, `matcher`, `action`, and
  `message`. Python rules export `EVENT`, optional `TOOL_NAMES`,
  `matches(hook_input)`, and either `check(hook_input)` or `ACTION`/`MESSAGE`.
  Scripted checks return `None` or an action dict, not the final hook envelope.
- Rule filenames determine both sorted evaluation order and public config IDs
  (filename without extension). Disabled rules are excluded before importing
  Python modules. A deny beats every rewrite; otherwise only the first rewrite
  is applied, with a warning for multiple rewrites. Prompt injections are
  concatenated with blank lines. Preserve per-rule error isolation and the
  engine's five-second watchdog.
- Disable config is read fresh on every invocation. For each tool, resolve
  `(global disabled + project disabled) - project enabled`, then union all
  tools' results. Claude uses global/project
  `.claude/ioncache-ai-tools.local.json` with camelCase keys; Codex uses
  `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`) with snake_case
  keys and exact project-path tables. See [the config examples](../README.md#disabling-a-rule).
  Copilot uses `$COPILOT_HOME/ioncache-ai-tools.local.json` (default
  `~/.copilot/`) and `.github/copilot/ioncache-ai-tools.local.json`, with
  camelCase keys. Keep self-check config isolated from all three real hosts.
- Reuse `tokenize_command`, `split_into_simple_commands`, and `skip_wrappers`
  for checks that depend on executable position or related options/targets.
  `normalize_shell_command` is the older text-normalization helper, not a
  shell parser. These guards intentionally catch common accidental actions,
  not deliberate obfuscation; preserve that scope rather than building an
  exhaustive shell interpreter.
- Question gating spans three scripts: `classify_question.py` writes
  `/tmp/.ioncache-pending-question-{session_id}`;
  `require_answer_questions_skill.py` reads it to request the skill;
  `block_pending_question.py` denies recognized mutations while it exists.
  Keep classification centralized and the classifier registered before its
  consumer. Read-only lookups remain allowed. The marker is cleared by a
  subsequent non-question prompt, not by detecting an assistant answer.
- Claude/Codex final-response checks use `last_assistant_message`. Copilot
  lacks this field, so its adapter waits for the exact current `agentStop`
  record in `events.jsonl` before reading the latest root assistant text.
  Never treat a stale turn or an unreadable transcript as a clean response.
  `fix_emdash.py` rewrites edit/write content but denies
  Bash input: inserting whitespace could change shell arguments.

## Prompts, documentation, and local development

- Commands and skills start with YAML frontmatter containing `name` and
  `description`. Keep skill descriptions specific about when they activate.
- Direct installs copy plugin files into an install cache. Editing this checkout
  alone does not update an installed plugin. Reinstall after plugin-source
  changes and start a fresh session/thread; see
  [local development](../README.md#local-development) for host-specific commands.
  Rule-disable config is outside that cache and takes effect immediately.
  Use `copilot --plugin-dir .` to load a live checkout without installing;
  `copilot plugin install .` refreshes a directly installed local copy.
- [README.md](../README.md) describes current behavior.
  [Design documents](../docs/superpowers/specs/) and
  [implementation plans](../docs/superpowers/plans/) include historical
  JavaScript-engine designs; check them against the current Python code.
  [The roadmap](../docs/ROADMAP.md) distinguishes shipped behavior from proposed rules.
