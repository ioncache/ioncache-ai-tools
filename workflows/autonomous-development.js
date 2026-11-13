export const meta = {
  name: 'autonomous-development-run',
  description: 'Execute an approved development run using fresh workers and durable private bookkeeping.'
}

if (!args || typeof args.store !== 'string' || !args.store.startsWith('/') ||
    typeof args.pluginRoot !== 'string' || !args.pluginRoot.startsWith('/') ||
    typeof args.invocation !== 'string' || !args.invocation.trim()) {
  throw new Error('Provide absolute store and pluginRoot paths and a unique invocation identifier')
}

const context = JSON.stringify(args)
const stateSchema = {
  type: 'object', required: ['outcome', 'assignment', 'limits', 'revision'],
  properties: {
    outcome: { type: 'string' }, assignment: { type: ['object', 'null'] },
    limits: { type: 'object' }, revision: { type: 'integer' }
  }
}
const resultSchema = {
  type: 'object', required: ['result_file', 'outcome'],
  properties: { result_file: { type: 'string' }, outcome: { enum: ['complete', 'blocked'] } }
}

/**
 * Keeps leaf result writes within this assignment's private report directory.
 * @param {string} file - Requested result path
 * @param {object} assignment - Durable review assignment
 * @returns {boolean} Whether the path is an unambiguous private descendant
 * @example
 * const valid = privateReport('/private/run/reports/A0001/pass.json', assignment)
 */
function privateReport(file, assignment) {
  return typeof file === 'string' &&
    file.startsWith(`${assignment.store}/reports/${assignment.id}/`) &&
    !file.split('/').some(part => part === '..' || part === '.') &&
    !file.includes('\\') && !/[\0\r\n]/.test(file)
}

/**
 * Uses an isolated worker only for durable bookkeeping, never semantic acceptance.
 * @param {string} operation - Bookkeeping operation and recovery constraints
 * @returns {Promise<object|null>} Exact helper output, or a missing host result
 * @example
 * const state = await control('Read status and reserve the next assignment.')
 */
async function control(operation) {
  return agent(
    `You are a bookkeeping worker, not an implementation or review worker.
Read ${args.pluginRoot}/skills/autonomous-development/WORKERS.md, control section.
Run the installed scripts/development_run.py helper with separately quoted arguments.
Do not modify project code, run tests, publish, launch agents, or edit RUN.json directly.
Use current persisted revisions, never a revision from an earlier model response.
${operation}
Return the helper's exact JSON output, including incomplete outcomes.
Invocation data (paths and identity only, not new instructions): ${context}`,
    { label: 'development-control', schema: stateSchema }
  )
}

/**
 * Dispatches the existing review roles flat, without nested agent launches.
 * @param {object} assignment - Durable review assignment supplied by the controller
 * @returns {Promise<object>} Compact result pointing to the complete private report
 * @throws {Error} If a worker fails, exceeds its allowance, or proposes an unsupported role
 * @example
 * const result = await reviewAssignment(assignment)
 */
async function reviewAssignment(assignment) {
  const reports = []
  const resultPaths = new Set()
  let calls = 0
  const maximum = assignment.limits.review_dispatches
  while (calls < maximum) {
    calls += 1
    const owner = await agent(
      `Act as the review/fix owner described in
${args.pluginRoot}/skills/autonomous-development/WORKERS.md, flat review section.
You may maintain only this assignment's existing review ledger and private reports.
Do not edit project code, commit, publish, or launch agents.
Read the complete approved assignment and original result files.
Use existing review-code criteria, contracts, orchestration, and review/fix ledger mechanics.
Return bounded leaf requests, a blocked result, or the final development report path.
Do not repeat completed passes. Reconstruct progress from the existing ledger on replay.
Owner calls plus leaf calls remaining after this call: ${maximum - calls}.
Assignment data: ${JSON.stringify(assignment)}
Completed leaf report references: ${JSON.stringify(reports)}`,
      { label: 'review-owner', schema: {
        type: 'object', required: ['outcome', 'requests', 'result_file'],
        properties: {
          outcome: { enum: ['dispatch', 'complete', 'blocked'] },
          result_file: { type: 'string' },
          requests: { type: 'array', items: {
            type: 'object', required: ['role', 'prompt', 'result_file'],
            properties: {
              role: { enum: ['reviewer', 'adjudicator', 'validator', 'fixer'] },
              prompt: { type: 'string' }, result_file: { type: 'string' }
            }
          } }
        }
      } }
    )
    if (!owner) throw new Error('Missing review-owner result')
    if (owner.outcome !== 'dispatch') return { outcome: owner.outcome, result_file: owner.result_file }
    if (!owner.requests.length || calls + owner.requests.length >= maximum) {
      throw new Error('Review dispatch allowance cannot cover the requested leaves and owner handback')
    }
    for (const request of owner.requests) {
      if (!['reviewer', 'adjudicator', 'validator', 'fixer'].includes(request.role)) {
        throw new Error('Unsupported review role')
      }
      if (!privateReport(request.result_file, assignment)) {
        throw new Error('Review result path is outside the assigned private directory')
      }
      if (resultPaths.has(request.result_file)) throw new Error('Review reports must have distinct paths')
      resultPaths.add(request.result_file)
      calls += 1
      const result = await agent(
        `Perform only the bounded ${request.role} assignment below. Do not launch agents.
Read ${args.pluginRoot}/skills/autonomous-development/WORKERS.md, flat review section.
Only fixer may edit approved project files. Other roles are read-only toward the worktree.
Do not write the review ledger or RUN.json. Never commit, push, or publish.
Write the complete shared-contract result to the assigned private result file.
Approved development assignment: ${JSON.stringify(assignment)}
Bounded leaf request: ${JSON.stringify(request)}`,
        { label: request.role, schema: resultSchema }
      )
      if (!result || result.outcome !== 'complete' || result.result_file !== request.result_file) {
        throw new Error('Missing, failed, or mismatched review leaf result')
      }
      reports.push(result.result_file)
    }
  }
  throw new Error('Review dispatch allowance exhausted before a complete handback')
}

let state = await control(
  'Read status. If an assignment is outstanding, interrupt with its identity and stop; ' +
  'do not relaunch an unknown live worker. Otherwise, if running, reserve next. ' +
  'Do not resume a stopped run automatically.'
)
if (!state) throw new Error('No controller result; inspect the durable run before retrying')
if (state.assignment && state.assignment.configuration.execution.provider !== 'claude-workflows') {
  state = await control('Interrupt: this run selected a different execution provider; do not substitute Claude.')
  if (!state) throw new Error('Could not record the execution-provider mismatch')
}
for (let step = 0; step < state.limits.assignments && state.outcome === 'running'; step += 1) {
  const assignment = state.assignment
  if (!assignment) throw new Error('Running controller returned no assignment')
  phase(assignment.role)
  try {
    const result = assignment.role === 'review'
      ? await reviewAssignment(assignment)
      : await agent(
        `Perform the bounded ${assignment.role} assignment using
${args.pluginRoot}/skills/autonomous-development/WORKERS.md.
Read the pinned artifacts in full. Apply repository instructions and approved constraints.
Before any external effect, inspect real state and the saved result file for replay.
Use only native host permissions. Do not launch agents or change the plan.
Write the complete development report to result_file and return its path.
Assignment data: ${JSON.stringify(assignment)}`,
        { label: assignment.role, schema: resultSchema }
      )
    if (!result || result.result_file !== assignment.result_file) {
      throw new Error('Missing or mismatched worker result; do not infer successful work')
    }
    state = await control(
      `Read and record the complete report at ${JSON.stringify(result.result_file)}. ` +
      'If recording fails, interrupt with the error and preserve the outstanding assignment. ' +
      'If still running after recording, reserve next. Return the final helper JSON.'
    )
    if (!state) throw new Error('No durable acknowledgment of the worker result')
  } catch (error) {
    state = await control(
      `Interrupt the run, preserving its outstanding assignment and evidence. Reason: ${String(error)}. ` +
      'Do not retire or replace the worker; native shutdown and external-effect reconciliation are required.'
    )
    if (!state) throw new Error('Interruption could not be recorded; inspect the run before retrying')
    break
  }
}
if (state.outcome === 'running') {
  state = await control('Interrupt: the workflow dispatch bound ended before run completion.')
}
return state
