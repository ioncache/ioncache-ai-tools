export const meta = {
  name: 'autonomous-development-run',
  description: 'Run one script-generated worker batch; Python owns state, validation and recovery.'
}

const handoff = null
if (!handoff || !Array.isArray(handoff.jobs) || handoff.jobs.length === 0) {
  throw new Error('Use development_handoff.py prepare, then claim and launch its generated scriptPath without args')
}
if (handoff.jobs.some(job => job.role === 'fixer') && handoff.jobs.length !== 1) {
  throw new Error('A fixer must run alone; regenerate the batch using the pinned helper')
}

/**
 * Runs one frozen purpose, leaving report validation and collection to scripts.
 * @param {object} job - Script-generated job with native model options
 * @param {number} index - Zero-based job index within this batch
 * @returns {Promise<object>} Advisory native outcome, never development acceptance
 * @example
 * const observation = await launch(handoff.jobs[0], 0)
 */
async function launch(job, index) {
  const command = ['python3', `${handoff.pluginRoot}/scripts/development_handoff.py`]
  const boundary = [handoff.store, '--batch', handoff.batch, '--job', String(index + 1)]
  const start = [...command, 'start', ...boundary]
  const finish = [...command, 'finish', ...boundary]
  const candidate = `${job.result_file}.candidate.json`
  const submit = [...command, 'submit', ...boundary, '--candidate', candidate]
  const model = ['python3', `${handoff.pluginRoot}/scripts/development_run.py`, 'model-report',
    handoff.store, '--invocation', handoff.batch, '--call', String(index + 1),
    '--assignment', handoff.assignment, '--role', job.role]
  if (job.options.model) model.push('--selected-model', job.options.model)
  if (job.options.effort) model.push('--selected-effort', job.options.effort)
  try {
    const result = await agent(
      `Before any assigned work, run this argv with separately quoted arguments:
Start arguments: ${JSON.stringify(start)}
If start reports a restart, follow its instruction: reconcile the earlier attempt's effects, never repeat them.
If start fails, do not repeat work or effects. Inspect the existing report and return the limitation.
Record requested and observed model identity with this argv:
Model report arguments: ${JSON.stringify(model)}
Use --source unavailable unless native context exposes actual identity; never infer it from selection.
Assigned result file: ${JSON.stringify(job.result_file)}
Write your complete report there, then validate it using:
Finish arguments: ${JSON.stringify(finish)}
For a development report, the helper can supply assignment and artifact identity fields from a candidate.
Write the candidate to ${JSON.stringify(candidate)}, inside the private run store, then run:
Submit arguments: ${JSON.stringify(submit)}
Candidate fields: outcome, summary, evidence, data; optional worker and model_report.
Review leaves keep their purpose-specific full report contract; owners write their dispatch/final request.
For owner completion, submit outcome, empty requests, and report containing the development candidate;
the helper supplies the final report path and identities.
If validation fails, use its exact errors to correct only the report from existing evidence, within
the reported correction allowance. Never rerun implementation, commits or publication to repair JSON.
Do not fabricate observations to satisfy validation. Preserve earlier evidence and failed candidates.
Return only an advisory notification after the helper validates the file. Native success is not acceptance.
${job.prompt}`,
      { label: job.role, ...job.options, schema: {
        type: 'object', additionalProperties: false, required: ['reported'],
        properties: { reported: { type: 'boolean' }, error: { type: 'string' } }
      } }
    )
    return { job: index + 1, role: job.role, returned: result !== null,
      ...(result?.error ? { error: result.error } : {}) }
  } catch (error) {
    return { job: index + 1, role: job.role, error: String(error) }
  }
}

phase(handoff.jobs[0].role)
const observations = await Promise.all(handoff.jobs.map(launch))
return { batch: handoff.batch, action: 'collect', observations }
