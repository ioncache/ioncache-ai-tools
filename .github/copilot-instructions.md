# Repository instructions

Keep this file focused on developing the repository. Assistant behavioral
rules belong in the plugin's hooks, rules, and skills, not duplicated here.

Read [../AGENTS.md](../AGENTS.md) for the primary enforcement and recovery
invariant that applies to all contributor work.

## Architecture

This repository ships reusable AI-assistant behavior as a plugin for Claude
Code, Codex, and GitHub Copilot CLI. Python hooks enforce behavior, Markdown
skills instruct the assistant, and Node.js helpers create configured git
worktrees and prepare releases.
Python uses the standard library; JavaScript uses CommonJS. The release helper
dynamically imports the ESM-only `conventional-changelog` packages from
contributor dev dependencies; the worktree helper uses Node built-ins.
Use Python 3.11+ for `tomllib`, Node.js 22.12+, and Git in a POSIX environment
(`rule_engine.py` uses `SIGALRM`).

- Claude Code uses `hooks/hooks.json` for lifecycle, prompt, display, tool and Stop
  events. Codex uses `.codex-plugin/plugin.json` and
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
  Prompt processing supplies stateless guidance; failures must not create fences.
- Claude and Codex launch matching hooks concurrently. Emit question guidance
  from one handler, without marker readers or stored classification state.
  Codex registers one adapter per prompt/tool event. Both adapters pass
  `apply_patch` to the shared hooks once using `tool_input.command`; the
  engine checks all targets and added lines with one rules/config load.
  Deny required rewrites instead of altering patch context.
  Adapter errors report unavailability without blocking or granting host permission.
- `hooks/scripts/rule_engine.py` owns rule discovery, matching, and output
  merging. `plugin_config.py` reconciles and resolves the shipped catalog.
  Rules live in `hooks/rules/`; `guidance.py` supplies scope, question, and
  documentation instructions plus explicit skill opt-outs. It creates no task,
  turn, launch, request-freshness, or root/child permission state.
  `scope_review.py`, `copilot_history.py`, `turn_guard.py`, `turn_review.py`,
  `block_pending_question.py`, and experimental claim checkers remain inactive
  source, with no registered hooks or active import paths. The shared store
  must not import these modules. Do not restore authorization fallbacks when
  guidance is disabled or checking fails.
  Keep narrow action denials paired with executable alternatives. Broad process
  termination is denied; exact positive PIDs and native stop controls remain
  available for processes the worker owns or was assigned to manage. The rule
  does not verify ownership. Worktree denial must expose the setup launcher
  directly even when the corresponding skill is disabled.
  Exercise defaults with real commands in disposable directories and interleaved
  root/child questions, including actual Copilot child `sessionId`/`agentId`
  payloads. Isolated adapter checks do not establish live host usability.
  Assistant display and final text are not rewritten or gated. Stop hooks only
  deliver cache notices; Copilot does not scan final transcripts.
  `block_emdash_turn.py` is retained inactive source.
  The retired `block_pending_question.py` CLI emits no decision even if an old
  registration invokes it; its helpers remain only for inactive review code.
- `hooks/scripts/docs_cache.py` shares distilled facts across Claude `WebFetch`,
  Codex single-URL `webrun` opens, and Copilot `web_fetch`. Claude answers and
  Codex excerpts are reference-only; never turn their byte or line counts into
  page coverage. Keep bypass and notice state separate by harness and session.
- `skills/*/SKILL.md` contains both workflow and behavior instructions with
  activation descriptions. Do not rely on legacy `commands/` migration:
  Codex may ignore templates or large commands. Their examples describe behavior
  for consuming projects, not necessarily this plugin's implementation stack.
  `skills/review-code/` shares `CRITERIA.md`, `CONTRACTS.md`, and
  `ORCHESTRATION.md` between standalone review and the review/fix caller.
  Leaf assignments must not re-enter the skill or spawn another review layer.
- `scripts/review_ledger.py` persists per-run review history and snapshots;
  `review_loop_state.py` validates transitions by replay. Its storeless
  `fingerprint` command reuses the snapshot implementation for standalone
  reviews. The outer loop owns ledger writes, fixes, and limits; shared review
  instructions own conditional nested coordination or flat adjudication.
  Keep ledger checks mechanical, not semantic judgments. Rich handbacks map
  to schema-1 evidence fields rather than adding event fields.
- The `create-worktree` skill invokes `scripts/create-worktree.py`, which requires
  Node.js 22.12.0+ and checks its version before launching the sibling
  `create-worktree.js` helper.
  The helper wraps `git worktree add` and applies the main worktree's
  `.worktree-setup.json`. Missing, outdated, or unverifiable Node must fail before
  any worktree/setup writes and remain recoverable by installing or upgrading
  Node or correcting `PATH`.
  Setup order is copies, `afterCopy` writes, symlinks, then shell commands.
  Missing config is created with generic defaults. Keep repository-specific
  setup in that JSON, not in the helper. Preserve lexical and symlink-resolved
  path containment checks.

## Validation commands

Run from the repository root after installing contributor tooling with `npm ci`:

```sh
python3 hooks/scripts/rule_engine_self_check.py < /dev/null
python3 hooks/scripts/pending_question_self_check.py < /dev/null
python3 hooks/scripts/turn_guard_self_check.py < /dev/null
python3 hooks/scripts/plugin_config_self_check.py < /dev/null
python3 hooks/scripts/copilot_adapter_self_check.py < /dev/null
python3 hooks/scripts/codex_adapter_self_check.py < /dev/null
python3 hooks/scripts/docs_cache_self_check.py < /dev/null
python3 hooks/scripts/claim_evidence_self_check.py < /dev/null
node scripts/create-worktree.js --self-test
python3 scripts/review_ledger_self_check.py
python3 scripts/release_self_check.py
npm run release:check
```

These checks run in CI; the Node self-test exercises worktree setup and path
containment. The Codex adapter self-check covers the shared worktree launcher's
missing-runtime recovery and the installed skill's invocation.
Extend the existing assertion-based self-checks for changes to their respective
behavior. The ledger self-check also exercises standalone
fingerprints, review-handback event fixtures, and packaged review references.

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
python3 -m py_compile hooks/scripts/*.py hooks/rules/*.py scripts/*.py
for f in scripts/*.js; do node --check "$f" || exit 1; done
for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json \
         .codex-plugin/plugin.json .agents/plugins/marketplace.json \
         .github/plugin/plugin.json hooks/hooks.json hooks/codex-hooks.json \
         hooks/copilot-hooks.json config/defaults.json; do
  python3 -m json.tool "$f" > /dev/null || exit 1
done
```

[`.github/workflows/validate.yml`](workflows/validate.yml) also checks skill
frontmatter and rejects literal U+2014 characters in Python,
Markdown, JSON, and JavaScript files. Em-dash detection code and fixtures
construct the character with `chr(0x2014)` to pass this source check.

## Hook and rule conventions

- Every active feature must have an independent opt-out in the shipped
  `config/defaults.json`, enabled by default. Configuration is part of every
  feature change, not optional follow-up work. Synchronization preserves local
  values for retained settings, adds new defaults, and removes retired settings.
  Add coverage for the opt-out and keep unrelated safeguards independent.
- Retained inactive implementations must not be imported or registered by
  active hooks. Their retired settings must not appear in the shipped catalog.
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
- Shared text rewrites emit `updatedInput` without a permission decision,
  preserving Claude's normal approval flow. Only the Codex adapter adds the
  `allow` field required by its rewrite protocol.
- Resolve shipped files relative to the script or the host's plugin-root
  variable (`${CLAUDE_PLUGIN_ROOT}`, `${PLUGIN_ROOT}`, or `${COPILOT_PLUGIN_ROOT}`).
  The process working directory is the consuming project, used for project
  config, not the installed plugin directory.
- Add one `.json` or `.py` file per rule and its default setting without modifying the engine.
  JSON rules declare `event`, optional `toolNames`, `matcher`, `action`, and
  `message`. Python rules export `EVENT`, optional `TOOL_NAMES`,
  `matches(hook_input)`, and either `check(hook_input)` or `ACTION`/`MESSAGE`.
  Scripted checks return `None` or an action dict, not the final hook envelope.
- Rule filenames determine both sorted evaluation order and public config IDs
  (filename without extension). Disabled rules are excluded before importing
  Python modules. Bundled rules absent from the shipped catalog never load,
  even if stale settings try to enable them. A deny beats every rewrite; otherwise only the first rewrite
  is applied, with a warning for multiple rewrites. Prompt injections are
  concatenated with blank lines. Preserve per-rule error isolation and the
  engine's five-second watchdog. Missing, non-directory, or unlistable rule
  paths are discovery failures, not empty rule sets. Discovery exceptions
  propagate to `main()`, which reports checker unavailability; a readable empty directory
  or no enabled rules for an event remains valid. Engine-wide errors and
  watchdog expiry report unavailability without granting permission or blocking
  the entire worker. Preserve already-computed decisions; a known denial wins.
  Shared adapter execution has an internal deadline before the native hook
  timeout: 20 seconds for shared execution, with smaller per-handler limits.
  The adapters also bound the whole invocation to 25 seconds, including
  configuration work. Session-end deadlines are two seconds for Codex and
  four seconds for Copilot. Config writer locks
  use short bounded waits and preserve readable preferences on runtime failure.
  Pre-tool and final adapter hooks have 30-second native limits.
  Self-checks install isolated fake reviewer executables to catch accidental
  model launches; never let offline tests launch a real model against fixtures.
- Configuration is reconciled on each hook invocation and by the explicit
  `plugin_config.py` install/update command. All three hosts use plugin-owned
  JSON with a `features` boolean map. Global files contain every shipped key;
  project overrides stay sparse. Resolve defaults, global values, embedded
  project values, then the project file. Union disables across hosts.
  Legacy JSON lists migrate in place; Codex TOML is a one-time migration source
  only when the companion JSON does not exist. Never rewrite host TOML.
  Read unchanged settings without a writer lock; re-read under the lock before
  atomic replacement, preserving symlinks. Runtime persistence failures warn
  but retain valid effective settings; explicit synchronization fails nonzero.
  Reuse settings within a hook invocation. Never cache across invocations.
  Malformed or unreadable settings remain untouched: warn and pause plugin
  features so users can repair their configuration, without granting host
  permissions. See [../docs/configuration.md](../docs/configuration.md).
  Each skill has a `skill:<name>` opt-out: explicit skill-tool loads are blocked
  and bootstrap instructions cover automatic/slash-command activation.
  Skill visibility remains host-managed; do not claim plugin config unregisters
  a skill. Keep self-check HOME and both host directories isolated.
- Reuse `tokenize_command`, `split_into_simple_commands`, and `command_executable`
  for checks that depend on executable position or related options/targets.
  Use `is_shell_operator` for punctuation comparisons: decoded shell words
  can contain the same characters without being operators.
  `normalize_shell_command` is the older text-normalization helper, not a
  shell parser. These guards intentionally catch common accidental actions,
  not deliberate obfuscation; preserve that scope rather than building an
  exhaustive shell interpreter.
- `guidance.py` uses the pure question classifier for advisory text only.
  Questions do not suspend existing assignments. Native identities are passed
  through rather than mapped into shared permission storage; one agent's
  conversation must never create a tool fence for another.
- Cache diagnostics use user-facing `systemMessage` or Copilot progress
  output, never repeated `additionalContext` or mandatory final-answer prose.
  Keep progress parsing at the Copilot boundary; shared handlers emit one JSON
  object. Never call the retained claim-evidence receipt path from cache delivery.
- `fix_emdash.py` rewrites edit/write content but denies
  Bash input: inserting whitespace could change shell arguments.

## Prompts, documentation, and local development

- Every plugin version change must update `CHANGELOG.md` with New, Updated
  and Fixed items from commits since the preceding version. Use
  `npm run release -- VERSION` from a clean feature worktree after
  committing the intended changes. Review its output and commit all three
  plugin manifests with the changelog. See
  [../docs/development.md#version-changes-and-changelog](../docs/development.md#version-changes-and-changelog).
- Skills start with YAML frontmatter containing `name` and
  `description`. Keep skill descriptions specific about when they activate.
- Claude relative-path plugins from local-directory marketplaces load in place;
  restart or `/reload-plugins` after source changes. Remote installs are cached.
  Codex and direct Copilot installs use caches; refresh those installed copies
  and start a fresh session/thread after source changes. See
  [../docs/development.md#local-development](../docs/development.md#local-development)
  for host-specific commands.
  Rule-disable config is outside that cache and takes effect immediately.
  Use `copilot --plugin-dir .` to load a live checkout without installing;
  For persistent local Copilot loading, register the checkout with
  `copilot plugin marketplace add /absolute/path/to/checkout`, then install
  `ioncache-ai-tools@ioncache-ai-tools`. Direct `plugin install .` is unsupported.
- [../README.md](../README.md) is the concise guide to current functionality,
  installation, usage, and known issues for plugin users. Keep repository
  contributor setup and release workflows out of it.
  Keep the complete shipped skill catalog and direct host-specific invocation
  instructions in the README, not only in linked references.
  Keep detailed references in `docs/`; do not add historical
  behavior or exhaustive implementation details to the README.
  [Design documents](../docs/superpowers/specs/) and
  [implementation plans](../docs/superpowers/plans/) include historical
  JavaScript-engine designs; check them against the current Python code.
