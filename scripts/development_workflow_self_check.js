#!/usr/bin/env node
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { execFileSync } = require('node:child_process')
const { createHash } = require('node:crypto')

const source = fs.readFileSync(path.join(__dirname, '../workflows/autonomous-development.js'), 'utf8')
assert.match(source, /^export const meta = \{\n/)
const body = source.replace(/^export const meta = \{[\s\S]*?^\}/m, '')
const run = vm.compileFunction(`return (async () => { ${body} })()`, ['args', 'agent', 'phase'])
const modelRoles = ['development-control', 'preflight', 'prepare', 'implement', 'review-owner',
  'reviewer', 'adjudicator', 'validator', 'fixer', 'commit', 'draft', 'audit-initial', 'audit-final',
  'evidence', 'ready']
const fixtureModels = Object.fromEntries(modelRoles.map(role => [role, {
  model: `fixture-${role}`, effort: role === 'development-control' ? 'low' : 'high', fallback: 'fail'
}]))
const input = { store: '/private/run', pluginRoot: '/plugin', invocation: 'offline-fixture',
  models: fixtureModels }

/**
 * Supplies compact checkpoint receipts to in-memory host fixtures.
 * @param {object} assignment - Fixture assignment
 * @param {string} input - Checkpoint JSON from the adapter
 * @returns {void}
 * @throws {assert.AssertionError} If a retained request changes
 * @example
 * fixtureCheckpoint(assignment, input)
 */
function fixtureCheckpoint(assignment, input) {
  const { assignment: id, ...saved } = JSON.parse(input)
  assert.equal(id, assignment.id)
  for (const [path, value] of Object.entries(saved.reservations)) {
    const previous = assignment.review_dispatch.reservations[path]
    if (value.identity !== previous?.identity) {
      value.identity = createHash('sha256').update(value.identity).digest('hex')
    }
    if (previous) assert.equal(value.identity, previous.identity, 'Review report request changed')
  }
  assignment.review_dispatch = saved
}

/**
 * Exercises workflow dispatch with local responses, never a real host agent.
 * @param {string} scenario - Fixture scenario
 * @param {object} setup - Assignment policy and expected native choices
 * @returns {Promise<object>} Workflow result and observed role labels
 * @example
 * const observed = await scenario('complete')
 */
async function scenario(scenario, setup = {}) {
  const roles = []
  const recorded = []
  const waiting = scenario === 'waiting' || scenario === 'waiting-independent'
  let owners = 0
  let reviewers = 0
  let assignment = {
    id: 'A0001', role: scenario.startsWith('audit-') ? scenario
      : scenario.startsWith('review') ? 'review' : waiting ? 'prepare' : 'implement',
    pr: waiting ? 'dependent' : 'first',
    root: '/project', comparison_base: 'fixture-base', private_context: 'owner-only-context',
    store: input.store, result_file: '/private/run/reports/A0001.json',
    configuration: { execution: { provider: 'claude-workflows' } },
    review_dispatch: { calls: 0, reservations: {}, reports: [] },
    limits: { review_dispatches: scenario === 'review-budget' ? 2 : 6 }
  }
  if (scenario === 'review-model-overrides') {
    assignment.configuration.execution.models = {
      reviewer: { model: 'manifest-reviewer', effort: 'medium', fallback: 'fail' },
      'review-owner': { model: 'manifest-owner', effort: 'max', fallback: 'fail' }
    }
    assignment.model_selection = { enabled: true, review_auto_enabled: true, review_options: {
      model_selection: 'auto', roles: {
        reviewer: { model: 'review-option', effort: 'xhigh', fallback: 'fail' }
      }
    } }
  }
  if (scenario === 'model-configured') assignment.model_selection = { enabled: false }
  if (scenario === 'model-fallback') {
    assignment.configuration.execution.models = {
      implement: { model: 'unavailable-native-model', effort: 'high', fallback: 'configured' }
    }
    assignment.configured_model_fallbacks = ['implement']
  }
  Object.assign(assignment, setup.assignment)
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
      const checkpoint = prompt.match(/^Review checkpoint: (.+)$/m)
      if (checkpoint) {
        fixtureCheckpoint(assignment, checkpoint[1])
        if (scenario === 'review-checkpoint-missing') return null
        if (scenario === 'review-checkpoint-throw') throw new Error('Fixture checkpoint acknowledgment lost')
        return { outcome: 'running', assignment, limits: { assignments: 3 }, revision: roles.length }
      }
      const interrupted = prompt.includes('Interrupt')
      let outcome = roles.length === 1 ? 'running'
        : interrupted || scenario === 'review-context-conflict' ? 'blocked'
          : waiting ? 'waiting' : 'completed'
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
      if (owners === 2 && scenario === 'review-context-conflict') {
        assert(prompt.includes('"context_blocker":"Known conflicting review assignment"'))
        return { outcome: 'blocked', result_file: assignment.result_file, requests: [] }
      }
      if (owners === 2 && scenario === 'review-source-read') {
        assert(prompt.includes('assess a reported isolation concern before ordering replacement'))
        assert(prompt.includes('"context_blocker":"Read the cited project standards file"'))
        return { outcome: 'dispatch', result_file: '', requests: [{
          role: 'adjudicator', prompt: 'Assess the source-read-only classification and otherwise complete coverage.',
          result_file: '/private/run/reports/A0001/adjudication.json'
        }] }
      }
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
      assert(prompt.includes('Ignore them for this review. Only this explicitly supplied ruleset'))
      assert(prompt.includes('their presence alone is not contamination'))
      assert(prompt.includes('including standards owned by another category or cited by the plan'))
      assert.equal(options.agentType, undefined)
      const outcome = scenario === 'review-waiting' ? 'waiting'
        : ['review-context-conflict', 'review-source-read'].includes(scenario) ? 'blocked'
        : scenario === 'review-replacement' && reviewers === 1 ? 'blocked' : 'complete'
      return { outcome, result_file: `/private/run/reports/A0001/correctness-${reviewers}.json`,
        context_blocker: scenario === 'review-context-conflict' ? 'Known conflicting review assignment'
          : scenario === 'review-source-read' ? 'Read the cited project standards file' : null }
    }
    if (options.label === 'adjudicator' && scenario === 'review-source-read') {
      return { outcome: 'complete', result_file: '/private/run/reports/A0001/adjudication.json' }
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
    let expected = setup.expected?.[options.label] ?? fixtureModels[options.label]
    if (scenario === 'review-model-overrides' && options.label === 'reviewer') {
      expected = { model: 'review-option', effort: 'xhigh' }
    } else if (scenario === 'review-model-overrides' && options.label === 'review-owner') {
      expected = { model: 'manifest-owner', effort: 'max' }
    } else if (['model-configured', 'model-fallback'].includes(scenario) && options.label === 'implement') {
      expected = {}
    }
    assert.equal(options.model, expected.model)
    assert.equal(options.effort, expected.effort)
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
 * Observes real promise overlap and exclusive fixer barriers without a live host.
 * @param {boolean|string} failLeaf - True for native failure, 'context' for conflict, false for success
 * @param {object} policy - Model-selection policy supplied by the controller
 * @param {number} [dispatchLimit=20] - Owner and reserved leaf allowance
 * @returns {Promise<void>}
 * @throws {assert.AssertionError} When dispatch serializes readers or overlaps writers
 * @example
 * await concurrentReview(false)
 */
async function concurrentReview(failLeaf, policy = {}, dispatchLimit = 20) {
  const assignment = {
    id: 'A0001', role: 'review', root: '/project', comparison_base: 'base',
    store: input.store, result_file: '/private/run/reports/A0001.json',
    configuration: { execution: { provider: 'claude-workflows' } },
    review_dispatch: { calls: 0, reservations: {}, reports: [] },
    monitoring: { enabled: true }, model_selection: policy, limits: { review_dispatches: dispatchLimit }
  }
  const resuming = ['resume', 'changed-reservation', 'completed-path', 'duplicate-reservation'].includes(failLeaf)
  const blocked = Boolean(failLeaf && failLeaf !== 'resume')
  const assessmentFile = '/private/run/reports/A0001/isolation-assessment.json'
  let assessed = false
  let owners = 0
  let active = 0
  let maximum = 0
  let finished = 0
  let fixing = false
  const trace = []
  const requests = ['reviewer', 'reviewer', 'fixer', 'fixer', 'validator', 'reviewer'].map((role, index) => {
    const result_file = `/private/run/reports/A0001/leaf-${index}.json`
    const review_type = index === 0 ? 'correctness' : 'integration'
    return { role, prompt: `Independent fixture ${index}`, result_file, packet: role === 'reviewer' ? {
      identity: `packet-${index}`, review_type, root: assignment.root, base: assignment.comparison_base,
      result_file, instruction_set: { category: review_type, identity: `instructions-${index}` }
    } : null }
  })
  if (failLeaf === 'aliased-path') {
    requests[1].result_file = requests[0].result_file.replace('/leaf-', '//leaf-')
    requests[1].packet.result_file = requests[1].result_file
  }
  /**
   * Keeps fake workers in flight long enough to detect sequential scheduling.
   * @param {string} prompt - Native-call prompt
   * @param {object} options - Native-call options
   * @returns {Promise<object>} Fixture worker response
   * @throws {Error} For the injected reviewer failure
   * @example
   * const response = await worker('fixture', options)
   */
  async function worker(prompt, options) {
    if (options.label === 'development-control') {
      assert.equal(active, 0, 'Controller must not advance while a sibling is still running')
      const checkpoint = prompt.match(/^Review checkpoint: (.+)$/m)
      if (checkpoint) {
        fixtureCheckpoint(assignment, checkpoint[1])
        return { assignment, limits: { assignments: 1 }, revision: 0, outcome: 'running' }
      }
      return { assignment: owners ? null : assignment, limits: { assignments: 1 }, revision: 0,
        outcome: owners ? (prompt.includes('Interrupt') || failLeaf === 'context' ? 'blocked' : 'completed') : 'running',
        reason: prompt.includes('Interrupt') ? prompt : null }
    }
    if (options.label === 'review-owner') {
      owners += 1
      if (owners === 1) return { outcome: 'dispatch', result_file: '', requests }
      if (owners === 2 && resuming) {
        assert.equal(finished, 2)
        assert(prompt.includes('"outcome":"not_started"'))
        return { outcome: 'dispatch', result_file: '', requests: [{
          role: 'adjudicator', prompt: 'Assess the original source-read-only conflict.',
          result_file: assessmentFile
        }] }
      }
      if (owners === 3 && resuming) {
        assert(assessed)
        const remaining = requests.slice(2).map(request => Object.fromEntries(Object.entries(request).reverse()))
        remaining[3].packet = Object.fromEntries(Object.entries(remaining[3].packet).reverse())
        if (failLeaf === 'changed-reservation') remaining[0].prompt = 'Different correction assignment'
        if (failLeaf === 'completed-path') remaining[0] = requests[1]
        if (failLeaf === 'duplicate-reservation') remaining.push(remaining[0])
        return { outcome: 'dispatch', result_file: '', requests: remaining }
      }
      if (failLeaf === 'context') {
        assert.equal(finished, 2)
        assert(prompt.includes('"outcome":"not_started"'))
        return { outcome: 'blocked', result_file: assignment.result_file, requests: [] }
      }
      assert.equal(finished, requests.length)
      return { outcome: 'complete', result_file: assignment.result_file, requests: [] }
    }
    const result_file = JSON.parse(prompt.match(/Assigned result file: (.+)/)[1])
    if (result_file === assessmentFile) {
      assert.equal(active, 0)
      assert.equal(finished, 2)
      assessed = true
      return { outcome: 'complete', result_file }
    }
    const index = requests.findIndex(item => item.result_file === result_file)
    const progress = JSON.parse(prompt.match(/Progress arguments: (.+)/)[1])
    assert.equal(progress[progress.indexOf('--dispatch') + 1], String(index + 2))
    assert(!fixing, 'No leaf may overlap a fixer')
    if (options.label === 'fixer') {
      assert.equal(options.model, fixtureModels.fixer.model)
      assert.equal(options.effort, fixtureModels.fixer.effort)
      assert.equal(active, 0, 'Fixers must wait for every reader and previous fixer')
      fixing = true
    }
    active += 1
    maximum = Math.max(maximum, active)
    trace.push(`start-${index}`)
    await new Promise(resolve => setTimeout(resolve, index === 0 ? 10 : 30))
    active -= 1
    fixing = false
    finished += 1
    trace.push(`end-${index}`)
    if (failLeaf === true && index === 0) throw new Error('Fixture concurrent leaf failed')
    if ((failLeaf === 'context' || resuming) && index === 0) {
      return { outcome: 'blocked', result_file, context_blocker: 'Conflicting injected review instructions' }
    }
    return { outcome: 'complete', result_file }
  }
  const result = await run(input, worker, phase)
  if (failLeaf === 'aliased-path') {
    assert.equal(result.outcome, 'blocked')
    assert.equal(finished, 0)
    assert.equal(maximum, 0)
    assert.equal(Object.keys(assignment.review_dispatch.reservations).length, 0)
    return
  }
  assert.equal(maximum, 2, 'Independent leaves must overlap')
  assert.equal(result.outcome, blocked ? 'blocked' : 'completed', result.reason)
  if (blocked) {
    assert.equal(finished, 2, 'Drain already-launched siblings, but do not start later fixer batches')
    if (resuming) {
      assert(assessed)
      assert.match(result.reason, /Review report/)
    }
  } else {
    assert.equal(finished, requests.length)
    assert(trace.indexOf('end-1') < trace.indexOf('start-2'))
    assert(trace.indexOf('end-2') < trace.indexOf('start-3'))
    assert(trace.indexOf('end-3') < trace.indexOf('start-4'))
  }
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
  let review = null
  /**
   * Keeps fake native review work backed by real phase files and ledger events.
   * @param {string} action - Prepare requests or finish the recorded review
   * @returns {object} Frozen requests or the final report reference
   * @throws {Error} If the persisted review fixture fails
   * @example
   * const requests = reviewWorker('prepare')
   */
  function reviewWorker(action) {
    return JSON.parse(execFileSync(fixture.python, [
      path.join(__dirname, 'development_run_self_check.py'), '--workflow-review-fixture'
    ], { input: JSON.stringify({ store: fixture.store, action }), encoding: 'utf8',
      stdio: 'pipe', maxBuffer: 8 * 1024 * 1024 }))
  }
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
    const input = command === 'review-checkpoint' ? extra.shift() : undefined
    const args = [path.join(__dirname, 'development_run.py'), command, fixture.store, ...extra]
    if (command !== 'status') args.push('--revision', String(helper('status').revision))
    return JSON.parse(execFileSync(fixture.python, args, {
      input, encoding: 'utf8', stdio: 'pipe', maxBuffer: 8 * 1024 * 1024
    }))
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
    const checkpoint = prompt.match(/^Review checkpoint: (.+)$/m)
    if (checkpoint) return helper('review-checkpoint', checkpoint[1])
    if (prompt.includes('Read status.')) {
      if (state.assignment?.review_resume_ready) {
        assert(prompt.includes('claim-review --provider claude-workflows'))
        return helper('claim-review', '--provider', 'claude-workflows')
      }
      if (state.assignment) return helper('interrupt', '--reason', 'Outstanding fixture worker')
      if (state.outcome !== 'running') return state
      assert(prompt.includes('--provider claude-workflows'))
      assert(prompt.includes('pass --models'))
      try {
        return helper('next', '--provider', 'claude-workflows', '--models', JSON.stringify(fixtureModels))
      } catch (error) {
        return helper('interrupt', '--reason', String(error.stderr || error))
      }
    }
    if (prompt.includes('Read and record the complete report at')) {
      assert(prompt.includes(JSON.stringify(state.assignment.result_file)))
      try {
        state = helper('record', '--report', state.assignment.result_file)
        assert(prompt.includes('--provider claude-workflows'))
        return state.outcome === 'running'
          ? helper('next', '--provider', 'claude-workflows', '--models', JSON.stringify(fixtureModels)) : state
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
    const expected = fixture.expected_models?.[options.label]
    if (expected) {
      assert.equal(options.model, expected.model)
      assert.equal(options.effort, expected.effort)
    }
    const modelArgs = JSON.parse(prompt.match(/^Model report arguments: (.+)$/m)[1])
    const modelRecord = JSON.parse(execFileSync(fixture.python, [...modelArgs.slice(1),
      '--actual-model', `observed-${options.label}`, '--source', 'native-context'],
    { encoding: 'utf8', stdio: 'pipe' }))
    const progressLine = prompt.match(/^Progress arguments: (.+)$/m)
    const progressArgs = progressLine ? JSON.parse(progressLine[1]) : null
    if (progressArgs) {
      execFileSync(fixture.python, [...progressArgs.slice(1), '--event', 'started'],
        { stdio: 'pipe' })
    }
    const result = options.label === 'development-control' ? control(prompt) : await work(prompt, options)
    if (progressArgs && result) {
      execFileSync(fixture.python, [...progressArgs.slice(1), '--event', 'reported'],
        { stdio: 'pipe' })
    }
    if (result?.result_file && fs.existsSync(result.result_file)) {
      const report = JSON.parse(fs.readFileSync(result.result_file, 'utf8'))
      if (options.label === 'reviewer') report.selection.model_report = modelRecord.model_report
      else report.model_report = modelRecord.model_report
      fs.writeFileSync(result.result_file, JSON.stringify(report))
    }
    return result
  }
  /**
   * Supplies bounded fixture results after the worker's real progress checkpoint.
   * @param {string} prompt - Purpose-only native prompt
   * @param {object} options - Native-call options
   * @returns {Promise<object|null>} Fixture result
   * @throws {Error} For an injected worker failure
   * @example
   * const result = await work(prompt, options)
   */
  async function work(prompt, options) {
    const assignment = helper('status').assignment
    if (assignment.task_plan) assert(!Object.hasOwn(assignment.task_plan, 'paths'))
    if (fixture.scenario.startsWith('review-') && options.label === 'review-owner') {
      if (fixture.scenario === 'review-recovered') return reviewWorker('finish-recovered')
      if (review) return reviewWorker('finish')
      review = reviewWorker('prepare')
      const requests = review.packets.map(packet => ({
        role: 'reviewer', prompt: '', result_file: packet.result_file, packet
      }))
      if (fixture.scenario === 'review-budget') {
        while (requests.length < assignment.limits.review_dispatches) requests.push(requests[0])
      }
      if (fixture.scenario === 'review-path') requests[0].result_file = '/outside/report.json'
      if (fixture.scenario === 'review-missing-packet') requests[0].packet = null
      return { outcome: 'dispatch', result_file: '', requests }
    }
    if (options.label === 'reviewer') {
      const handoff = JSON.parse(fs.readFileSync(review.handoff, 'utf8'))
      const prefix = '\nFrozen packet: '
      const packet = JSON.parse(prompt.slice(prompt.indexOf(prefix) + prefix.length))
      const attempt = handoff.attempts.find(item => item.packet.identity === packet.identity)
      assert(attempt, 'Reviewer must receive its exact frozen packet')
      assert.deepEqual(packet, attempt.packet)
      await new Promise(resolve => setTimeout(resolve, 10))
      fs.writeFileSync(attempt.packet.result_file, JSON.stringify(attempt.result))
      if (fixture.scenario === 'review-throw') throw new Error('Fixture review native call failed')
      return { outcome: 'complete', result_file: attempt.packet.result_file }
    }
    assert(['implement', 'review-owner', 'commit'].includes(options.label))
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
      summary: 'Offline fixture stops at the next review or commit boundary',
      evidence: ['Local fixture worker only; no model or network calls'],
      artifacts: Object.fromEntries(assignment.artifacts.map(item => [item.id, item.sha256])),
      data: {}
    }))
    return { outcome, result_file: assignment.result_file, requests: [] }
  }
  const args = { store: fixture.store, pluginRoot: path.resolve(__dirname, '..'),
    invocation: fixture.invocation, models: fixtureModels }
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
  assert.equal((await scenario('review-model-overrides')).result.outcome, 'completed')
  assert.equal((await scenario('model-configured')).result.outcome, 'completed')
  assert.equal((await scenario('model-fallback')).result.outcome, 'completed')
  assert.equal((await scenario('review-model-only', {
    assignment: {
      configuration: { execution: { provider: 'claude-workflows', models: {
        reviewer: { model: 'inherited-reviewer', effort: 'high', fallback: 'fail' }
      } } },
      model_selection: { enabled: true, review_auto_enabled: true, review_options: {
        roles: { reviewer: { model: 'model-only-override', effort: null, fallback: 'fail' } }
      } }
    },
    expected: { reviewer: { model: 'model-only-override' } }
  })).result.outcome, 'completed')
  for (const role of ['audit-initial', 'audit-final']) {
    const audited = await scenario(role)
    assert.equal(audited.result.outcome, 'completed')
    assert.deepEqual(audited.roles, ['development-control', role, 'development-control'])
    assert.deepEqual(audited.recorded, ['/private/run/reports/A0001.json'])
  }
  assert.equal((await scenario('missing')).result.outcome, 'blocked')
  const review = await scenario('review-complete')
  assert.equal(review.result.outcome, 'completed')
  assert.deepEqual(review.roles, [
    'development-control', 'development-control', 'review-owner', 'development-control',
    'reviewer', 'development-control', 'review-owner', 'development-control'
  ])
  for (const name of ['review-budget', 'review-path', 'review-missing-packet']) {
    const blocked = await scenario(name)
    assert.equal(blocked.result.outcome, 'blocked')
    assert(!blocked.roles.includes('reviewer'))
  }
  for (const name of ['review-checkpoint-missing', 'review-checkpoint-throw']) {
    const blocked = await scenario(name)
    assert.equal(blocked.result.outcome, 'blocked')
    assert(!blocked.roles.includes('review-owner'))
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
    'development-control', 'development-control', 'review-owner', 'development-control',
    'reviewer', 'development-control'
  ])
  assert.deepEqual(incompleteReview.recorded, [])
  const replacement = await scenario('review-replacement')
  assert.equal(replacement.result.outcome, 'completed', replacement.result.reason)
  assert.deepEqual(replacement.roles, [
    'development-control', 'development-control', 'review-owner', 'development-control',
    'reviewer', 'development-control', 'review-owner', 'development-control',
    'reviewer', 'development-control', 'review-owner', 'development-control'
  ])
  const contextConflict = await scenario('review-context-conflict')
  assert.equal(contextConflict.result.outcome, 'blocked')
  assert.deepEqual(contextConflict.roles, [
    'development-control', 'development-control', 'review-owner', 'development-control',
    'reviewer', 'development-control', 'review-owner', 'development-control'
  ])
  const sourceRead = await scenario('review-source-read')
  assert.equal(sourceRead.result.outcome, 'completed')
  assert.deepEqual(sourceRead.roles, [
    'development-control', 'development-control', 'review-owner', 'development-control',
    'reviewer', 'development-control', 'review-owner', 'development-control',
    'adjudicator', 'development-control', 'review-owner', 'development-control'
  ])
  await assert.rejects(run({}, null, phase), /Provide absolute/)
  await assert.rejects(run({ ...input, models: {} }, null, phase), /Resolve native model/)
  await concurrentReview(false)
  await concurrentReview(false, { enabled: true, review_auto_enabled: false })
  await concurrentReview(true)
  await concurrentReview('context')
  await concurrentReview('resume')
  await concurrentReview('resume', {}, 12)
  await concurrentReview('changed-reservation')
  await concurrentReview('completed-path')
  await concurrentReview('duplicate-reservation')
  await concurrentReview('aliased-path')
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
