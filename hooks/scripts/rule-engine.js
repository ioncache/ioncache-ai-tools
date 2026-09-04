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

function main() {
  runHook()
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
  loadRulesForEvent,
  runHook
}

if (require.main === module) main()
