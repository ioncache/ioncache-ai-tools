# Per-Rule Disable Config: Design

## Problem

The rule engine's 5 pilot rules are all-or-nothing: every rule that matches an event always runs, with no way for a user to turn one off for a specific project without editing the plugin's own shipped files (which get clobbered on update/reinstall). A prior session (2026-09-10, see the `selective-hook-enable-deferred` memory) researched broader per-hook enable/disable across the whole plugin and found Claude Code has no native toggle, deferring the question with "an env var is the cheapest design if revisited." That conclusion is superseded here: env vars are explicitly out. Config must live inside each tool's own native per-project settings mechanism, not a new file this plugin invents, and not an environment variable.

## Goals

- A user can disable individual rules (by filename, minus extension) per project.
- Configuration lives inside Claude Code's and Codex's own native config surfaces, not a new repo file, not an env var.
- No platform-detection branching. The engine checks whether each possible config source exists and reads whichever do; nothing decides "which tool am I running under."
- Works whether only one tool is in use, both, or neither (falls back to every rule enabled, today's behavior).

## Non-goals

- Per-rule configuration of anything other than enabled/disabled (no severity overrides, no per-project rule parameters). Not requested.
- A UI or CLI command to edit either config source. Users hand-edit the files directly, same as any other Claude Code plugin settings file or Codex config entry.
- Caching or avoiding the Python subprocess spawn for performance. This repo's `hooks.json` already spawns a fresh `python3` process on most `UserPromptSubmit`/`PreToolUse` events via `docs_first_guard.py`, `classify_question.py`, and `block_pending_question.py`. One more spawn, gated behind a cheap `fs.existsSync` check so it only happens when `~/.codex/config.toml` actually exists, is not a new class of cost this codebase doesn't already accept.

## Two config sources, read unconditionally

### Claude Code: `.claude/ioncache-ai-tools.local.json`

This is Claude Code's own documented `plugin-settings` pattern (a per-project, gitignored settings file a plugin reads directly), not something invented for this feature. Project root is `process.cwd()`, the same assumption `hooks/scripts/graphify_context.js` already makes for locating `graphify-out/` in this repo.

```json
{ "disabledRules": ["never-kill-without-asking"] }
```

### Codex: a project-scoped table in `~/.codex/config.toml`

Verified empirically this session (installed the plugin into a real Codex instance, hand-edited `config.toml`, then ran `codex plugin add`/`remove`/marketplace-add cycles against it): a custom key placed inside `[plugins."<name>"]` gets deleted entirely by `codex plugin remove`, since Codex rewrites that whole section from scratch. A custom key placed inside `[projects."<path>"]` survived every operation tried, including plugin add/remove/re-add and marketplace re-add. Only the project section is safe.

```toml
[projects."/Users/markjubenville/projects/personal/ioncache-ai-tools".ioncache-ai-tools]
disabled_rules = ["never-kill-without-asking"]
```

There is no Codex CLI command to write this; users hand-edit `~/.codex/config.toml`, same as they already do for other Codex settings.

Codex has no confirmed project-root env var for hook subprocesses (unlike Claude Code's `$CLAUDE_PROJECT_DIR`, which this design also doesn't use, see below). `process.cwd()` is the lookup key here too, matching the same assumption used for Claude Code and consistent with the rest of this codebase.

### Why not `$CLAUDE_PROJECT_DIR`

Claude Code hook subprocesses do get a `$CLAUDE_PROJECT_DIR` env var pointing at the project root (documented in the plugin-dev hook-development reference). Using it here would be more robust than `process.cwd()` for Claude Code specifically, since a working directory can technically differ from the project root, but this design uses `process.cwd()` uniformly for both sources instead, since that is what `graphify_context.js` already relies on in this exact codebase, keeps the two sources symmetric, and avoids introducing any env var into this feature at all given how explicitly that was ruled out.

## Architecture

`rule-engine.js` gains one new function:

```js
function getDisabledRuleIds(projectRoot, { codexConfigPath = path.join(os.homedir(), '.codex', 'config.toml') } = {}) {
  const disabled = new Set()

  const claudeConfigPath = path.join(projectRoot, '.claude', 'ioncache-ai-tools.local.json')
  if (fs.existsSync(claudeConfigPath)) {
    try {
      const config = JSON.parse(fs.readFileSync(claudeConfigPath, 'utf8'))
      for (const id of config.disabledRules || []) disabled.add(id)
    } catch (err) {
      console.error(`rule-engine: failed to read ${claudeConfigPath}: ${err.message}`)
    }
  }

  if (fs.existsSync(codexConfigPath)) {
    try {
      const helperPath = path.join(__dirname, 'read_codex_disabled_rules.py')
      const result = spawnSync('python3', [helperPath, codexConfigPath, projectRoot], { encoding: 'utf8' })
      for (const id of JSON.parse(result.stdout || '[]')) disabled.add(id)
    } catch (err) {
      console.error(`rule-engine: failed to read Codex config: ${err.message}`)
    }
  }

  return disabled
}
```

`codexConfigPath` is an overridable option (default `~/.codex/config.toml`) specifically so the self-check can point it at a fixture file instead of touching the real global Codex config during tests.

`loadRulesForEvent` gains a third, optional parameter and one more filter step:

```js
function loadRulesForEvent(rulesDir, event, disabledRuleIds = new Set()) {
  if (!fs.existsSync(rulesDir)) return []
  return fs
    .readdirSync(rulesDir)
    .filter((name) => name.endsWith('.json') || name.endsWith('.js'))
    .map((name) => loadRuleFile(rulesDir, name))
    .filter((rule) => rule !== null && rule.event === event)
    .filter((rule) => !disabledRuleIds.has(path.basename(rule.name, path.extname(rule.name))))
}
```

A rule's "id" for config purposes is its filename minus extension (`never-kill-without-asking`, not `never-kill-without-asking.json`), the same across both config sources, even though the two sources use each ecosystem's own idiomatic field-name casing (`disabledRules` in JSON, `disabled_rules` in TOML, this is deliberate, not an inconsistency).

`runHook` wires it together:

```js
async function runHook(overrideRulesDir) {
  const event = process.argv[2]
  let hookInput
  try {
    hookInput = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (err) {
    return
  }

  const rulesDir = overrideRulesDir || path.join(__dirname, '..', 'rules')
  const disabledRuleIds = getDisabledRuleIds(process.cwd())
  let rules
  try {
    rules = loadRulesForEvent(rulesDir, event, disabledRuleIds)
  } catch (err) {
    console.error(`rule-engine: failed to load rules from ${rulesDir}: ${err.message}`)
    rules = []
  }

  return await runRules(rules, event, hookInput)
}
```

## The Codex helper: `hooks/scripts/read_codex_disabled_rules.py`

Plain Python, `tomllib` only (standard library since Python 3.11, confirmed available on this machine at 3.14.7). Never raises, never exits non-zero; on any failure (file missing, malformed TOML, missing section) it prints `[]` and exits 0, since this is a helper feeding an already fail-safe hook.

```python
#!/usr/bin/env python3
import json
import sys

def main():
    if len(sys.argv) != 3:
        print("[]")
        return

    config_path, project_root = sys.argv[1], sys.argv[2]
    try:
        import tomllib
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        project = config.get("projects", {}).get(project_root, {})
        rules = project.get("ioncache-ai-tools", {}).get("disabled_rules", [])
        print(json.dumps(rules))
    except Exception:
        print("[]")

if __name__ == "__main__":
    main()
```

## Error handling

Both config sources are read defensively: a missing file is a normal, expected case (not an error), a malformed file is logged to stderr and treated as empty, and the Python helper itself never raises, matching the plan's standing "a hook must never throw uncaught or exit non-zero" constraint, this feature adds two more ways to read something at hook-startup time, so it inherits that constraint fully.

The Codex lookup is an exact string match between `process.cwd()` and the `[projects."<path>"]` key a user typed. A trailing slash, an unresolved symlink, or any other mismatch fails silently, the rule stays enabled, with no warning. This is deliberate, not an oversight: it mirrors Codex's own existing project-matching convention (the same exact-path keys already used for `trust_level`), rather than this plugin inventing its own, more forgiving normalization that Codex itself doesn't apply.

## Testing

Extend `rule-engine.self-check.js`:
- `getDisabledRuleIds` reads a fixture `.claude/ioncache-ai-tools.local.json` under a temp project root and returns the right set.
- `getDisabledRuleIds` reads a fixture Codex `config.toml` (via the `codexConfigPath` override) with a matching `[projects."<path>".ioncache-ai-tools]` section and returns the right set, exercising the real Python helper via `spawnSync`, not a mock.
- A project root matching neither source returns an empty set.
- A malformed `.claude/ioncache-ai-tools.local.json` degrades to empty for that source rather than throwing.
- `loadRulesForEvent` with a non-empty `disabledRuleIds` correctly excludes the matching rule and keeps every other rule for that event.

## Success criteria

- Disabling `never-kill-without-asking` via either config source (tested independently) actually stops that rule from firing, verified with the same manual-payload smoke-test technique used for the original 5 rules.
- Enabling it via both sources at once still disables it exactly once (union, not error).
- No config present anywhere reproduces today's behavior exactly: every rule runs.
