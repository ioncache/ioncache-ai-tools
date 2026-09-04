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
