#!/usr/bin/env node
// Generic hook rule engine. See
// docs/superpowers/specs/2026-09-04-generic-rule-engine-design.md

const fs = require('fs')
const path = require('path')
const os = require('os')
const { spawnSync } = require('child_process')

function getField(obj, dotPath) {
  return dotPath
    .split('.')
    .reduce((value, key) => (value === null || value === undefined ? undefined : value[key]), obj)
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
  const rewrites = results.filter((r) => r && r.action === 'rewrite')
  if (rewrites.length > 1) {
    console.error(
      `rule-engine: ${rewrites.length} rules returned a rewrite for the same event; only the first is applied, the rest are silently dropped (see spec's known limitation)`
    )
  }
  const rewrite = rewrites[0]
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

function loadRuleFile(rulesDir, name) {
  try {
    const fullPath = path.join(rulesDir, name)
    const rule = name.endsWith('.json') ? JSON.parse(fs.readFileSync(fullPath, 'utf8')) : require(fullPath)
    return { ...rule, name }
  } catch (err) {
    console.error(`rule-engine: skipping rule file "${name}": ${err.message}`)
    return null
  }
}

const DEFAULT_CODEX_HOME = path.join(os.homedir(), '.codex')

function getDisabledRuleIds(
  projectRoot,
  { codexConfigPath = path.join(process.env.CODEX_HOME || DEFAULT_CODEX_HOME, 'config.toml') } = {}
) {
  const disabled = new Set()

  const claudeConfigPath = path.join(projectRoot, '.claude', 'ioncache-ai-tools.local.json')
  if (fs.existsSync(claudeConfigPath)) {
    try {
      const config = JSON.parse(fs.readFileSync(claudeConfigPath, 'utf8'))
      const disabledRules = Array.isArray(config.disabledRules) ? config.disabledRules : []
      for (const id of disabledRules) disabled.add(id)
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

function loadRulesForEvent(rulesDir, event, disabledRuleIds = new Set()) {
  if (!fs.existsSync(rulesDir)) return []
  return fs
    .readdirSync(rulesDir)
    .filter((name) => name.endsWith('.json') || name.endsWith('.js'))
    .map((name) => loadRuleFile(rulesDir, name))
    .filter((rule) => rule !== null && rule.event === event)
    .filter((rule) => !disabledRuleIds.has(path.basename(rule.name, path.extname(rule.name))))
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

const HANG_TIMEOUT_MS = 5000

function main() {
  // A scripted rule's check() that never settles (e.g. it holds an
  // open event-loop handle) would otherwise keep this process alive
  // forever, since nothing else forces exit. This watchdog fires
  // regardless of what runHook() is awaiting.
  const watchdog = setTimeout(() => process.exit(0), HANG_TIMEOUT_MS)
  runHook()
    .then((output) => {
      clearTimeout(watchdog)
      if (output) console.log(JSON.stringify(output))
      process.exit(0)
    })
    .catch(() => {
      clearTimeout(watchdog)
      process.exit(0)
    })
}

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

if (require.main === module) main()
