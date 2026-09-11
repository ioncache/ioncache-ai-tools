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
  loadRulesForEvent,
  getDisabledRuleIds
} = require('./rule-engine.js')
const fixEmdash = require('../rules/fix-emdash.js')
const noManualLockfileEditBash = require('../rules/no-manual-lockfile-edit-bash.js')

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

  // matchRule: custom matches() function is invoked and its result respected
  let customMatcherCalled = false
  const customMatchRule = {
    toolNames: ['Bash'],
    matches(input) {
      customMatcherCalled = true
      return input.tool_input.command === 'trigger-me'
    }
  }
  assert.strictEqual(
    matchRule(customMatchRule, { tool_name: 'Bash', tool_input: { command: 'trigger-me' } }),
    true,
    'custom matches() should be invoked and its true result respected'
  )
  assert.strictEqual(customMatcherCalled, true, 'custom matches() should actually be called')
  assert.strictEqual(
    matchRule(customMatchRule, { tool_name: 'Bash', tool_input: { command: 'something-else' } }),
    false,
    'custom matches() false result should be respected'
  )

  // matchRule: custom matches() is still gated by toolNames
  customMatcherCalled = false
  assert.strictEqual(
    matchRule(customMatchRule, { tool_name: 'Read', tool_input: { command: 'trigger-me' } }),
    false,
    'toolNames should exclude the tool before custom matches() runs'
  )
  assert.strictEqual(customMatcherCalled, false, 'custom matches() should not be called when toolNames excludes the tool')

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

  // loadRulesForEvent: a bad rule file is skipped, valid siblings still load
  const badRulesDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rule-engine-bad-'))
  fs.writeFileSync(
    path.join(badRulesDir, 'good.json'),
    JSON.stringify({ event: 'PreToolUse', matcher: { type: 'always' }, action: 'deny', message: 'good' })
  )
  fs.writeFileSync(path.join(badRulesDir, 'bad.json'), '{invalid json')
  fs.writeFileSync(path.join(badRulesDir, 'throw.js'), 'throw new Error("rule load error")')
  let loadError = null
  let badDirRules = []
  try {
    badDirRules = loadRulesForEvent(badRulesDir, 'PreToolUse')
  } catch (err) {
    loadError = err
  }
  assert.strictEqual(loadError, null, 'loadRulesForEvent should not throw on invalid rule files')
  assert.strictEqual(badDirRules.length, 1, 'only the valid rule should load, the bad ones are skipped')
  assert.strictEqual(badDirRules[0].name, 'good.json', 'the valid rule should still be the one that loads')
  fs.rmSync(badRulesDir, { recursive: true, force: true })

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
  assert.ok(
    realPreToolUseRules.includes('no-manual-lockfile-edit-bash.js'),
    'no-manual-lockfile-edit-bash.js should load for PreToolUse'
  )

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

  // Real never-kill-without-asking rule file, matched via matchRule directly
  // (exercises the shipped pattern itself, not a hand-copied one)
  const neverKillRule = JSON.parse(fs.readFileSync(path.join(rulesDir, 'never-kill-without-asking.json'), 'utf8'))
  assert.strictEqual(
    matchRule(neverKillRule, { tool_name: 'Bash', tool_input: { command: 'kill -9 12345' } }),
    true,
    'never-kill-without-asking should match a real kill invocation'
  )
  assert.strictEqual(
    matchRule(neverKillRule, {
      tool_name: 'Bash',
      tool_input: { command: 'cat hooks/rules/never-kill-without-asking.json' }
    }),
    false,
    'never-kill-without-asking should not false-positive on its own filename substring (hyphen-boundary regression)'
  )

  // Real no-manual-lockfile-edit rule file, matched via matchRule directly
  const lockfileRule = JSON.parse(fs.readFileSync(path.join(rulesDir, 'no-manual-lockfile-edit.json'), 'utf8'))
  assert.strictEqual(
    matchRule(lockfileRule, { tool_name: 'Edit', tool_input: { file_path: 'package-lock.json' } }),
    true,
    'no-manual-lockfile-edit should match a real lockfile edit'
  )
  // No hyphen-boundary regression case here: this pattern anchors on a
  // literal filename suffix (`$`), it never uses `\b`, so there's no
  // separator-class boundary for a hyphenated identifier to slip past.

  // no-manual-lockfile-edit-bash: catches Bash mutations the Edit/Write/
  // MultiEdit-only rule above can't see
  const lockfileName = 'package-lock.json'
  assert.strictEqual(
    noManualLockfileEditBash.matches({ tool_name: 'Bash', tool_input: { command: `printf x > ${lockfileName}` } }),
    true,
    'should match a redirection into a lockfile'
  )
  assert.strictEqual(
    noManualLockfileEditBash.matches({ tool_name: 'Bash', tool_input: { command: `sed -i s/a/b/ ${lockfileName}` } }),
    true,
    'should match sed -i targeting a lockfile'
  )
  assert.strictEqual(
    noManualLockfileEditBash.matches({ tool_name: 'Bash', tool_input: { command: `cat ${lockfileName}` } }),
    false,
    'should not match reading a lockfile without a mutation'
  )
  assert.strictEqual(
    noManualLockfileEditBash.matches({ tool_name: 'Bash', tool_input: { command: 'npm install' } }),
    false,
    'should not match an unrelated Bash command'
  )

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

  // fix-emdash: check denies Bash instead of rewriting (an inserted space
  // could split one shell argument into two)
  const bashResult = await fixEmdash.check({
    tool_name: 'Bash',
    tool_input: { command: `one${emDash}two`, description: 'keep me' }
  })
  assert.strictEqual(bashResult.action, 'deny', 'fix-emdash should deny Bash rather than rewrite it')
  assert.ok(typeof bashResult.message === 'string' && bashResult.message.length > 0, 'deny should include a message')

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

  console.log('All rule-engine self-checks passed.')
}

main()
