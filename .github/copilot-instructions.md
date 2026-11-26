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
Python uses the standard library; Node helpers use CommonJS. Claude's native
settings mod in `hooks/plugin-settings.mjs` uses the host-required ES module
format and the shared Python settings helper, not a separate preference store.
Its native `.test.ts` tests run offline with the contributor Claude CLI.
Claude's response-validation mod also uses the native ES module format.
The release helper
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
  Prompt processing supplies guidance and records only the root question
  marker; failures report unavailability and must not create fences.
- Claude and Codex launch matching hooks concurrently. `guidance.py` is the
  only prompt handler that classifies questions: it emits the question
  contract and records or clears the root identity's question marker.
  Codex registers one adapter per prompt/tool event. Both adapters pass
  `apply_patch` to the shared hooks once using `tool_input.command`; the
  engine checks all targets and added lines with one rules/config load.
  Deny required rewrites instead of altering patch context.
  Adapter errors report unavailability without blocking or granting host permission.
- `hooks/scripts/rule_engine.py` owns rule discovery, matching, and output
  merging. `plugin_config.py` reconciles and resolves the shipped catalog.
  Rules live in `hooks/rules/`; `guidance.py` supplies scope, question, and
  documentation instructions plus explicit skill opt-outs. It creates no task,
  launch, request-freshness, or root/child permission state. Its only stored
  state is the per-identity question marker described below.
  `block_pending_question.py` is the registered question-turn `PreToolUse`
  guard. `scope_review.py`, `copilot_history.py`, `turn_guard.py`,
  `turn_review.py`, and experimental claim checkers remain inactive
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
  Claude's `hooks/response-validation/` mod buffers response streams and rewrites
  their text before delivery. It uses a tool-less native small-model completion,
  the caller's own bounded history, and no approval or retry state. Failed
  validation replaces the draft with an unavailability notice without denying
  subsequent work. Keep stream text and returned metadata consistent, preserve
  unrelated tool calls and opaque chunk handles, and never leak drafts on
  cancellation or hook failure. `response-validation` independently opts out.
  Copilot and Codex do not run this mod. Stop hooks only deliver cache notices.
  `block_emdash_turn.py` is retained inactive source.
  Question markers (`classify_question.marker_path`) are keyed by session and
  agent identity. A marker requires a positively identified root-user prompt.
  The shared boundary uses `_ioncache_prompt_origin: "user"`; this is an
  internal contract, not a native host field. Root identity alone, a prompt
  event name, and the absence of known text prefixes do not establish origin.
  Native prompt payloads alone do not establish user origin and do not create
  markers. Copilot's `copilot_question.py` correlates the current root prompt
  with native `user.message` provenance at pre-tool time and passes the result
  to the shared guard. It reads bounded local history without storing another
  permission state. Child identities, agent/automation/autopilot messages,
  completed root answers, and unknown or failed evidence must not fence work.
  It matches skill expansions only in their recorded leading or inline form;
  prompt mode's unexpanded leading `/command` is an instruction.
  `claude_question.py` correlates `prompt_id` with a root transcript message's
  explicit `origin.kind: "human"`; completed answers and newer prompts release it.
  Same-prompt Skill tool content and image-read notes do not.
  `codex_question.py` requires a matching explicitly user-triggered turn without
  delegated lineage and its original `user.text` input. Later user-role input
  other than environment or selected-skill context makes that attribution
  ambiguous and releases it. Explicit leading skill invocations are instructions
  on every host; inline mentions keep a question. Exec and automated triggers
  do not establish human origin. Both re-read bounded native history at tool time,
  never persist another permission state or fall back to markers on missing evidence.
  `question_history.py` owns the shared bounded, regular-file-only reader.
  Synthetic normalized-input tests do not establish native host support.
  See `docs/guardrails.md#prompt-origin-evidence-and-gaps` and the sanitized
  captures in `hooks/fixtures/prompt-origins.json` and
  `hooks/fixtures/copilot-question-events.json`,
  `hooks/fixtures/claude-question-events.json`, and
  `hooks/fixtures/codex-question-events.json`.
  `claude_prompt.py` normalizes observed Claude framing at the guidance entry
  boundary. It removes system-reminder blocks from question text and recognizes
  task-notification or agent-message segments anywhere in a batch, not just
  at the beginning. Keep the recorded model-facing batches in
  `hooks/fixtures/claude-batched-prompts.json` distinct from hook-stdin captures.
  Keep Copilot's captured same-interaction memory records distinct from submitted
  prompts. Other Copilot and Codex batching/reminder formats remain unverified.
  The shared classifier keeps clauses ending in `?`. Starting words count
  only for a whole, single-clause prompt of at most 12 words and 120 characters,
  without a trailing period, newline, colon or semicolon. Commas may repeat
  identical emphasis, not introduce other clauses. Declarative starters inside
  longer prose must not create question turns.
  Every prompt clears its own marker before settings and guidance evaluation,
  including host-started, unknown-origin and parent-written turns. Neither
  an agent identity nor a parent identity may create a root question marker.
  A guidance or marker-clear failure must not create one afterward.
  The guard uses only the caller's own marker or native root-message evidence,
  never a parent's state, so a root question cannot stop a running child.
  It denies `is_mutating`
  matches and `WORK_CONTROL_TOOLS` (launching, messaging, or stopping workers;
  task/todo creation) so the questioned agent cannot delegate around it.
  Marker and settings failures report unavailability without a denial.
  Do not restore the old root-marker fallback, request-ID or stale-parent
  denials, or task approvals.
- `hooks/scripts/docs_cache.py` shares distilled facts across Claude `WebFetch`,
  Codex single-URL `webrun` opens, and Copilot `web_fetch`. Claude answers and
  Codex excerpts are reference-only; never turn their byte or line counts into
  page coverage. Keep bypass and notice state separate by harness and session.
  A Claude `WebFetch` hit needs a fact distilled for the same question. Every
  hit names the live marker (`[live]` prompt prefix, or a `#live` URL fragment
  for tools without a prompt); marked calls never read the cache or emit allow.
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
  Store ledgers and objects outside repositories: standalone XDG state storage
  or the development run's pinned private or recovery `reviews/` directory. Preserve
  schema-1 history during legacy migration, and distinguish offline inspection
  and audit archives from live acceptance. File hints are not edit allowlists;
  review the actual correction delta while preserving HEAD/index ownership.
- `review_assignments.py` freezes source-language evidence and all policy
  resources in schema-3 phase plans with unique report namespaces, separately
  from review switches and user exclusions. JSDoc requires
  JavaScript; general categories adapt to the actual stack. Unknown language
  facts leave coverage unresolved, not a permission fence. Retain old evidence
  and consumed work when a corrected contract requires a new phase.
- `scripts/review_comments.py` publishes review-code findings for the
  `--post-comments` caller step in `skills/review-code/POSTING.md`. It checks
  eligibility, anchors comments to the merge-base diff, applies the sensitive
  findings policy and posts one `COMMENT` review. All GitHub calls go through
  its `api()` function; the self-check replaces it with fakes and never posts.
- `review_reporting.py` projects unresolved material findings independently of
  action and disposition. `development_followups.py` carries the cumulative
  inventory and optional native publisher receipts. The existing draft/ready
  workers own follow-up issues and the PR's known-issue section; ticket failures
  add no acceptance gate. Keep full evidence private and disclosure-filter PR drafts.
- `scripts/development_manifest.py` validates approved inputs, and
  `scripts/development_run.py` owns private development-run bookkeeping outside
  the repository. It does not launch models or publish. `development_handoff.py`
  owns script-generated batches, persisted claims, report validation and collection.
  `development_executor.py` pins runtime resources outside the reviewed tree;
  `development_jobs.py` generates purpose-only jobs and validates report contracts.
  The Claude template in `workflows/` runs one generated batch with no control
  models or acceptance authority. Keep offline
  lifecycle checks distinct from live-host qualification. Forward frozen
  single-purpose packets, not generic catalogs or the implementation context.
  Final acceptance reuses the shared category checker and pins its full-phase
  evidence to the completed ledger's root, base and snapshot.
  Provider checks precede reservation; schema-1 approval content stays unchanged.
  External worktree destinations are resolved and pinned with store separation.
  `development_progress.py` owns private review checkpoints and the lock-free
  `watch` reader. `development_models.py` validates native role choices and
  records requested versus observed identities. Workflow read-only leaves run
  concurrently with exclusive fixer barriers; never treat a selected model as
  an observed identity or hardcode a model ranking.
- `scripts/development_audit.py` exports selected process evidence and an explicitly
  reviewed public narrative. Live publication runs as an approved audit worker,
  not as controller bookkeeping. `publish-archive` uses the same guarded
  publisher independently of run state under the existing manifest permissions.
  Its receipt stays beside the archive, never advancing `RUN.json` or readiness.
  Publish to the modified repository's wiki,
  prepend one current row per PR to `Automated-Pull-Request-Audits`, preserve
  other wiki content and PR-body text, keep one index link on Home, and exclude raw private
  inputs, prompts and reports. Extend the development self-check's isolated Git
  wiki remotes and fake-API publication fixtures; never publish to GitHub during
  offline checks. Wiki access and initialization are preflight prerequisites;
  never fall back to an audit branch or a manual upload.
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

Run from the repository root with Python 3.15 (the CI test runtime) after
installing contributor tooling. Installed plugin runtime support remains 3.11+:

```sh
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -n auto
npm run test:settings-ui
node scripts/create-worktree.js --self-test
node scripts/development_workflow_self_check.js
npm run release:check
npm run test:responses
```

These checks run in CI; the Node self-test exercises worktree setup and path
containment. The Codex adapter self-check covers the shared worktree launcher's
missing-runtime recovery and the installed skill's invocation.
Extend the pytest-collected self-checks for changes to their respective behavior.
Use in-process calls and shared immutable starting fixtures by default. Reserve
subprocesses for the boundaries they verify, not ordinary fixture progression.
Never parallelize environment-changing tests with threads. Keep test dependencies
out of runtime imports. Inspect pytest's duration report and keep the full local
run near one minute. Fixture tiers and their preconditions are documented in
[../docs/development.md#python-tests](../docs/development.md#python-tests).
The ledger self-check also exercises standalone
fingerprints, review-handback event fixtures, and packaged review references.

Run one Copilot adapter test with:

```sh
.venv/bin/python -m pytest hooks/scripts/copilot_adapter_self_check.py::CopilotAdapterTests::test_native_shell_rules
```

Run one file, or the explicit real-process tier:

```sh
.venv/bin/python -m pytest -n auto scripts/development_run_self_check.py
.venv/bin/python -m pytest -n auto -m process
```

Syntax and manifest checks used by CI:

```sh
python3 -m py_compile hooks/scripts/*.py hooks/rules/*.py scripts/*.py
for f in scripts/*.js hooks/response-validation/*.mjs; do node --check "$f" || exit 1; done
for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json \
         .codex-plugin/plugin.json .agents/plugins/marketplace.json \
         .github/plugin/plugin.json hooks/hooks.json hooks/codex-hooks.json \
         hooks/copilot-hooks.json config/defaults.json scripts/fixtures/review_quality.json; do
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
- `guidance.py` uses the pure question classifier for the question contract
  and the root identity's question marker. A question suspends the questioned
  root's own work for that turn, including an existing assignment, and nothing
  else. Native identities are passed through rather than mapped into shared
  permission storage; one agent's conversation must never create a tool fence
  for another.
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
