#!/usr/bin/env node
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const source = fs.readFileSync(path.join(__dirname, '../workflows/autonomous-development.js'), 'utf8')
assert.match(source, /^export const meta = \{\n/)
const body = source.replace(/^export const meta = \{[\s\S]*?^\}/m, '')
const run = vm.compileFunction(`return (async () => { ${body} })()`, ['args', 'agent', 'phase'])
const input = { store: '/private/run', pluginRoot: '/plugin', invocation: 'offline-fixture' }

/**
 * Exercises workflow dispatch with local responses, never a real host agent.
 * @param {string} scenario - Fixture scenario
 * @returns {Promise<object>} Workflow result and observed role labels
 * @example
 * const observed = await scenario('complete')
 */
async function scenario(scenario) {
  const roles = []
  let owners = 0
  const assignment = {
    id: 'A0001', role: scenario.startsWith('review') ? 'review' : 'implement',
    store: input.store, result_file: '/private/run/reports/A0001.json',
    configuration: { execution: { provider: 'claude-workflows' } },
    limits: { review_dispatches: scenario === 'review-budget' ? 2 : 6 }
  }
  /**
   * Supplies deterministic native-call responses for a single test run.
   * @param {string} prompt - Native agent prompt
   * @param {object} options - Native agent options
   * @returns {Promise<object|null>} Simulated structured response
   * @example
   * const response = await agent('fixture prompt', { label: 'development-control' })
   */
  async function agent(prompt, options) {
    roles.push(options.label)
    if (options.label === 'development-control') {
      const outcome = roles.length === 1 ? 'running'
        : prompt.includes('Interrupt') ? 'blocked' : 'completed'
      return { outcome, assignment: outcome === 'running' ? assignment : null,
        limits: { assignments: 3 }, revision: roles.length }
    }
    if (scenario === 'missing') return null
    if (options.label === 'review-owner') {
      owners += 1
      return owners === 1
        ? { outcome: 'dispatch', result_file: '', requests: [{
          role: 'reviewer', prompt: 'Read the fixture and its callers.',
          result_file: scenario === 'review-path' ? '/outside/report.json'
            : '/private/run/reports/A0001/correctness.json'
        }] }
        : { outcome: 'complete', result_file: assignment.result_file, requests: [] }
    }
    if (options.label === 'reviewer') {
      return { outcome: 'complete', result_file: '/private/run/reports/A0001/correctness.json' }
    }
    return { outcome: 'complete', result_file: assignment.result_file }
  }
  return { result: await run(input, agent, phase), roles }
}

/**
 * Replaces the host's progress UI without starting a process.
 * @param {string} title - Phase name
 * @returns {void}
 * @example
 * phase('review')
 */
function phase(title) {
  assert.equal(typeof title, 'string')
}

/**
 * Checks successful dispatch, missing results, and finite flat-review boundaries.
 * @returns {Promise<void>}
 * @example
 * await main()
 */
async function main() {
  const complete = await scenario('complete')
  assert.equal(complete.result.outcome, 'completed')
  assert.deepEqual(complete.roles, ['development-control', 'implement', 'development-control'])
  assert.equal((await scenario('missing')).result.outcome, 'blocked')
  const review = await scenario('review-complete')
  assert.equal(review.result.outcome, 'completed')
  assert.deepEqual(review.roles, [
    'development-control', 'review-owner', 'reviewer', 'review-owner', 'development-control'
  ])
  for (const name of ['review-budget', 'review-path']) {
    const blocked = await scenario(name)
    assert.equal(blocked.result.outcome, 'blocked')
    assert(!blocked.roles.includes('reviewer'))
  }
  await assert.rejects(run({}, null, phase), /Provide absolute/)
  console.log('Development workflow offline self-check passed')
}

/**
 * Fails the offline check without swallowing its diagnostic.
 * @param {Error} error - Failed assertion or script exception
 * @returns {void}
 */
function fail(error) {
  console.error(error)
  process.exitCode = 1
}

main().catch(fail)
