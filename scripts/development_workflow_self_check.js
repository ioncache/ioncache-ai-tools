#!/usr/bin/env node
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { execFileSync } = require('node:child_process')

const source = fs.readFileSync(path.join(__dirname, '../workflows/autonomous-development.js'), 'utf8')
const modelRoles = ['development-control', 'preflight', 'prepare', 'implement', 'review-owner',
  'reviewer', 'adjudicator', 'validator', 'fixer', 'commit', 'draft', 'audit-initial', 'audit-final',
  'evidence', 'ready']
const fixtureModels = Object.fromEntries(modelRoles.map(role => [role, {
  model: `fixture-${role}`, effort: role === 'development-control' ? 'low' : 'high', fallback: 'fail'
}]))

/**
 * Executes a generated batch with a fake native agent boundary.
 * @param {string} script - Complete workflow source
 * @param {Function} agent - Offline worker callback
 * @returns {Promise<object>} Advisory native observations
 * @example
 * const result = await execute(script, fakeAgent)
 */
function execute(script, agent) {
  assert.match(script, /^export const meta = \{\n/)
  const body = script.replace(/^export const meta = \{[\s\S]*?^\}/m, '')
  return vm.compileFunction(`return (async () => { ${body} })()`, ['agent', 'phase'])(
    agent, title => assert.equal(typeof title, 'string'))
}

/**
 * Runs Python-owned dispatches against real private state using fake workers.
 * @param {object} fixture - Isolated store and injected failure scenario
 * @returns {Promise<object>} Durable controller status and launched roles
 * @throws {Error} If an offline fixture command fails
 * @example
 * const observed = await persistedScenario(fixture)
 */
async function persistedScenario(fixture) {
  const roles = []
  let review = null
  const modelFile = path.join(fixture.store, 'fixture-models.json')
  fs.writeFileSync(modelFile, JSON.stringify(fixtureModels))
  /**
   * Executes a deterministic helper with closed stdin and a bounded runtime.
   * @param {string} script - Helper filename
   * @param {string[]} argv - Literal arguments
   * @param {object} [input] - Optional JSON stdin
   * @returns {object} Parsed helper output
   * @example
   * const state = call('development_run.py', ['status', fixture.store])
   */
  function call(script, argv, input) {
    return JSON.parse(execFileSync(fixture.python, [path.join(__dirname, script), ...argv], {
      input: input === undefined ? '' : JSON.stringify(input), encoding: 'utf8',
      stdio: 'pipe', maxBuffer: 16 * 1024 * 1024, timeout: 30000
    }))
  }
  /** @returns {object} Current persisted status. */
  function status() {
    return call('development_run.py', ['status', fixture.store])
  }
  /** @param {string} reason - Native or collector error. @returns {void} */
  function interrupt(reason) {
    call('development_run.py', ['interrupt', fixture.store, '--revision', String(status().revision), '--reason', reason])
  }
  /** @param {string} action - Fixture review action. @returns {object} Ledger-backed fixture. */
  function reviewWorker(action) {
    return call('development_run_self_check.py', ['--workflow-review-fixture'], { store: fixture.store, action })
  }
  /** @returns {void} Closes the accepted ledger at a dispatch boundary. */
  function closeAcceptedReview() {
    const state = status()
    const accepted = state.prs[state.assignment.pr].review
    const ledger = JSON.parse(fs.readFileSync(accepted.ledger, 'utf8'))
    execFileSync(fixture.python, [path.join(__dirname, 'review_ledger.py'), 'apply',
      accepted.ledger, '--revision', String(ledger.events.length)], {
      cwd: state.assignment.root, input: JSON.stringify({
        type: 'stop', outcome: 'failed', actor: 'fixture', reason: 'Closed at the dispatch boundary'
      }), stdio: 'pipe', timeout: 30000
    })
  }
  /**
   * Produces actual report files; returned native JSON has no control authority.
   * @param {string} prompt - Frozen job instructions
   * @param {object} options - Native role/model options
   * @returns {Promise<object|null>} Advisory native result
   * @throws {Error} For the selected simulated worker failure
   * @example
   * const result = await agent(prompt, options)
   */
  async function agent(prompt, options) {
    roles.push(options.label)
    const expected = fixture.expected_models?.[options.label]
    if (expected) {
      assert.equal(options.model, expected.model)
      assert.equal(options.effort, expected.effort)
    }
    const start = JSON.parse(prompt.match(/^Start arguments: (.+)$/m)[1])
    execFileSync(fixture.python, start.slice(1), { input: '', stdio: 'pipe', timeout: 30000 })
    const assignment = status().assignment
    const resultFile = JSON.parse(prompt.match(/^Assigned result file: (.+)$/m)[1])
    const submit = JSON.parse(prompt.match(/^Submit arguments: (.+)$/m)[1])
    assert.equal(submit[submit.indexOf('--candidate') + 1], `${resultFile}.candidate.json`)
    const modelArgs = JSON.parse(prompt.match(/^Model report arguments: (.+)$/m)[1])
    const modelRecord = JSON.parse(execFileSync(fixture.python, [...modelArgs.slice(1),
      '--actual-model', `observed-${options.label}`, '--source', 'native-context'],
    { input: '', encoding: 'utf8', stdio: 'pipe', timeout: 30000 }))
    let report
    if (options.label === 'review-owner' && fixture.scenario.startsWith('review-')) {
      if (fixture.scenario === 'review-recovered') report = reviewWorker('finish-recovered')
      else if (review) report = reviewWorker('finish')
      else {
        review = reviewWorker('prepare')
        const requests = review.packets.map(packet => ({
          role: 'reviewer', prompt: '', result_file: packet.result_file, packet
        }))
        if (fixture.scenario === 'review-budget') {
          while (requests.length < assignment.limits.review_dispatches) requests.push({
            role: 'adjudicator', prompt: 'Independent fixture assessment',
            result_file: `${fixture.store}/reports/${assignment.id}/budget-${requests.length}.json`
          })
        }
        if (fixture.scenario === 'review-path') requests[0].result_file = '/outside/report.json'
        if (fixture.scenario === 'review-missing-packet') requests[0].packet = null
        report = { outcome: 'dispatch', result_file: '', requests }
      }
      report.requests ||= []
    } else if (options.label === 'reviewer') {
      const handoff = JSON.parse(fs.readFileSync(review.handoff, 'utf8'))
      const packet = JSON.parse(prompt.slice(prompt.indexOf('\nFrozen packet: ') + '\nFrozen packet: '.length))
      const attempt = handoff.attempts.find(item => item.packet.identity === packet.identity)
      assert.deepEqual(packet, attempt.packet)
      report = attempt.result
      report.selection.model_report = modelRecord.model_report
    } else {
      assert(['implement', 'review-owner', 'commit'].includes(options.label))
      if (options.label === 'implement') {
        fs.writeFileSync(path.join(assignment.root, fixture.scenario === 'scope' ? 'unapproved.txt' : 'app.txt'), 'after\n')
        if (fixture.scenario === 'throw') throw new Error('Fixture native call failed')
        if (fixture.scenario === 'missing') return null
        if (fixture.scenario === 'missing-input') {
          fs.unlinkSync(assignment.artifacts.find(item => item.id === 'design').snapshot)
        }
      }
      const committing = options.label === 'commit' && fixture.scenario === 'close-after-dispatch'
      const data = {}
      if (committing) {
        execFileSync('git', ['add', 'app.txt'], { cwd: assignment.root, stdio: 'pipe' })
        execFileSync('git', ['commit', '-qm', 'Fixture claimed commit'], { cwd: assignment.root, stdio: 'pipe' })
        data.commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: assignment.root, encoding: 'utf8' }).trim()
      }
      const outcome = options.label === 'implement' || committing ? 'complete' : 'blocked'
      const development = {
        assignment: assignment.id, worker: null, outcome, summary: 'Offline fixture result',
        evidence: ['Local fixture worker only; no model or network calls'],
        artifacts: Object.fromEntries(assignment.artifacts.map(item => [item.id, item.sha256])),
        data, model_report: modelRecord.model_report
      }
      fs.writeFileSync(assignment.result_file, JSON.stringify(development))
      report = options.label === 'review-owner'
        ? { outcome, result_file: assignment.result_file, requests: [] } : development
    }
    fs.writeFileSync(resultFile, JSON.stringify(report))
    if (options.label === 'reviewer' && fixture.scenario === 'review-throw') {
      throw new Error('Fixture review native call failed')
    }
    const finish = JSON.parse(prompt.match(/^Finish arguments: (.+)$/m)[1])
    try {
      execFileSync(fixture.python, finish.slice(1), { input: '', stdio: 'pipe', timeout: 30000 })
    } catch (error) {
      throw new Error(String(error.stdout || error.stderr || error))
    }
    if (options.label === 'implement' && fixture.scenario === 'lost-finished-reply') {
      throw new Error('Fixture lost native reply after successful finish')
    }
    return { outcome: 'completed', revision: 0, assignment: null }
  }
  for (let step = 0; step < 100; step += 1) {
    try {
      const batch = call('development_handoff.py', ['prepare', fixture.store, '--models-file', modelFile])
      if (batch.action === 'inspect') break
      if (batch.action === 'collect') {
        call('development_handoff.py', ['collect', fixture.store, '--batch', batch.batch])
        continue
      }
      if (batch.action !== 'launch') {
        interrupt('Outstanding native batch; inspect its reports and reconcile shutdown')
        break
      }
      if (fixture.scenario === 'close-before-dispatch' && status().assignment.role === 'commit') closeAcceptedReview()
      call('development_handoff.py', ['claim', fixture.store, '--batch', batch.batch])
      const observed = await execute(fs.readFileSync(batch.script, 'utf8'), agent)
      if (fixture.scenario === 'close-after-dispatch' && status().assignment.role === 'commit') closeAcceptedReview()
      try {
        call('development_handoff.py', ['collect', fixture.store, '--batch', batch.batch])
      } catch (error) {
        const failures = observed.observations.filter(item => item.error || !item.returned)
        throw new Error([String(error.stdout || error.stderr || error),
          ...failures.map(item => item.error || 'Missing native result')].join('\n'))
      }
    } catch (error) {
      interrupt(String(error.stdout || error.stderr || error))
      break
    }
  }
  return { result: status(), roles }
}

/**
 * Verifies bounded batching, draining failures, and ignoring fabricated state.
 * @returns {Promise<void>}
 * @example
 * await main()
 */
async function main() {
  if (process.argv[2] === '--persisted-controller') {
    process.stdout.write(JSON.stringify(await persistedScenario(JSON.parse(fs.readFileSync(0, 'utf8')))))
    return
  }
  await assert.rejects(execute(source, null), /generated scriptPath/)
  const handoff = { batch: 'B000001', assignment: 'A0001', store: '/private/run', pluginRoot: '/plugin',
    jobs: ['reviewer', 'validator'].map(role => ({ role, prompt: 'Only this purpose',
      result_file: `/private/run/${role}.json`, options: { model: `fixture-${role}` } })) }
  let active = 0
  let maximum = 0
  let finished = 0
  const observed = await execute(source.replace('const handoff = null', `const handoff = ${JSON.stringify(handoff)}`),
    async (prompt, options) => {
      assert(!prompt.includes('development-control'))
      assert(prompt.includes('Finish arguments:'))
      assert.equal(options.model, `fixture-${options.label}`)
      active += 1
      maximum = Math.max(maximum, active)
      await new Promise(resolve => setTimeout(resolve, options.label === 'reviewer' ? 5 : 20))
      active -= 1
      finished += 1
      if (options.label === 'reviewer') throw new Error('Fixture transport failure')
      return { outcome: 'completed', assignment: null }
    })
  assert.equal(maximum, 2)
  assert.equal(finished, 2)
  assert.equal(observed.action, 'collect')
  assert.equal(observed.outcome, undefined)
  assert.match(observed.observations[0].error, /Fixture transport failure/)
  handoff.jobs[0].role = 'fixer'
  await assert.rejects(execute(source.replace('const handoff = null', `const handoff = ${JSON.stringify(handoff)}`), null),
    /fixer must run alone/)
  console.log('Development workflow offline self-check passed')
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})
