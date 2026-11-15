#!/usr/bin/env node
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { execFileSync } = require('node:child_process')

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
  const recorded = []
  const waiting = scenario === 'waiting' || scenario === 'waiting-independent'
  let owners = 0
  let reviewers = 0
  let assignment = {
    id: 'A0001', role: scenario.startsWith('review') ? 'review' : waiting ? 'prepare' : 'implement',
    pr: waiting ? 'dependent' : 'first',
    root: '/project', comparison_base: 'fixture-base', private_context: 'owner-only-context',
    store: input.store, result_file: '/private/run/reports/A0001.json',
    configuration: { execution: { provider: 'claude-workflows' } },
    limits: { review_dispatches: scenario === 'review-budget' ? 2 : 6 }
  }
  /**
   * Supplies deterministic native-call responses for a single test run.
   * @param {string} prompt - Native agent prompt
   * @param {object} options - Native agent options
   * @returns {object|null} Simulated structured response
   * @example
   * const result = response('fixture prompt', { label: 'development-control' })
   */
  function response(prompt, options) {
    roles.push(options.label)
    if (options.label === 'development-control') {
      const interrupted = prompt.includes('Interrupt')
      let outcome = roles.length === 1 ? 'running'
        : interrupted ? 'blocked' : waiting ? 'waiting' : 'completed'
      if (roles.length > 1 && !interrupted) {
        assert(prompt.includes(`Read and record the complete report at ${JSON.stringify(assignment.result_file)}`))
        recorded.push(assignment.result_file)
        if (scenario === 'waiting-independent' && assignment.role === 'prepare') {
          assignment = { ...assignment, id: 'A0002', role: 'implement', pr: 'independent',
            result_file: '/private/run/reports/A0002.json' }
          outcome = 'running'
        }
      }
      return { outcome, assignment: outcome === 'running' ? assignment : null,
        limits: { assignments: 3 }, revision: roles.length, reason: interrupted ? prompt : null }
    }
    if (scenario === 'missing') return null
    if (options.label === 'review-owner') {
      owners += 1
      if (owners > 1 && scenario === 'review-replacement') {
        assert(prompt.includes('"outcome":"blocked"'))
      }
      if (owners === 1 || (owners === 2 && scenario === 'review-replacement')) {
        const resultFile = scenario === 'review-path' ? '/outside/report.json'
          : `/private/run/reports/A0001/correctness-${owners}.json`
        const packet = {
          identity: 'fixture-packet', assignment: `correctness-${owners}`,
          root: assignment.root, base: assignment.comparison_base, snapshot: 'fixture-snapshot',
          review_type: 'correctness', result_file: resultFile,
          instruction_set: { identity: 'fixture-instructions', category: 'correctness',
            sources: [{ content: 'fixture-correctness-only' }] }
        }
        return { outcome: 'dispatch', result_file: '', requests: [{
          role: 'reviewer', prompt: 'sibling-instruction-marker', result_file: resultFile,
          packet: scenario === 'review-missing-packet' ? null : packet
        }] }
      }
      return { outcome: 'complete', result_file: assignment.result_file, requests: [] }
    }
    if (options.label === 'reviewer') {
      reviewers += 1
      assert(prompt.includes('fixture-correctness-only'))
      assert(!prompt.includes('owner-only-context'))
      assert(!prompt.includes('sibling-instruction-marker'))
      assert(!prompt.includes('/WORKERS.md'))
      const outcome = scenario === 'review-waiting' ? 'waiting'
        : scenario === 'review-replacement' && reviewers === 1 ? 'blocked' : 'complete'
      return { outcome, result_file: `/private/run/reports/A0001/correctness-${reviewers}.json` }
    }
    return { outcome: assignment.role === 'prepare' ? 'waiting' : 'complete',
      result_file: assignment.result_file }
  }
  /**
   * Enforces the supplied outcome enum at the simulated native-call boundary.
   * @param {string} prompt - Native agent prompt
   * @param {object} options - Native agent options with an output schema
   * @returns {Promise<object|null>} Simulated response accepted by the outcome enum
   * @throws {assert.AssertionError} If a fixture violates the supplied outcome enum
   * @example
   * const result = await agent('fixture prompt', options)
   */
  async function agent(prompt, options) {
    const result = response(prompt, options)
    const outcomes = options.schema.properties.outcome.enum
    if (result && outcomes) {
      assert(outcomes.includes(result.outcome), `Outcome ${result.outcome} is not allowed by the agent schema`)
    }
    return result
  }
  return { result: await run(input, agent, phase), roles, recorded }
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
 * Runs the adapter against a persisted controller using only local fixture workers.
 * @param {object} fixture - Isolated Python fixture paths and failure scenario
 * @returns {Promise<object>} Durable result and dispatched labels
 * @throws {Error} If the controller or fixture protocol fails
 * @example
 * const observed = await persistedScenario(fixture)
 */
async function persistedScenario(fixture) {
  const roles = []
  /**
   * Uses fresh CLI processes and persisted revisions rather than synthetic state.
   * @param {string} command - Controller command
   * @param {...string} extra - Command arguments
   * @returns {object} Controller JSON
   * @throws {Error} If the controller rejects the operation
   * @example
   * const state = helper('status')
   */
  function helper(command, ...extra) {
    const args = [path.join(__dirname, 'development_run.py'), command, fixture.store, ...extra]
    if (command !== 'status') args.push('--revision', String(helper('status').revision))
    return JSON.parse(execFileSync(fixture.python, args, { encoding: 'utf8', stdio: 'pipe' }))
  }
  /**
   * Executes the workflow's bookkeeping instructions with the real controller.
   * @param {string} prompt - Adapter bookkeeping request
   * @returns {object} Persisted helper state
   * @throws {Error} If shutdown bookkeeping cannot be recorded
   * @example
   * const state = control('Read status.')
   */
  function control(prompt) {
    let state = helper('status')
    if (prompt.includes('Read status.')) {
      if (state.assignment) return helper('interrupt', '--reason', 'Outstanding fixture worker')
      return state.outcome === 'running' ? helper('next') : state
    }
    if (prompt.includes('Read and record the complete report at')) {
      assert(prompt.includes(JSON.stringify(state.assignment.result_file)))
      try {
        state = helper('record', '--report', state.assignment.result_file)
        return state.outcome === 'running' ? helper('next') : state
      } catch (error) {
        return helper('interrupt', '--reason', String(error.stderr || error))
      }
    }
    assert(prompt.includes('Interrupt'))
    return helper('interrupt', '--reason', prompt)
  }
  /**
   * Simulates bounded workers, retaining partial effects on failure.
   * @param {string} prompt - Native-call prompt
   * @param {object} options - Native-call options
   * @returns {Promise<object|null>} Fixture handback or missing response
   * @throws {Error} For the injected native-call failure
   * @example
   * const response = await agent(prompt, { label: 'implement' })
   */
  async function agent(prompt, options) {
    roles.push(options.label)
    if (options.label === 'development-control') return control(prompt)
    const assignment = helper('status').assignment
    assert(['implement', 'review-owner'].includes(options.label))
    if (options.label === 'implement') {
      const name = fixture.scenario === 'scope' ? 'unapproved.txt' : 'app.txt'
      fs.writeFileSync(path.join(assignment.root, name), 'after\n')
      if (fixture.scenario === 'throw') throw new Error('Fixture native call failed')
      if (fixture.scenario === 'missing') return null
      if (fixture.scenario === 'missing-input') {
        fs.unlinkSync(assignment.artifacts.find(item => item.id === 'design').snapshot)
      }
    }
    const outcome = options.label === 'implement' ? 'complete' : 'blocked'
    fs.writeFileSync(assignment.result_file, JSON.stringify({
      assignment: assignment.id, worker: null, outcome,
      summary: 'Offline fixture stops at the next review boundary',
      evidence: ['Local fixture worker only; no model or network calls'],
      artifacts: Object.fromEntries(assignment.artifacts.map(item => [item.id, item.sha256])),
      data: {}
    }))
    return { outcome, result_file: assignment.result_file, requests: [] }
  }
  const args = { store: fixture.store, pluginRoot: path.resolve(__dirname, '..'),
    invocation: fixture.invocation }
  return { result: await run(args, agent, phase), roles }
}

/**
 * Checks successful dispatch, missing results, and finite flat-review boundaries.
 * @returns {Promise<void>}
 * @example
 * await main()
 */
async function main() {
  if (process.argv[2] === '--persisted-controller') {
    const observed = await persistedScenario(JSON.parse(fs.readFileSync(0, 'utf8')))
    process.stdout.write(JSON.stringify(observed))
    return
  }
  const complete = await scenario('complete')
  assert.equal(complete.result.outcome, 'completed')
  assert.deepEqual(complete.roles, ['development-control', 'implement', 'development-control'])
  assert.equal((await scenario('missing')).result.outcome, 'blocked')
  const review = await scenario('review-complete')
  assert.equal(review.result.outcome, 'completed')
  assert.deepEqual(review.roles, [
    'development-control', 'review-owner', 'reviewer', 'review-owner', 'development-control'
  ])
  for (const name of ['review-budget', 'review-path', 'review-missing-packet']) {
    const blocked = await scenario(name)
    assert.equal(blocked.result.outcome, 'blocked')
    assert(!blocked.roles.includes('reviewer'))
  }
  for (const name of ['waiting', 'waiting-independent']) {
    const waiting = await scenario(name)
    assert.equal(waiting.result.outcome, 'waiting', waiting.result.reason)
    const roles = ['development-control', 'prepare', 'development-control']
    const recorded = ['/private/run/reports/A0001.json']
    if (name === 'waiting-independent') {
      roles.push('implement', 'development-control')
      recorded.push('/private/run/reports/A0002.json')
    }
    assert.deepEqual(waiting.roles, roles)
    assert.deepEqual(waiting.recorded, recorded)
    assert.equal(waiting.result.assignment, null)
  }
  const incompleteReview = await scenario('review-waiting')
  assert.equal(incompleteReview.result.outcome, 'blocked')
  assert.deepEqual(incompleteReview.roles, [
    'development-control', 'review-owner', 'reviewer', 'development-control'
  ])
  assert.deepEqual(incompleteReview.recorded, [])
  const replacement = await scenario('review-replacement')
  assert.equal(replacement.result.outcome, 'completed', replacement.result.reason)
  assert.deepEqual(replacement.roles, [
    'development-control', 'review-owner', 'reviewer', 'review-owner',
    'reviewer', 'review-owner', 'development-control'
  ])
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
