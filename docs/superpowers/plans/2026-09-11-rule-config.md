# Per-Rule Disable Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user disable individual rule-engine rules per project, configured through each tool's own native settings surface (Claude Code's plugin-settings file, Codex's `config.toml`), with no env var and no new repo file.

**Architecture:** `rule-engine.js` gains a `getDisabledRuleIds(projectRoot, options)` function that reads two optional, independent sources (a Claude Code JSON file, a Codex TOML section read via a small Python helper) and unions whatever it finds. `loadRulesForEvent` gains a third parameter to filter out any rule whose id is in that set.

**Tech Stack:** Plain Node.js for the engine (unchanged). Plain Python 3.11+ (`tomllib`, standard library, no dependency) for the Codex-side reader, since Node has no built-in TOML parser.

**Spec:** `docs/superpowers/specs/2026-09-11-rule-config-design.md`

## Global Constraints

- No new npm or pip dependencies.
- No environment variable anywhere in this feature, not for config, not for platform detection. The engine checks whether each config source's file exists and reads whichever do; nothing branches on "which tool is this."
- `process.cwd()` is the project-root lookup key for both config sources (matching the existing convention `hooks/scripts/graphify_context.js` already uses in this repo), not `$CLAUDE_PROJECT_DIR`.
- A rule's id for config purposes is its filename minus extension (`never-kill-without-asking`, not `never-kill-without-asking.json`).
- Neither config source may ever cause `rule-engine.js` to throw or exit non-zero. A missing file is normal; a malformed file logs to stderr and is treated as empty.
- The Codex config's project-path matching is an exact string match against `process.cwd()`, deliberately not normalized (mirrors Codex's own existing project-key convention), and must not be tested against the real `~/.codex/config.toml` on the machine running the self-check, tests use the `codexConfigPath` override.

---

### Task 1: Codex config reader (`read_codex_disabled_rules.py`)

**Files:**
- Create: `hooks/scripts/read_codex_disabled_rules.py`

**Interfaces:**
- Produces: a CLI script taking two positional arguments, `<config_path> <project_root>`, printing a JSON array to stdout. Always prints valid JSON (an array, possibly empty) and always exits 0, regardless of what goes wrong. Consumed by Task 2's `getDisabledRuleIds` via `spawnSync('python3', [helperPath, codexConfigPath, projectRoot], ...)`.

This task is fully testable standalone, no dependency on Task 2's JS changes.

- [ ] **Step 1: Write `hooks/scripts/read_codex_disabled_rules.py`**

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

- [ ] **Step 2: Manually verify all four cases against fixture files**

Create a scratch fixture (use any path outside the repo, e.g. under a temp directory) named `config.toml` with this content:

```toml
[projects."/tmp/my-project"]
trust_level = "trusted"

[projects."/tmp/my-project".ioncache-ai-tools]
disabled_rules = ["test-rule-a"]
```

Run each of these four commands and confirm the exact output shown:

```bash
python3 hooks/scripts/read_codex_disabled_rules.py /path/to/fixture/config.toml /tmp/my-project
```
Expected: `["test-rule-a"]`

```bash
python3 hooks/scripts/read_codex_disabled_rules.py /path/to/fixture/config.toml /tmp/other-project
```
Expected: `[]`

```bash
python3 hooks/scripts/read_codex_disabled_rules.py /path/to/fixture/does-not-exist.toml /tmp/my-project
```
Expected: `[]`

```bash
python3 hooks/scripts/read_codex_disabled_rules.py only-one-arg
```
Expected: `[]`

If a real rule id needs to appear in a fixture or a shell command anywhere in this task, avoid the literal string `never-kill-without-asking`, this repo's own `never-kill-without-asking` rule denies `kill`/`pkill`/`killall` as a bounded word and does not fire on that hyphenated compound, but other rule ids or unrelated fixture content are safer to use for scratch testing regardless. Use a placeholder id like `test-rule-a` for fixtures, as shown above.

---

### Task 2: Wire disabled-rule filtering into the engine

**Files:**
- Modify: `hooks/scripts/rule-engine.js`
- Modify: `hooks/scripts/rule-engine.self-check.js`

**Interfaces:**
- Consumes: Task 1's `hooks/scripts/read_codex_disabled_rules.py`, invoked exactly as `spawnSync('python3', [helperPath, codexConfigPath, projectRoot], { encoding: 'utf8' })`.
- Produces: `getDisabledRuleIds(projectRoot, { codexConfigPath } = {}) -> Set<string>`, exported via `module.exports`. `loadRulesForEvent(rulesDir, event, disabledRuleIds = new Set())`, the existing function with one new optional parameter, backward compatible with every existing call site in the self-check.

- [ ] **Step 1: Add the new imports to `hooks/scripts/rule-engine.js`**

At the top of the file, alongside the existing `const fs = require('fs')` and `const path = require('path')`:

```javascript
const os = require('os')
const { spawnSync } = require('child_process')
```

- [ ] **Step 2: Add `getDisabledRuleIds` to `hooks/scripts/rule-engine.js`**

Add this function after `loadRuleFile` and before `loadRulesForEvent`:

```javascript
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

- [ ] **Step 3: Add the filter to `loadRulesForEvent`**

Change the function signature and add one more `.filter(...)` call. The full function becomes:

```javascript
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

- [ ] **Step 4: Wire it into `runHook`**

The current `runHook` reads:

```javascript
async function runHook(overrideRulesDir) {
  const event = process.argv[2]
  let hookInput
  try {
    hookInput = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (err) {
    return
  }

  const rulesDir = overrideRulesDir || path.join(__dirname, '..', 'rules')
  let rules
  try {
    rules = loadRulesForEvent(rulesDir, event)
  } catch (err) {
    console.error(`rule-engine: failed to load rules from ${rulesDir}: ${err.message}`)
    rules = []
  }

  return await runRules(rules, event, hookInput)
}
```

Change it to compute and pass `disabledRuleIds`:

```javascript
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

- [ ] **Step 5: Add `getDisabledRuleIds` to `module.exports`**

The current export block:

```javascript
module.exports = {
  matchRule,
  resolveAction,
  mergePreToolUse,
  mergeUserPromptSubmit,
  runRules,
  loadRulesForEvent,
  runHook
}
```

Add `getDisabledRuleIds` to it:

```javascript
module.exports = {
  matchRule,
  resolveAction,
  mergePreToolUse,
  mergeUserPromptSubmit,
  runRules,
  loadRulesForEvent,
  runHook,
  getDisabledRuleIds
}
```

- [ ] **Step 6: Add `getDisabledRuleIds` to the self-check's imports**

In `hooks/scripts/rule-engine.self-check.js`, the current import block:

```javascript
const {
  matchRule,
  resolveAction,
  mergePreToolUse,
  mergeUserPromptSubmit,
  runRules,
  loadRulesForEvent
} = require('./rule-engine.js')
```

Add `getDisabledRuleIds`:

```javascript
const {
  matchRule,
  resolveAction,
  mergePreToolUse,
  mergeUserPromptSubmit,
  runRules,
  loadRulesForEvent,
  getDisabledRuleIds
} = require('./rule-engine.js')
```

- [ ] **Step 7: Append the new test assertions**

Add this block to `hooks/scripts/rule-engine.self-check.js`, immediately before the final `console.log('All rule-engine self-checks passed.')` line:

```javascript
  // getDisabledRuleIds: reads disabledRules from a Claude Code local settings file
  const claudeProjectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-claude-config-'))
  fs.mkdirSync(path.join(claudeProjectRoot, '.claude'))
  fs.writeFileSync(
    path.join(claudeProjectRoot, '.claude', 'ioncache-ai-tools.local.json'),
    JSON.stringify({ disabledRules: ['test-rule-a'] })
  )
  const claudeDisabled = getDisabledRuleIds(claudeProjectRoot, { codexConfigPath: '/does/not/exist.toml' })
  assert.deepStrictEqual(
    [...claudeDisabled],
    ['test-rule-a'],
    'should read disabledRules from the Claude Code local settings file'
  )
  fs.rmSync(claudeProjectRoot, { recursive: true, force: true })

  // getDisabledRuleIds: a malformed Claude Code settings file degrades to empty, never throws
  const malformedProjectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-malformed-config-'))
  fs.mkdirSync(path.join(malformedProjectRoot, '.claude'))
  fs.writeFileSync(path.join(malformedProjectRoot, '.claude', 'ioncache-ai-tools.local.json'), '{not valid json')
  const malformedDisabled = getDisabledRuleIds(malformedProjectRoot, { codexConfigPath: '/does/not/exist.toml' })
  assert.deepStrictEqual(
    [...malformedDisabled],
    [],
    'a malformed settings file should degrade to no disabled rules, not throw'
  )
  fs.rmSync(malformedProjectRoot, { recursive: true, force: true })

  // getDisabledRuleIds: reads disabled_rules from a Codex config.toml project section, via the real Python helper
  const codexProjectRoot = '/tmp/rule-engine-codex-test-project'
  const codexConfigDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-codex-config-'))
  const codexConfigPath = path.join(codexConfigDir, 'config.toml')
  fs.writeFileSync(
    codexConfigPath,
    `[projects."${codexProjectRoot}"]\ntrust_level = "trusted"\n\n[projects."${codexProjectRoot}".ioncache-ai-tools]\ndisabled_rules = ["test-rule-b"]\n`
  )
  const codexDisabled = getDisabledRuleIds(codexProjectRoot, { codexConfigPath })
  assert.deepStrictEqual(
    [...codexDisabled],
    ['test-rule-b'],
    'should read disabled_rules from the Codex config.toml project section via the Python helper'
  )
  fs.rmSync(codexConfigDir, { recursive: true, force: true })

  // getDisabledRuleIds: both sources present at once union together, not error
  const bothProjectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-both-config-'))
  fs.mkdirSync(path.join(bothProjectRoot, '.claude'))
  fs.writeFileSync(
    path.join(bothProjectRoot, '.claude', 'ioncache-ai-tools.local.json'),
    JSON.stringify({ disabledRules: ['test-rule-a'] })
  )
  const bothCodexConfigDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-both-codex-'))
  const bothCodexConfigPath = path.join(bothCodexConfigDir, 'config.toml')
  fs.writeFileSync(
    bothCodexConfigPath,
    `[projects."${bothProjectRoot}".ioncache-ai-tools]\ndisabled_rules = ["test-rule-b"]\n`
  )
  const bothDisabled = getDisabledRuleIds(bothProjectRoot, { codexConfigPath: bothCodexConfigPath })
  assert.deepStrictEqual(
    [...bothDisabled].sort(),
    ['test-rule-a', 'test-rule-b'],
    'both sources present at once should union together, not overwrite or error'
  )
  fs.rmSync(bothProjectRoot, { recursive: true, force: true })
  fs.rmSync(bothCodexConfigDir, { recursive: true, force: true })

  // getDisabledRuleIds: neither source present returns an empty set
  const emptyProjectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-no-config-'))
  const noConfigDisabled = getDisabledRuleIds(emptyProjectRoot, { codexConfigPath: '/does/not/exist.toml' })
  assert.deepStrictEqual([...noConfigDisabled], [], 'no config anywhere should mean no disabled rules')
  fs.rmSync(emptyProjectRoot, { recursive: true, force: true })

  // loadRulesForEvent: disabledRuleIds excludes the matching rule, keeps others
  const filterRulesDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-filter-'))
  fs.writeFileSync(
    path.join(filterRulesDir, 'rule-one.json'),
    JSON.stringify({ event: 'PreToolUse', matcher: { type: 'always' }, action: 'deny', message: 'one' })
  )
  fs.writeFileSync(
    path.join(filterRulesDir, 'rule-two.json'),
    JSON.stringify({ event: 'PreToolUse', matcher: { type: 'always' }, action: 'deny', message: 'two' })
  )
  const filteredRules = loadRulesForEvent(filterRulesDir, 'PreToolUse', new Set(['rule-one'])).map((r) => r.name)
  assert.deepStrictEqual(filteredRules, ['rule-two.json'], 'a disabled rule id should exclude that rule and keep the other')
  fs.rmSync(filterRulesDir, { recursive: true, force: true })
```

- [ ] **Step 8: Run the self-check and verify it passes**

Run: `node hooks/scripts/rule-engine.self-check.js < /dev/null`
Expected: `All rule-engine self-checks passed.` If Task 1's Python helper has a bug, the Codex-side assertion in this step will fail with a clear diff, since it invokes the real script via `spawnSync`, not a mock.

- [ ] **Step 9: Manually verify the real `never-kill-without-asking` rule against the real engine, with and without a disable config**

This is the one test that exercises the actual shipped rule, not a synthetic fixture, matching the design spec's own success criteria. Run from the repo root.

First, confirm it still denies with no config present:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"pkill firefox"}}' | node hooks/scripts/rule-engine.js PreToolUse
```
Expected: a JSON object with `"permissionDecision":"deny"`.

Now add a temporary disable config, re-run the exact same command, then remove the config immediately after checking the result, in the same terminal session, so nothing is left behind:

```bash
mkdir -p .claude
echo '{"disabledRules": ["never-kill-without-asking"]}' > .claude/ioncache-ai-tools.local.json
echo '{"tool_name":"Bash","tool_input":{"command":"pkill firefox"}}' | node hooks/scripts/rule-engine.js PreToolUse
rm .claude/ioncache-ai-tools.local.json
rmdir .claude 2>/dev/null || true
```
Expected: no output at all from the middle command (the rule is disabled, so nothing matches, nothing denies). Confirm `git status --short` shows no leftover `.claude/` changes afterward, this file must not end up committed.

---

### Task 3: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing new, describes Task 2's shipped behavior.

- [ ] **Step 1: Add a "Disabling a rule" subsection to `README.md`**

Insert this new subsection immediately after the per-rule table and before the `Full design:` line inside the existing `### hooks/rules/` section:

````markdown
### Disabling a rule

Add either config file, whichever CLI you use. No repo file, no environment
variable.

**Claude Code:** `.claude/ioncache-ai-tools.local.json` in the project root
(gitignored, not shipped with the plugin):

```json
{ "disabledRules": ["never-kill-without-asking"] }
```

**Codex:** a project-scoped table in `~/.codex/config.toml`, hand-edited,
there is no CLI command for it:

```toml
[projects."/absolute/path/to/project".ioncache-ai-tools]
disabled_rules = ["never-kill-without-asking"]
```

A rule's id is its filename minus the extension. Both sources are read and
unioned, disabling a rule in either one disables it. Takes effect after the
usual reinstall (see Local development above), this applies to real
installs too, not just local dev.
````

- [ ] **Step 2: Verify the README change**

Run: `grep -c '^```' README.md`
Expected: an even number (every opened code fence is closed). Visually confirm the new subsection renders correctly by reading the file back.

Run:
```bash
grep -n $'\xe2\x80\x94' README.md || echo "no em-dash found"
```
Expected: `no em-dash found`
