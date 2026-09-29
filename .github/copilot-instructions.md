# Repository instructions

## Architecture

This repository ships reusable AI-assistant behavior as a plugin for Claude
Code and Codex. Python hooks enforce behavior, Markdown commands and skills
instruct the assistant, and a Node.js helper creates configured git worktrees.
Python uses the standard library; JavaScript uses CommonJS and Node built-ins.
Use Python 3.11+ for `tomllib`, Node.js, and Git in a POSIX environment
(`rule_engine.py` uses `SIGALRM`).

- Both plugin packages share `hooks/hooks.json`, which wires
  `UserPromptSubmit`, `PreToolUse`, and `Stop`. `.codex-plugin/plugin.json`
  explicitly points to that file; Claude uses the conventional hooks location.
  Keep shared metadata in the two plugin manifests consistent. Marketplace
  registration lives in `.claude-plugin/marketplace.json` and
  `.agents/plugins/marketplace.json`, with different schemas.
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
  setup in that JSON, not in the helper.

## Validation commands

Run from the repository root:

```sh
python3 hooks/scripts/rule_engine_self_check.py < /dev/null
python3 hooks/scripts/pending_question_self_check.py < /dev/null
node scripts/create-worktree.js --self-test
```

The Python scripts run in CI; the Node self-test exercises worktree path
containment. Extend the existing assertion-based self-checks for changes to
their respective behavior.

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
         hooks/hooks.json; do
  python3 -m json.tool "$f" > /dev/null || exit 1
done
```

[`.github/workflows/validate.yml`](workflows/validate.yml) also checks command
and skill frontmatter and rejects literal U+2014 characters in Python,
Markdown, JSON, and JavaScript files.

## Hook and rule conventions

- Hook payloads arrive as JSON on stdin. Reserve stdout for the hook protocol;
  diagnostics belong on stderr. Prompt reminders require
  `hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: ...}`.
  A bare top-level `additionalContext` is ignored. Tool decisions similarly
  belong inside `hookSpecificOutput` with `hookEventName: "PreToolUse"`.
  Stop hooks use top-level `decision`/`reason`.
- Resolve shipped files relative to the script or `${CLAUDE_PLUGIN_ROOT}`.
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
  `(global disabled + project disabled) - project enabled`, then union both
  tools' results. Claude uses global/project
  `.claude/ioncache-ai-tools.local.json` with camelCase keys; Codex uses
  `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`) with snake_case
  keys and exact project-path tables. See [the config examples](../README.md#disabling-a-rule).
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
- Final-response punctuation checks use `last_assistant_message`, not
  transcript parsing. `fix_emdash.py` rewrites edit/write content but denies
  Bash input: inserting whitespace could change shell arguments.

## Prompts, documentation, and local development

- Commands and skills start with YAML frontmatter containing `name` and
  `description`. Keep skill descriptions specific about when they activate.
- Never write literal em dashes in source, fixtures, documentation, or output.
  Construct the character as `chr(0x2014)` when testing or implementing its
  detection. Follow [the documentation-writing skill](../skills/documentation-writing/SKILL.md)
  for prose conventions.
- Preserve the [answer-questions skill](../skills/answer-questions/SKILL.md):
  answer direct questions with reasoning before taking action; do not attach
  unrequested designs or rewrites. `docs_first_guard.py` requires current
  source lookups for external API, CLI, and library specifics.
- Use `/create-worktree` or `node scripts/create-worktree.js <git-worktree-add-args>`
  when creating worktrees so local setup is applied. Preserve lexical and
  symlink-resolved path containment checks in the helper.
- Both hosts copy plugin files into an install cache. Editing this checkout
  alone does not update an installed plugin. Reinstall after plugin-source
  changes and start a fresh session/thread; see
  [local development](../README.md#local-development) for host-specific commands.
  Rule-disable config is outside that cache and takes effect immediately.
- [README.md](../README.md) describes current behavior.
  [Design documents](../docs/superpowers/specs/) and
  [implementation plans](../docs/superpowers/plans/) include historical
  JavaScript-engine designs; check them against the current Python code.
  [The roadmap](../docs/ROADMAP.md) distinguishes shipped behavior from proposed rules.
