# Generic Rule Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one generic, config-driven hook engine in `ioncache-ai-tools` that can enforce three rule shapes (always-on reminder, pattern match, scripted check), and pilot it with 5 real rules ported from the user's memory store.

**Architecture:** A single Node script, `hooks/scripts/rule-engine.js`, invoked once per lifecycle event (`PreToolUse`, `UserPromptSubmit`) via `hooks/hooks.json`. It loads every rule file under `hooks/rules/` whose `event` matches the invocation, runs each rule's cheap synchronous matcher, then resolves the matched rules' actions concurrently via `Promise.all`, merges the results per event type, and emits one JSON payload (or nothing).

**Tech Stack:** Plain Node.js (no dependencies, no test framework). Rules are either declarative `.json` files or scripted `.js` modules under `hooks/rules/`.

**Spec:** `docs/superpowers/specs/2026-09-04-generic-rule-engine-design.md`

## Global Constraints

- Commits are scoped strictly to the isolated `generic-rule-engine` branch, in the `.worktrees/generic-rule-engine` worktree. Each task ends with a commit there, per the standard subagent-driven-development flow, since the review-package tooling diffs BASE..HEAD commits. `main` is never touched and nothing is ever pushed, per the user's explicit confirmation.
- No new npm dependencies. Node builtins only (`fs`, `path`, `os`, `assert`).
- All new code is JavaScript/Node, never Python, per the user's stated scripting-language preference.
- A hook must never exit non-zero or throw uncaught. `UserPromptSubmit` in particular: a non-zero exit blocks and erases the user's typed prompt.
- `fix_emdash_tool_input.py`'s `updatedInput` contract must be matched exactly: a full copy of `tool_input` with only the target field(s) changed, never a partial patch (Claude Code replaces `tool_input` wholesale).
- Only one rewrite-producing rule exists in this pilot (`fix-emdash`). Multi-rewrite composition is explicitly out of scope (see spec's "Known limitation").

---

### Task 1: Rule engine core (matching, merging, rule loading)

**Files:**
- Create: `hooks/scripts/rule-engine.js`
- Create: `hooks/scripts/rule-engine.self-check.js`

**Interfaces:**
- Produces (used by every later task): `matchRule(rule, hookInput) -> boolean`, `resolveAction(rule, hookInput) -> Promise<{action, message?, updatedInput?, systemMessage?}|null>`, `mergePreToolUse(results) -> object|null`, `mergeUserPromptSubmit(results) -> object|null`, `runRules(rules, event, hookInput) -> Promise<object|null>`, `loadRulesForEvent(rulesDir, event) -> Array<object>`. All exported via `module.exports`.

This task builds and proves the engine's logic in isolation, no real rule files or `hooks.json` wiring yet, that's Task 2 onward.

- [ ] **Step 1: Write `hooks/scripts/rule-engine.js`**

```javascript
#!/usr/bin/env node
// Generic hook rule engine. See
// docs/superpowers/specs/2026-09-04-generic-rule-engine-design.md

const fs = require('fs')
const path = require('path')

function getField(obj, dotPath) {
  return dotPath.split('.').reduce((value, key) => (value == null ? undefined : value[key]), obj)
}

function toolNameMatches(rule, hookInput) {
  if (!rule.toolNames) return true
  return rule.toolNames.includes(hookInput.tool_name)
}

function matchRule(rule, hookInput) {
  if (!toolNameMatches(rule, hookInput)) return false
  if (typeof rule.matches === 'function') return rule.matches(hookInput)
  const matcher = rule.matcher || {}
  if (matcher.type === 'always') return true
  if (matcher.type === 'regex') {
    const value = getField(hookInput, matcher.field)
    if (typeof value !== 'string') return false
    return new RegExp(matcher.pattern).test(value)
  }
  return false
}

async function resolveAction(rule, hookInput) {
  if (typeof rule.check === 'function') return rule.check(hookInput)
  if (rule.action === 'deny') return { action: 'deny', message: rule.message }
  if (rule.action === 'inject') return { action: 'inject', message: rule.message }
  return null
}

function mergePreToolUse(results) {
  const deny = results.find((r) => r && r.action === 'deny')
  if (deny) {
    return {
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: deny.message
      }
    }
  }
  const rewrite = results.find((r) => r && r.action === 'rewrite')
  if (rewrite) {
    return {
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'allow',
        updatedInput: rewrite.updatedInput
      },
      systemMessage: rewrite.systemMessage
    }
  }
  return null
}

function mergeUserPromptSubmit(results) {
  const messages = results.filter((r) => r && r.action === 'inject').map((r) => r.message)
  if (messages.length === 0) return null
  return { additionalContext: messages.join('\n\n') }
}

async function runRules(rules, event, hookInput) {
  const matched = rules.filter((rule) => {
    try {
      return matchRule(rule, hookInput)
    } catch (err) {
      console.error(`rule-engine: matcher threw for rule "${rule.name || 'unknown'}": ${err.message}`)
      return false
    }
  })

  const results = await Promise.all(
    matched.map(async (rule) => {
      try {
        return await resolveAction(rule, hookInput)
      } catch (err) {
        console.error(`rule-engine: check threw for rule "${rule.name || 'unknown'}": ${err.message}`)
        return null
      }
    })
  )

  if (event === 'PreToolUse') return mergePreToolUse(results)
  if (event === 'UserPromptSubmit') return mergeUserPromptSubmit(results)
  return null
}

function loadRulesForEvent(rulesDir, event) {
  if (!fs.existsSync(rulesDir)) return []
  return fs
    .readdirSync(rulesDir)
    .filter((name) => name.endsWith('.json') || name.endsWith('.js'))
    .map((name) => {
      const fullPath = path.join(rulesDir, name)
      const rule = name.endsWith('.json') ? JSON.parse(fs.readFileSync(fullPath, 'utf8')) : require(fullPath)
      return { ...rule, name }
    })
    .filter((rule) => rule.event === event)
}

function main() {
  const event = process.argv[2]
  let hookInput
  try {
    hookInput = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (err) {
    process.exit(0)
  }

  const rulesDir = path.join(__dirname, '..', 'rules')
  const rules = loadRulesForEvent(rulesDir, event)

  runRules(rules, event, hookInput)
    .then((output) => {
      if (output) console.log(JSON.stringify(output))
      process.exit(0)
    })
    .catch(() => process.exit(0))
}

module.exports = {
  matchRule,
  resolveAction,
  mergePreToolUse,
  mergeUserPromptSubmit,
  runRules,
  loadRulesForEvent
}

if (require.main === module) main()
```

- [ ] **Step 2: Write `hooks/scripts/rule-engine.self-check.js`**

```javascript
#!/usr/bin/env node
const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const {
  matchRule,
  resolveAction,
  mergePreToolUse,
  mergeUserPromptSubmit,
  runRules,
  loadRulesForEvent
} = require('./rule-engine.js')

async function main() {
  // matchRule: always
  assert.strictEqual(matchRule({ matcher: { type: 'always' } }, {}), true, 'always matcher should always match')

  // matchRule: regex + toolNames restriction
  const regexRule = {
    toolNames: ['Bash'],
    matcher: { type: 'regex', field: 'tool_input.command', pattern: '\\bkill\\b' }
  }
  assert.strictEqual(
    matchRule(regexRule, { tool_name: 'Bash', tool_input: { command: 'kill -9 123' } }),
    true,
    'regex matcher should match when pattern is present'
  )
  assert.strictEqual(
    matchRule(regexRule, { tool_name: 'Bash', tool_input: { command: 'ls' } }),
    false,
    'regex matcher should not match unrelated command'
  )
  assert.strictEqual(
    matchRule(regexRule, { tool_name: 'Read', tool_input: { command: 'kill' } }),
    false,
    'toolNames restriction should exclude other tools'
  )

  // resolveAction: declarative deny/inject
  assert.deepStrictEqual(await resolveAction({ action: 'deny', message: 'no' }, {}), { action: 'deny', message: 'no' })
  assert.deepStrictEqual(await resolveAction({ action: 'inject', message: 'hi' }, {}), { action: 'inject', message: 'hi' })

  // resolveAction: scripted rule
  const scriptedRule = { check: async () => ({ action: 'rewrite', updatedInput: { command: 'fixed' } }) }
  assert.deepStrictEqual(await resolveAction(scriptedRule, {}), {
    action: 'rewrite',
    updatedInput: { command: 'fixed' }
  })

  // mergePreToolUse: deny wins over rewrite
  const denyWins = mergePreToolUse([
    { action: 'rewrite', updatedInput: { command: 'fixed' } },
    { action: 'deny', message: 'blocked' }
  ])
  assert.strictEqual(denyWins.hookSpecificOutput.permissionDecision, 'deny')
  assert.strictEqual(denyWins.hookSpecificOutput.permissionDecisionReason, 'blocked')

  // mergePreToolUse: rewrite only
  const rewriteOnly = mergePreToolUse([{ action: 'rewrite', updatedInput: { command: 'fixed' }, systemMessage: 'msg' }])
  assert.strictEqual(rewriteOnly.hookSpecificOutput.permissionDecision, 'allow')
  assert.deepStrictEqual(rewriteOnly.hookSpecificOutput.updatedInput, { command: 'fixed' })
  assert.strictEqual(rewriteOnly.systemMessage, 'msg')

  // mergePreToolUse: nothing matched
  assert.strictEqual(mergePreToolUse([]), null)

  // mergeUserPromptSubmit: concatenation
  const injected = mergeUserPromptSubmit([
    { action: 'inject', message: 'first' },
    { action: 'inject', message: 'second' }
  ])
  assert.strictEqual(injected.additionalContext, 'first\n\nsecond')

  // mergeUserPromptSubmit: nothing matched
  assert.strictEqual(mergeUserPromptSubmit([]), null)

  // runRules: a throwing rule does not break other rules
  const rulesWithFailure = [
    {
      event: 'PreToolUse',
      matcher: { type: 'always' },
      check: async () => {
        throw new Error('boom')
      }
    },
    { event: 'PreToolUse', matcher: { type: 'always' }, action: 'deny', message: 'caught the good one' }
  ]
  const runResult = await runRules(rulesWithFailure, 'PreToolUse', { tool_name: 'Bash', tool_input: {} })
  assert.strictEqual(runResult.hookSpecificOutput.permissionDecisionReason, 'caught the good one')

  // loadRulesForEvent: reads json + js rules, filters by event
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-test-'))
  fs.writeFileSync(
    path.join(tmpDir, 'a.json'),
    JSON.stringify({ event: 'PreToolUse', matcher: { type: 'always' }, action: 'deny', message: 'a' })
  )
  fs.writeFileSync(
    path.join(tmpDir, 'b.json'),
    JSON.stringify({ event: 'UserPromptSubmit', matcher: { type: 'always' }, action: 'inject', message: 'b' })
  )
  fs.writeFileSync(
    path.join(tmpDir, 'c.js'),
    "module.exports = { event: 'PreToolUse', matches: () => true, check: async () => null }"
  )
  const preToolUseRules = loadRulesForEvent(tmpDir, 'PreToolUse')
  assert.strictEqual(preToolUseRules.length, 2, 'should load both PreToolUse rules (json + js)')
  const userPromptRules = loadRulesForEvent(tmpDir, 'UserPromptSubmit')
  assert.strictEqual(userPromptRules.length, 1, 'should load only the UserPromptSubmit rule')
  fs.rmSync(tmpDir, { recursive: true, force: true })

  // loadRulesForEvent: missing directory returns empty array, never throws
  assert.deepStrictEqual(loadRulesForEvent(path.join(tmpDir, 'does-not-exist'), 'PreToolUse'), [])

  console.log('All rule-engine self-checks passed.')
}

main()
```

- [ ] **Step 3: Run the self-check and verify it passes**

Run: `node hooks/scripts/rule-engine.self-check.js`
Expected: prints `All rule-engine self-checks passed.` and exits 0. Any `AssertionError` means a bug in Step 1's implementation, fix and rerun before moving on.

---

### Task 2: First two pattern rules, wire `PreToolUse` into `hooks.json`

**Files:**
- Create: `hooks/rules/never-kill-without-asking.json`
- Create: `hooks/rules/no-manual-lockfile-edit.json`
- Modify: `hooks/hooks.json`
- Modify: `hooks/scripts/rule-engine.self-check.js` (append real-rule-loading assertions)

**Interfaces:**
- Consumes: `loadRulesForEvent(rulesDir, event)` from Task 1, unchanged.

- [ ] **Step 1: Create `hooks/rules/never-kill-without-asking.json`**

```json
{
  "event": "PreToolUse",
  "toolNames": ["Bash"],
  "matcher": {
    "type": "regex",
    "field": "tool_input.command",
    "pattern": "(^|[\\s;&|(`])(?:[\\w./-]*/)?(kill|pkill|killall)($|[\\s;&|)`])"
  },
  "action": "deny",
  "message": "Never run kill/pkill/killall without asking the user first, even for your own leftover process. Ask, then wait for an explicit yes."
}
```

- [ ] **Step 2: Create `hooks/rules/no-manual-lockfile-edit.json`**

```json
{
  "event": "PreToolUse",
  "toolNames": ["Edit", "Write", "MultiEdit"],
  "matcher": {
    "type": "regex",
    "field": "tool_input.file_path",
    "pattern": "(package-lock\\.json|yarn\\.lock|pnpm-lock\\.yaml)$"
  },
  "action": "deny",
  "message": "Never hand-edit a lockfile. Resolve the conflict in package.json first, then regenerate the lockfile by running the package manager's install command."
}
```

- [ ] **Step 3: Append real-rule-loading assertions to `rule-engine.self-check.js`**

Add before the final `console.log` line:

```javascript
  // Real pilot rules load correctly for PreToolUse
  const rulesDir = path.join(__dirname, '..', 'rules')
  const realPreToolUseRules = loadRulesForEvent(rulesDir, 'PreToolUse').map((r) => r.name)
  assert.ok(
    realPreToolUseRules.includes('never-kill-without-asking.json'),
    'never-kill-without-asking.json should load for PreToolUse'
  )
  assert.ok(
    realPreToolUseRules.includes('no-manual-lockfile-edit.json'),
    'no-manual-lockfile-edit.json should load for PreToolUse'
  )
```

- [ ] **Step 4: Run the self-check and verify it still passes**

Run: `node hooks/scripts/rule-engine.self-check.js`
Expected: `All rule-engine self-checks passed.`

- [ ] **Step 5: Add the `PreToolUse` entry to `hooks/hooks.json`**

Add this object to the end of the `PreToolUse` array (after the existing `fix_emdash_tool_input.py` entry, before the array's closing `]`):

```json
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/rule-engine.js\" PreToolUse"
          }
        ]
      }
```

- [ ] **Step 6: Verify `hooks.json` is still valid JSON**

Run: `node -e "JSON.parse(require('fs').readFileSync('hooks/hooks.json','utf8')); console.log('OK')"`
Expected: `OK`

- [ ] **Step 7: Manual end-to-end smoke test against the real engine + real rules**

Run each of these three commands from the repo root:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"kill -9 12345"}}' | node hooks/scripts/rule-engine.js PreToolUse
```
Expected: JSON with `"permissionDecision":"deny"` and the kill-rule's message.

```bash
echo '{"tool_name":"Edit","tool_input":{"file_path":"package-lock.json","old_string":"a","new_string":"b"}}' | node hooks/scripts/rule-engine.js PreToolUse
```
Expected: JSON with `"permissionDecision":"deny"` and the lockfile-rule's message.

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' | node hooks/scripts/rule-engine.js PreToolUse
```
Expected: no output, exit code 0.

---

### Task 3: Scripted rule, port `fix_emdash_tool_input.py` into the engine

**Files:**
- Create: `hooks/rules/fix-emdash.js`
- Delete: `hooks/scripts/fix_emdash_tool_input.py`
- Modify: `hooks/hooks.json` (remove the now-superseded entry)
- Modify: `hooks/scripts/rule-engine.self-check.js` (append transform assertions)

**Interfaces:**
- Consumes: the scripted-rule shape from Task 1 (`event`, `toolNames`, `matches(input)`, `async check(input)`).
- Produces: `fix-emdash.js` exports the same shape, importable by the self-check for direct assertions.

- [ ] **Step 1: Write `hooks/rules/fix-emdash.js`**

```javascript
// Ports fix_emdash_tool_input.py: silently rewrites em-dashes in Bash /
// Write / Edit / MultiEdit tool input before the tool runs. Builds the
// target character from its code point, never a literal, so this file
// itself is never mangled by the very rule it implements.

const EM_DASH = String.fromCharCode(0x2014)
const EM_DASH_PATTERN = new RegExp('\\s*' + EM_DASH + '\\s*', 'g')
const REPLACEMENT = ', '

function fix(text) {
  return text.replace(EM_DASH_PATTERN, REPLACEMENT)
}

function containsEmDash(text) {
  return typeof text === 'string' && text.includes(EM_DASH)
}

module.exports = {
  event: 'PreToolUse',
  toolNames: ['Bash', 'Write', 'Edit', 'MultiEdit'],
  matches(input) {
    const toolInput = input.tool_input || {}
    if (input.tool_name === 'Bash') return containsEmDash(toolInput.command)
    if (input.tool_name === 'Write') return containsEmDash(toolInput.content)
    if (input.tool_name === 'Edit') return containsEmDash(toolInput.new_string)
    if (input.tool_name === 'MultiEdit') return (toolInput.edits || []).some((edit) => containsEmDash(edit.new_string))
    return false
  },
  async check(input) {
    const toolInput = { ...(input.tool_input || {}) }
    if (input.tool_name === 'Bash') {
      toolInput.command = fix(toolInput.command)
    } else if (input.tool_name === 'Write') {
      toolInput.content = fix(toolInput.content)
    } else if (input.tool_name === 'Edit') {
      toolInput.new_string = fix(toolInput.new_string)
    } else if (input.tool_name === 'MultiEdit') {
      toolInput.edits = (toolInput.edits || []).map((edit) =>
        containsEmDash(edit.new_string) ? { ...edit, new_string: fix(edit.new_string) } : edit
      )
    }
    return {
      action: 'rewrite',
      updatedInput: toolInput,
      systemMessage: 'Auto-fixed em-dash(es) in tool input before execution.'
    }
  }
}
```

- [ ] **Step 2: Append transform assertions to `rule-engine.self-check.js`**

Add before the final `console.log` line (import at the top alongside the other `require`s: `const fixEmdash = require('../rules/fix-emdash.js')`):

```javascript
  // fix-emdash: matches per tool type
  const emDash = String.fromCharCode(0x2014)
  assert.strictEqual(
    fixEmdash.matches({ tool_name: 'Bash', tool_input: { command: `a${emDash}b` } }),
    true,
    'fix-emdash should match a Bash command containing an em-dash'
  )
  assert.strictEqual(
    fixEmdash.matches({ tool_name: 'Bash', tool_input: { command: 'a-b' } }),
    false,
    'fix-emdash should not match a plain hyphen'
  )

  // fix-emdash: check rewrites Bash command, preserves other fields
  const bashResult = await fixEmdash.check({
    tool_name: 'Bash',
    tool_input: { command: `one${emDash}two`, description: 'keep me' }
  })
  assert.strictEqual(bashResult.updatedInput.command, 'one, two')
  assert.strictEqual(bashResult.updatedInput.description, 'keep me')

  // fix-emdash: check rewrites MultiEdit edits array, leaves unaffected edits untouched
  const multiEditResult = await fixEmdash.check({
    tool_name: 'MultiEdit',
    tool_input: {
      file_path: 'f.js',
      edits: [
        { old_string: 'x', new_string: `a${emDash}b` },
        { old_string: 'y', new_string: 'unchanged' }
      ]
    }
  })
  assert.strictEqual(multiEditResult.updatedInput.edits[0].new_string, 'a, b')
  assert.strictEqual(multiEditResult.updatedInput.edits[1].new_string, 'unchanged')
```

- [ ] **Step 3: Run the self-check and verify it passes**

Run: `node hooks/scripts/rule-engine.self-check.js`
Expected: `All rule-engine self-checks passed.`

- [ ] **Step 4: Remove the superseded entry from `hooks/hooks.json`**

Delete this whole object from the `PreToolUse` array:

```json
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/fix_emdash_tool_input.py\""
          }
        ]
      }
```

- [ ] **Step 5: Delete `hooks/scripts/fix_emdash_tool_input.py`**

Run: `rm hooks/scripts/fix_emdash_tool_input.py`

- [ ] **Step 6: Verify `hooks.json` is still valid JSON**

Run: `node -e "JSON.parse(require('fs').readFileSync('hooks/hooks.json','utf8')); console.log('OK')"`
Expected: `OK`

- [ ] **Step 7: Manual smoke test against the real engine**

```bash
node -e "console.log(JSON.stringify({tool_name:'Bash',tool_input:{command:'one'+String.fromCharCode(0x2014)+'two'}}))" | node hooks/scripts/rule-engine.js PreToolUse
```
Expected: JSON with `"permissionDecision":"allow"`, `"updatedInput":{"command":"one, two"}`, and the auto-fixed `systemMessage`.

---

### Task 4: Two always-on prompt rules, wire `UserPromptSubmit` into `hooks.json`

**Files:**
- Create: `hooks/rules/scope-exactly-what-asked.json`
- Create: `hooks/rules/verify-state-before-claiming.json`
- Modify: `hooks/hooks.json`
- Modify: `hooks/scripts/rule-engine.self-check.js` (append real-rule-loading assertions)

- [ ] **Step 1: Create `hooks/rules/scope-exactly-what-asked.json`**

```json
{
  "event": "UserPromptSubmit",
  "matcher": { "type": "always" },
  "action": "inject",
  "message": "Do exactly what was asked, nothing more. If something else seems worth doing, mention it and stop; don't act on it unless asked."
}
```

- [ ] **Step 2: Create `hooks/rules/verify-state-before-claiming.json`**

```json
{
  "event": "UserPromptSubmit",
  "matcher": { "type": "always" },
  "action": "inject",
  "message": "Never state the current status of anything (a PR, CI, a file, a branch) from memory or an earlier turn. Check it again in this turn before claiming it."
}
```

- [ ] **Step 3: Append real-rule-loading assertions to `rule-engine.self-check.js`**

Add before the final `console.log` line:

```javascript
  // Real pilot rules load correctly for UserPromptSubmit
  const realUserPromptRules = loadRulesForEvent(rulesDir, 'UserPromptSubmit').map((r) => r.name)
  assert.ok(
    realUserPromptRules.includes('scope-exactly-what-asked.json'),
    'scope-exactly-what-asked.json should load for UserPromptSubmit'
  )
  assert.ok(
    realUserPromptRules.includes('verify-state-before-claiming.json'),
    'verify-state-before-claiming.json should load for UserPromptSubmit'
  )
```

- [ ] **Step 4: Run the self-check and verify it still passes**

Run: `node hooks/scripts/rule-engine.self-check.js`
Expected: `All rule-engine self-checks passed.`

- [ ] **Step 5: Add the `UserPromptSubmit` entry to `hooks/hooks.json`**

Add this object to the end of the `UserPromptSubmit` array:

```json
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/rule-engine.js\" UserPromptSubmit"
          }
        ]
      }
```

- [ ] **Step 6: Verify `hooks.json` is still valid JSON**

Run: `node -e "JSON.parse(require('fs').readFileSync('hooks/hooks.json','utf8')); console.log('OK')"`
Expected: `OK`

- [ ] **Step 7: Manual end-to-end smoke test**

```bash
echo '{"prompt":"hello"}' | node hooks/scripts/rule-engine.js UserPromptSubmit
```
Expected: JSON with one `additionalContext` string containing both rules' messages, separated by a blank line.

---

### Task 5: Documentation and final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Hooks table in `README.md`**

Remove this row:

```
| `fix_emdash_tool_input.py` | PreToolUse | Silently rewrites em-dashes in tool input |
```

Add these rows in its place:

```
| `rule-engine.js PreToolUse` | PreToolUse | Runs every `hooks/rules/*` rule registered for this event (deny or rewrite) |
| `rule-engine.js UserPromptSubmit` | UserPromptSubmit | Runs every `hooks/rules/*` rule registered for this event (injects reminders) |
```

- [ ] **Step 2: Add a `hooks/rules/` section to `README.md`**

Add this new section directly after the existing `### \`.worktree-setup.json\`` section (before `## Skills`):

```markdown
### `hooks/rules/`

One file per rule, loaded by `rule-engine.js`. Adding a rule never touches
engine code. Three shapes:

- **Always-on** (`.json`, `matcher: {"type": "always"}`): injects a fixed
  reminder into `additionalContext` on every `UserPromptSubmit`.
- **Pattern** (`.json`, `matcher: {"type": "regex", "field": "...", "pattern": "..."}`):
  denies a `PreToolUse` call when a field of the tool input matches.
- **Scripted** (`.js`, exports `{event, toolNames, matches(input), async check(input)}`):
  the escape hatch for anything a regex can't express, including rewriting
  tool input in place (see `fix-emdash.js`).

Full design: `docs/superpowers/specs/2026-09-04-generic-rule-engine-design.md`.
```

- [ ] **Step 3: Final full verification**

Run: `node hooks/scripts/rule-engine.self-check.js`
Expected: `All rule-engine self-checks passed.`

Run: `node -e "JSON.parse(require('fs').readFileSync('hooks/hooks.json','utf8')); console.log('OK')"`
Expected: `OK`

Confirm `hooks/scripts/fix_emdash_tool_input.py` no longer exists:
Run: `ls hooks/scripts/fix_emdash_tool_input.py`
Expected: `No such file or directory`

Commit the README changes on the `generic-rule-engine` branch, then report completion.
